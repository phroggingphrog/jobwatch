"""Per-person removable job limits and the paid cheap-assessment route. Offline: fake gateway, temp dirs only."""
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from jobwatch.util import model_choice as model_choice
from jobwatch import users
from jobwatch.util.llm import LLM
from pipeline.agentic import discovery_settings, execution, service
from pipeline.agentic.api import Principal, create_api
from pipeline.agentic.contracts import AgenticError
from pipeline.agentic.runtime import (MAX_ROLE_TURNS, UNLIMITED_JOB_TOKENS, BatchBudget, JobBudget,
                                      RuntimeErrorSafe, run_role)
from pipeline.agentic.store import AgenticStore
from tests.test_deepagents_runtime import assert_safe_failure, choice, role, transport_llm
from tests.test_discovery_operations import world  # noqa: F401

CFG = {'job_token_ceiling': 250_000, 'job_seconds': 900, 'batch_seconds': 1800, 'batch_token_ceiling': 2_000_000}
CONFIG = {'pipeline': {'agentic': {'batch_token_ceiling': 1234}}}
INCIDENT_CODES = ('token_limit', 'turn_limit', 'deadline_exceeded', 'failed_attempt_limit')


def job(**kwargs):
    batch = BatchBudget('b', token_ceiling=10_000_000, deadline=time.time() + 1800)
    return JobBudget('a' * 64, batch, **kwargs)


# --- turns -------------------------------------------------------------------------------------
def test_unlimited_turns_run_past_the_default_cap_and_finite_turns_still_stop():
    steps = MAX_ROLE_TURNS + 4
    llm, seen = transport_llm([choice('read_evidence', source='cv')] * steps + [choice()])
    result = run_role(role(), {}, job(role_turn_limit=None), llm)
    assert result.turns == steps + 1 and len(seen) == steps + 1

    llm, seen = transport_llm([choice('read_evidence', source='cv')] * steps + [choice()])
    assert_safe_failure('turn_limit', lambda: run_role(role(), {}, job(), llm))
    assert len(seen) == MAX_ROLE_TURNS
    llm, seen = transport_llm([choice('read_evidence', source='cv')] * 6 + [choice()])
    assert_safe_failure('turn_limit', lambda: run_role(role(), {}, job(role_turn_limit=5), llm))


def test_a_callers_own_turn_cap_survives_an_unlimited_job():
    llm, _ = transport_llm([choice('read_evidence', source='cv')] * 4)
    assert_safe_failure('turn_limit', lambda: run_role(role(), {}, job(role_turn_limit=None), llm, max_turns=2))


def test_turn_override_does_not_become_a_failed_attempt_loop():
    b = job(role_turn_limit=None)
    llm, _ = transport_llm([choice('read_evidence', source='cv')] * 30 + [choice()])
    run_role(role(), {}, b, llm)
    assert b.failed_attempts == 0


# --- tokens ------------------------------------------------------------------------------------
def test_unlimited_job_tokens_never_raise_token_limit_but_finite_does():
    b = job(token_ceiling=None)
    assert b.snapshot().job_token_ceiling == UNLIMITED_JOB_TOKENS
    b.reserve('evaluator', 900_000, 12_000)            # far past the 250k default
    b.reserve('evaluator', 900_000, 12_000)
    with pytest.raises(RuntimeErrorSafe) as caught:
        job(token_ceiling=250_000).reserve('evaluator', 300_000, 12_000)
    assert caught.value.code == 'token_limit'


# --- time and the per-call wait ----------------------------------------------------------------
def make_store(tmp_path, name='agentic'):
    conn = sqlite3.connect(str(tmp_path / (name + '.sqlite')))
    store = AgenticStore(conn)
    store.ensure()
    return store


def started(store, limits, timing=None, *, batch_seconds=1800):
    from tests.test_agentic_store import key
    batch = BatchBudget('unit', token_ceiling=2_000_000, deadline=time.time() + batch_seconds)
    store.create_batch(batch.batch_id, batch._state.token_ceiling, batch.deadline)
    claim = store.claim(key(), 'owner', 900)
    return service._budget(store, claim, CFG, batch, None, batch.deadline, limits, timing), batch


def test_unlimited_job_time_follows_the_outer_batch_deadline_not_900_seconds(tmp_path):
    finite, batch = started(make_store(tmp_path, 'finite'), discovery_settings.job_defaults(CFG))
    assert finite.snapshot().job_deadline < batch.deadline - 800
    unlimited, batch = started(make_store(tmp_path, 'unlimited'),
                               {**discovery_settings.job_defaults(CFG), 'job_seconds': None})
    assert unlimited.snapshot().job_deadline == batch.deadline
    assert unlimited.remaining_seconds() > 1700


def test_limits_and_call_waits_reach_the_job_and_none_means_no_cap(tmp_path):
    limits = {'job_token_ceiling': None, 'job_seconds': None, 'job_max_turns': None}
    budget, _ = started(make_store(tmp_path), limits, {'model_call_seconds': None, 'model_call_reasoning_seconds': 900})
    assert (budget.role_turn_limit, budget.call_seconds, budget.call_seconds_reasoning) == (None, None, 900)
    assert budget.snapshot().job_token_ceiling == UNLIMITED_JOB_TOKENS


def test_a_finite_call_wait_cuts_the_gateway_timeout_and_none_leaves_the_job_clock():
    llm, seen = transport_llm([choice()])
    run_role(role(), {}, job(call_seconds=30), llm)
    assert seen[0][2] <= 30
    llm, seen = transport_llm([choice()])
    run_role(role(), {}, job(call_seconds=None), llm)
    assert seen[0][2] > 600


def test_lifting_a_limit_restarts_a_saved_run_that_carried_the_old_one(tmp_path):
    from tests.test_agentic_store import key
    store = make_store(tmp_path)
    batch = BatchBudget('unit', token_ceiling=2_000_000, deadline=time.time() + 1800)
    store.create_batch(batch.batch_id, batch._state.token_ceiling, batch.deadline)
    defaults = discovery_settings.job_defaults(CFG)
    claim = store.claim(key(), 'owner', 900)
    first = service._budget(store, claim, CFG, batch, None, batch.deadline, defaults)
    assert first.snapshot().job_token_ceiling == 250_000
    batch.release(first)
    store.release(claim, status='held', reason='token_limit')
    same = service._budget(store, store.claim(key(), 'owner', 900), CFG, batch, None, batch.deadline, defaults)
    assert same.snapshot().job_token_ceiling == 250_000          # unchanged settings: the saved run is resumed
    batch.release(same)
    claim = store.claim(key(), 'owner', 900) or None
    if claim is None:
        store.conn.execute("UPDATE agentic_runs SET status='held', lease_until=0")
        store.conn.commit()
        claim = store.claim(key(), 'owner', 900)
    lifted = service._budget(store, claim, CFG, batch, None, batch.deadline, {**defaults, 'job_token_ceiling': None})
    assert lifted.snapshot().job_token_ceiling == UNLIMITED_JOB_TOKENS


# --- settings storage and surfaces -------------------------------------------------------------
@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path / 'data'))
    users.create_user_dirs('sam')
    users.create_user_dirs('sue')
    monkeypatch.setattr('jobwatch.util.model_choice.chosen', lambda *a, **k: {})
    return tmp_path


def test_defaults_are_finite_and_unlimited_round_trips_per_person(data_dir):
    base = discovery_settings.get_settings('sam', CONFIG)
    assert base == {'daily_token_ceiling': 1234, 'job_token_ceiling': 250_000, 'job_seconds': 900, 'job_max_turns': 16}
    saved = discovery_settings.set_settings('sam', CONFIG, 1234, job_token_ceiling=None, job_seconds=None,
                                            job_max_turns=40)
    assert saved == {'daily_token_ceiling': 1234, 'job_token_ceiling': None, 'job_seconds': None, 'job_max_turns': 40}
    assert discovery_settings.get_settings('sam', CONFIG) == saved
    assert discovery_settings.get_settings('sue', CONFIG) == base
    assert discovery_settings.job_limits('sam', service._config(CONFIG)) == {
        'job_token_ceiling': None, 'job_seconds': None, 'job_max_turns': 40}


def test_saving_only_the_daily_value_keeps_job_limits_and_old_files_still_read(data_dir):
    discovery_settings.set_settings('sam', CONFIG, 1234, job_seconds=None)
    discovery_settings.set_settings('sam', CONFIG, None)         # what an older client posts
    assert discovery_settings.get_settings('sam', CONFIG)['job_seconds'] is None
    path = discovery_settings._path('sue')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"daily_token_ceiling":500}')
    assert discovery_settings.get_settings('sue', CONFIG)['job_seconds'] == 900


@pytest.mark.parametrize('field', ['job_token_ceiling', 'job_seconds', 'job_max_turns'])
@pytest.mark.parametrize('value', [0, -5, True, 1.5, '9'])
def test_job_limits_must_be_positive_integers_or_null(data_dir, field, value):
    with pytest.raises(ValueError):
        discovery_settings.set_settings('sam', CONFIG, 1234, **{field: value})


def test_damaged_file_falls_back_to_finite_job_limits(data_dir):
    path = discovery_settings._path('sam')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"daily_token_ceiling":true}')
    assert discovery_settings.job_limits('sam', CFG) == discovery_settings.job_defaults(CFG)


def test_native_api_reads_and_writes_job_limits(world):  # noqa: F811
    config, _ = world
    token = 'a' * 40
    headers = {'Authorization': 'Bearer ' + token}
    with TestClient(create_api(credentials={token: Principal('fixture-a')}, config=config)) as client:
        path = '/api/agent/discovery/settings'
        got = client.get(path, headers=headers).json()
        assert got == {'daily_token_ceiling': 2_000_000, 'job_token_ceiling': 250_000, 'job_seconds': 300,
                       'job_max_turns': 16}
        body = {'daily_token_ceiling': None, 'job_token_ceiling': None, 'job_seconds': None}
        assert client.post(path, headers=headers, json=body).json() == {
            'daily_token_ceiling': None, 'job_token_ceiling': None, 'job_seconds': None, 'job_max_turns': 16}
        assert client.post(path, headers=headers, json={'daily_token_ceiling': None}).json()['job_seconds'] is None
        assert client.post(path, headers=headers, json={'daily_token_ceiling': 5, 'job_seconds': 0}).status_code == 422


# --- the run windows ---------------------------------------------------------------------------
def run_batch(monkeypatch, tmp_path, *, person_limits, hard_stop, start_seconds=None):
    """Drive agentic_batch_run with a fake job; return what the job was told and how many were started."""
    seen = []
    monkeypatch.setattr(service, 'enabled', lambda config: True)
    monkeypatch.setattr(service, '_config', lambda config: dict(CFG))
    monkeypatch.setattr(service, '_run_timing', lambda config: {
        'job_start_seconds': 120 if start_seconds is None else start_seconds,
        'model_call_seconds': 180, 'model_call_reasoning_seconds': 600})
    monkeypatch.setattr(service.discovery_settings, 'job_limits', lambda person, cfg: person_limits)
    monkeypatch.setattr(service, 'run_agentic_job', lambda pid, *a, **k: seen.append(k['_invocation_deadline']))
    conn = sqlite3.connect(str(tmp_path / 'batch.sqlite'))
    conn.row_factory = None
    token = execution.HARD_STOP.set(hard_stop)
    try:
        service.agentic_batch_run([1], {}, conn, max_seconds=390, evidence_bundle=object())
    finally:
        execution.HARD_STOP.reset(token)
    return seen


FINITE = {'job_token_ceiling': 250_000, 'job_seconds': 900, 'job_max_turns': 16}
UNLIMITED = {'job_token_ceiling': None, 'job_seconds': None, 'job_max_turns': None}


def test_a_finite_job_is_cut_at_the_run_window(monkeypatch, tmp_path):
    now = time.time()
    (cut,) = run_batch(monkeypatch, tmp_path, person_limits=FINITE, hard_stop=now + 840)
    assert now + 380 < cut < now + 395


def test_an_unlimited_job_that_started_inside_the_window_may_run_to_the_hard_stop(monkeypatch, tmp_path):
    now = time.time()
    (cut,) = run_batch(monkeypatch, tmp_path, person_limits=UNLIMITED, hard_stop=now + 840)
    assert now + 835 < cut < now + 845


def test_the_hard_stop_also_caps_the_window_and_blocks_new_starts_after_it(monkeypatch, tmp_path):
    now = time.time()
    assert run_batch(monkeypatch, tmp_path, person_limits=UNLIMITED, hard_stop=now + 60) == []   # < 120 s left
    (cut,) = run_batch(monkeypatch, tmp_path, person_limits=UNLIMITED, hard_stop=now + 60, start_seconds=0)
    assert cut < now + 65


def test_a_start_rule_of_zero_starts_a_job_with_a_few_seconds_left(monkeypatch, tmp_path):
    now = time.time()
    assert run_batch(monkeypatch, tmp_path, person_limits=FINITE, hard_stop=now + 20) == []
    assert len(run_batch(monkeypatch, tmp_path, person_limits=FINITE, hard_stop=now + 20, start_seconds=0)) == 1


def test_timing_knobs_are_validated_and_null_means_unbounded():
    assert service._run_timing({}) == {'job_start_seconds': 120, 'model_call_seconds': 180,
                                       'model_call_reasoning_seconds': 600}
    cfg = {'pipeline': {'agentic': {'job_start_seconds': None, 'model_call_seconds': None}}}
    assert service._run_timing(cfg)['job_start_seconds'] == 0 and service._run_timing(cfg)['model_call_seconds'] is None
    with pytest.raises(AgenticError):
        service._run_timing({'pipeline': {'agentic': {'model_call_seconds': -1}}})


# --- the paid cheap-assessment route ------------------------------------------------------------
def gateway():
    return LLM(keys=['synthetic'], base_url=model_choice.SERVER_URL)


def test_deepseek_flash_is_allowed_for_assessment_and_free_or_stealth_routes_stay_refused():
    llm = gateway()
    execution.require_route(llm, 'deepseek-flash')
    for model in ('deepseek-flash:free', 'free-stack', 'stealth-stack', 'openrouter/stealth-1', 'claude/opus',
                  'openai/astra', '../bad'):
        with pytest.raises(AgenticError, match='model_not_allowed'):
            execution.require_route(llm, model)
    with pytest.raises(AgenticError, match='model_not_allowed'):
        execution.require_route(llm, 'deepseek-flash', embedding=True)          # embeddings stay on their own route
    with pytest.raises(AgenticError, match='gateway_not_allowed'):
        execution.require_route(LLM(keys=['synthetic'], base_url='https://other.example/v1'), 'deepseek-flash')


def test_cheap_assessment_profile_moves_only_the_evaluator_role(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path / 'data'))
    users.create_user_dirs('sam')
    users.create_user_dirs('sue')
    model_choice.apply_profile('cheap-assessment', 'sam')
    assert model_choice.chosen('sam') == {'evaluator': 'deepseek-flash'}
    assert model_choice.chosen('sue') == {}
    assert model_choice.get_model('writer', 'sam') != 'deepseek-flash'           # drafting is untouched
    with users.use('sam'):
        cfg = service._config({})
    assert cfg['evaluator_model'] == 'deepseek-flash' and cfg['worker_model'] != 'deepseek-flash'
    assert cfg['reviewer_model'] != 'deepseek-flash' and cfg['answer_model'] != 'deepseek-flash'
    with pytest.raises(KeyError):
        model_choice.apply_profile('unknown', 'sam')


def test_a_gateway_that_rejects_json_mode_or_reasoning_gets_one_request_without_them():
    calls = []

    def transport(url, headers, body, timeout):
        calls.append(dict(body))
        if 'response_format' in body:
            return 400, {'error': {'message': "Unsupported parameter: 'response_format'"}}
        if 'reasoning_effort' in body:
            return 400, {'error': {'message': 'reasoning_effort is not supported'}}
        return 200, {'choices': [{'message': {'content': '{"ok": true}'}}], 'usage': {'prompt_tokens': 3, 'completion_tokens': 2}}

    result = LLM(transport=transport, keys=['k']).chat_once('deepseek-flash', [{'role': 'user', 'content': 'json'}],
                                                             reasoning_effort='high')
    assert result.data == {'ok': True}
    assert 'response_format' in calls[0] and 'reasoning_effort' in calls[0]
    assert 'response_format' not in calls[-1] and 'reasoning_effort' not in calls[-1] and len(calls) == 3


def test_other_bad_requests_are_not_retried():
    calls = []
    def transport(url, headers, body, timeout):
        calls.append(1)
        return 400, {'error': {'message': 'context too long'}}
    from jobwatch.util.llm import SafeLLMError
    with pytest.raises(SafeLLMError):
        LLM(transport=transport, keys=['k']).chat_once('deepseek-flash', [{'role': 'user', 'content': 'x'}])
    assert len(calls) == 1


# --- model profiles: native tools, json mode, output floor ----------------------------------------
def tool_reply(*calls, content=None):
    return 200, {'choices': [{'finish_reason': 'tool_calls', 'message': {
        'content': content, 'reasoning_content': 'thinking',
        'tool_calls': [{'id': f'c{i}', 'type': 'function', 'function': {'name': n, 'arguments': a}}
                       for i, (n, a) in enumerate(calls)]}}],
        'usage': {'prompt_tokens': 11, 'completion_tokens': 7,
                  'completion_tokens_details': {'reasoning_tokens': 4}}}


@pytest.fixture
def sam(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path / 'data'))
    users.create_user_dirs('sam')
    return 'sam'


def test_default_profile_keeps_the_json_path_and_sends_no_tools(sam):
    llm, seen = transport_llm([choice()])
    with users.use(sam):
        run_role(role(), {}, job(), llm)
    body = seen[0][1]
    assert body['response_format'] == {'type': 'json_object'} and 'tools' not in body and body['max_tokens'] == 12_000


def test_native_tools_profile_sends_tools_reads_the_tool_call_and_floors_max_tokens(sam):
    model_choice.set_gateway_profile('claude/sonnet', {'native_tools': True, 'json_mode': False,
                                                       'min_output_tokens': 16_000}, sam)
    calls, replies = [], iter([tool_reply(('read_evidence', '{"source": "cv"}')),
                               tool_reply(('finish', '{"answer": "done"}'))])

    def transport(url, headers, body, timeout):
        calls.append(body)
        return next(replies)

    b = job()
    with users.use(sam):
        result = run_role(role(), {}, b, LLM(transport=transport, keys=['k']))
    assert result.output.answer == 'done' and result.tool_trace == ('read_evidence', 'finish')
    for body in calls:
        assert 'response_format' not in body and body['tool_choice'] == 'auto' and body['max_tokens'] == 16_000
        assert {t['function']['name'] for t in body['tools']} == {'read_evidence', 'finish'}
        assert body['tools'][0]['type'] == 'function' and 'properties' in body['tools'][0]['function']['parameters']
    assert b.snapshot().reservations[0].requested_output_tokens == 16_000      # budget reserves what is requested
    assert b.charged_tokens == 36                                              # actual usage, reasoning included


def test_native_tools_content_json_is_still_accepted_when_the_model_does_not_call_a_tool(sam):
    model_choice.set_gateway_profile('claude/sonnet', {'native_tools': True}, sam)
    llm, seen = transport_llm([choice()])
    with users.use(sam):
        assert run_role(role(), {}, job(), llm).output.answer == 'complete'
    assert 'tools' in seen[0][1]


def test_malformed_native_tool_call_is_a_safe_failure_not_a_crash(sam):
    model_choice.set_gateway_profile('claude/sonnet', {'native_tools': True}, sam)
    llm, _ = transport_llm([tool_reply(('finish', '{not json'))])
    with users.use(sam):
        assert_safe_failure('model_invalid_response', lambda: run_role(role(), {}, job(), llm))


def test_json_mode_off_drops_response_format_but_still_parses_json_text(sam):
    model_choice.set_gateway_profile('claude/sonnet', {'json_mode': False}, sam)
    llm, seen = transport_llm([choice()])
    with users.use(sam):
        assert run_role(role(), {}, job(), llm).output.answer == 'complete'
    assert 'response_format' not in seen[0][1] and 'tools' not in seen[0][1]


def test_profiles_are_per_person_per_model_and_ignore_bad_values(sam, tmp_path):
    users.create_user_dirs('sue')
    model_choice.set_gateway_profile('deepseek-flash', {'native_tools': True, 'min_output_tokens': 16_000}, sam)
    assert model_choice.gateway_profile('deepseek-flash', sam) == {
        'native_tools': True, 'json_mode': True, 'min_output_tokens': 16_000}
    assert model_choice.gateway_profile('deepseek-flash', 'sue') == model_choice.PROFILE_DEFAULT
    assert model_choice.gateway_profile('openai/sol', sam) == model_choice.PROFILE_DEFAULT
    path = users.user_dir(sam) / 'config' / 'model_profiles.json'
    path.write_text('{"deepseek-flash": {"native_tools": "yes", "min_output_tokens": -4, "json_mode": 0}}')
    assert model_choice.gateway_profile('deepseek-flash', sam) == model_choice.PROFILE_DEFAULT


def test_chat_once_native_tools_returns_the_same_shape_as_the_json_path():
    llm = LLM(transport=lambda *a: tool_reply(('finish', '{"answer": "x"}'), ('read_evidence', '{"source": "cv"}')),
              keys=['k'])
    out = llm.chat_once('deepseek-flash', [{'role': 'user', 'content': 'q'}], max_tokens=500,
                        tools=[{'type': 'function', 'function': {'name': 'finish', 'parameters': {}}}])
    assert out.data == {'tool': 'finish', 'arguments': {'answer': 'x'}} and out.usage == {'prompt_tokens': 11, 'completion_tokens': 7}
