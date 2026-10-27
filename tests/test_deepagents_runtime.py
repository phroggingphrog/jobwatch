"""Real Deep Agents graph acceptance with deterministic local-gateway transport."""
from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from pipeline.agentic.runtime import MAX_FAILED_ATTEMPTS, MAX_ROLE_TURNS
from langchain.agents.middleware import AgentMiddleware
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.globals import set_debug
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.runnables.config import var_child_runnable_config
from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict

from jobwatch.llm import BASE_URL, LLM
from pipeline.agentic import deepagents_runtime as runtime
from pipeline.agentic.contracts import BudgetCheckpoint, RequirementSet, StrictFrozen
from pipeline.agentic.runtime import (BatchBudget, JobBudget, RoleSpec, RuntimeErrorSafe,
                                     Tool, run_role)


class ReadArgs(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    source: str


class Answer(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    answer: str
    citations: tuple[str, ...] = ()


def budget(*, token_ceiling=100_000, clock=lambda: 1000, persistence=None):
    return JobBudget("a" * 64, BatchBudget("b", clock=clock), clock=clock,
                     deadline=1800, token_ceiling=token_ceiling, persist=persistence)


def role(*, name="evaluator", handler=lambda args, context: {"text": "verified synthetic evidence"},
         model="claude/sonnet"):
    return RoleSpec(name=name, model=model, system_prompt="Synthetic private role",
                    tools=(Tool("read_evidence", ReadArgs, handler),
                           Tool("finish", Answer, lambda a, c: a)), terminal_tools=("finish",))


def choice(name="finish", **args):
    return {"tool": name, "arguments": args or {"answer": "complete"}}


def transport_llm(choices, *, usage=None):
    pending = iter(choices)
    seen = []

    def transport(url, headers, body, timeout):
        seen.append((url, body, timeout))
        payload = next(pending)
        if isinstance(payload, tuple):
            return payload
        return 200, {"choices": [{"message": {"content": json.dumps(payload)}}],
                     "usage": usage or {"prompt_tokens": 11, "completion_tokens": 7}}

    return LLM(transport=transport, keys=["synthetic-key"]), seen


def test_backend_chat_dispatch_synthetic(tmp_path, monkeypatch):
    """One backend conversation through the real graph, with no network/live data."""
    import sqlite3
    from jobwatch import users, model_choice
    from pipeline.agentic.chat import dispatch
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(model_choice, 'SERVER_URL', 'http://127.0.0.1:20128/v1')
    monkeypatch.setattr(model_choice, 'get_model', lambda role: 'claude/sonnet')
    choices = [
        choice('write_todos', todos=[{'content': 'Inspect then request preparation', 'status': 'in_progress'}]),
        choice('read_file', file_path='/skills/career-ops/SKILL.md'),
        choice('write_file', file_path='/memories/AGENTS.md', content='Synthetic preference: concise answers.'),
        choice('task', subagent_type='career-reader', description='Inspect synthetic job 7'),
        choice('inspect_job', posting_id=7),
        {'answer': 'Job 7 is missing; no invented facts.'},
        choice('run_career_ops', posting_id=7),
        {'answer': 'Deferred: agentic_disabled. No application submitted.'},
        choice('read_file', file_path='/memories/AGENTS.md'),
        {'answer': 'Your synthetic preference is concise answers.'},
        {'answer': 'Separate person; no previous messages.'},
    ]
    llm, seen = transport_llm(choices)
    llm.base_url = model_choice.SERVER_URL
    for person in ('fixture-a', 'fixture-b'):
        root = users.user_dir(person)
        root.mkdir(parents=True)
        with sqlite3.connect(root / 'jobwatch.db') as conn:
            conn.execute('CREATE TABLE postings(id INTEGER PRIMARY KEY)')
    cfg = {'agentic': {'enabled': False}}
    def turn(person='fixture-a', thread_id='conversation', **kwargs):
        return dispatch(person=person, thread_id=thread_id, config=cfg, llm=llm, **kwargs)
    first = turn(message='Inspect job 7 and prepare it')
    print('FIRST', json.dumps(first))
    assert first['status'] == 'interrupted'
    assert first['tools'] == ['write_todos', 'read_file', 'write_file', 'task']
    assert first['interrupts'][0]['action_requests'][0]['name'] == 'run_career_ops'
    assert_safe_failure('human_decision_required', lambda: turn(decisions=[{'type': 'approve'}]))
    resumed = turn(decisions=[{'type': 'approve'}], human_decision=True)
    print('RESUMED', json.dumps(resumed))
    assert resumed['status'] == 'complete' and 'agentic_disabled' in resumed['answer']
    memory = turn(thread_id='new-thread', message='Recall my preference')
    print('MEMORY', json.dumps(memory))
    assert 'Synthetic preference: concise answers.' in json.dumps(seen[-1])
    other = turn(person='fixture-b', message='Hello')
    print('ISOLATION', json.dumps(other))
    assert other['tools'] == [] and 'Synthetic preference' not in json.dumps(seen[-1])
    assert 'Inspect job 7' not in json.dumps(seen[-1])
    print('RESULT: planning, skill read, specialist, SQLite reopen/resume, approval, defer, cross-thread memory and person isolation exercised; synthetic transport only.')


@pytest.mark.parametrize('message', ['Please use my attached CV.', ''])
def test_chat_receives_owned_upload_references_without_changing_human_words(tmp_path, monkeypatch, message):
    from jobwatch import users, model_choice
    from jobwatch.candidate import intake
    from pipeline.agentic.chat import dispatch
    from pipeline.agentic.execution import Execution

    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(model_choice, 'SERVER_URL', 'http://127.0.0.1:20128/v1')
    monkeypatch.setattr(model_choice, 'get_model', lambda role, *args: 'claude/sonnet')
    for person in ('fixture-a', 'fixture-b'):
        users.create_user_dirs(person)
    upload = intake.save_upload('fixture-a', 'cv.txt', b'Synthetic document evidence only.', 'cv')
    llm, seen = transport_llm([{'answer': 'What kind of work are you looking for?'},
                              {'answer': 'I can use the document you attached.'}])
    llm.base_url = model_choice.SERVER_URL
    execution = Execution('synthetic-attachment-turn')
    result = dispatch(person='fixture-a', thread_id='uploaded', message=message,
                      upload_ids=[upload['upload_id']], config={'agentic': {'enabled': False}},
                      llm=llm, execution=execution)
    assert result['status'] == 'complete'
    assert result['answer'] == 'What kind of work are you looking for?'
    assert result['tools'] == [] and result['interactions'] == []
    assert upload['upload_id'] in seen[0][1]['messages'][0]['content']
    assert 'Synthetic document evidence only.' not in json.dumps(seen)
    assert execution.human_texts == (message,)
    assert intake.current_version('fixture-a') is None
    followup = dispatch(person='fixture-a', thread_id='uploaded', message='Use the document I attached.',
                        config={'agentic': {'enabled': False}}, llm=llm)
    assert followup['status'] == 'complete'
    assert upload['upload_id'] in seen[1][1]['messages'][0]['content']
    with pytest.raises(RuntimeErrorSafe, match='upload_not_found'):
        dispatch(person='fixture-b', thread_id='foreign', message='Use a file.',
                 upload_ids=[upload['upload_id']], config={'agentic': {'enabled': False}}, llm=llm)
    assert len(seen) == 2  # cross-person references fail before a model sees them


def test_native_api_conversation_approval_and_recovery(tmp_path, monkeypatch):
    """Exercise the real native API and graph with isolated synthetic transport."""
    import sqlite3
    import time
    from fastapi.testclient import TestClient
    from jobwatch import users, model_choice
    from pipeline.agentic.api import create_api, Principal
    from pipeline.agentic.api_store import APIStore
    from pipeline.agentic.chat import skill_version

    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(model_choice, 'SERVER_URL', 'http://127.0.0.1:20128/v1')
    monkeypatch.setattr(model_choice, 'get_model', lambda role: 'claude/sonnet')
    cfg = {'agentic': {'enabled': False}}
    key, approval, other = 'fixture-run-' + 'a' * 40, 'fixture-approval-' + 'b' * 40, 'fixture-other-' + 'c' * 40
    credentials = {key: Principal('fixture-a'),
        approval: Principal('fixture-a', frozenset({'read','interact','approve'})), other: Principal('fixture-b')}
    llm, seen = transport_llm([
        choice('ask_human', question='What is your synthetic preference?'),
        choice('run_career_ops', posting_id=7),
        {'answer': 'Deferred: agentic_disabled. No application submitted.'},
        choice('prepare_application', posting_id=7),
        {'answer': 'Recovered synthetic request.'},
    ])
    llm.base_url = model_choice.SERVER_URL
    for person in ('fixture-a','fixture-b'):
        root = users.user_dir(person)
        root.mkdir(parents=True)
        with sqlite3.connect(root / 'jobwatch.db') as conn:
            conn.execute('CREATE TABLE postings(id INTEGER PRIMARY KEY)')
    def app():
        return create_api(credentials=credentials, config=cfg, llm_factory=lambda p: llm)
    def headers(token=key, idem='synthetic-request'):
        return {'Authorization': 'Bearer ' + token, 'Idempotency-Key': idem}
    def wait(client, ident):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = client.get('/api/agent/runs/' + ident, headers=headers()).json()
            if result['state'] not in ('queued','running'):
                return result
            time.sleep(0.02)
        pytest.fail('synthetic native run did not settle')

    # A contention deferral has not touched the graph and must retry the original
    # turn rather than recover a previous conversation checkpoint.
    with APIStore('fixture-a') as store:
        deferred_thread = store.create_thread(skill_version())['id']
        deferred_id = store.enqueue(deferred_thread, {'message': 'deferred'}, 'lock-contention')
        store.finish(deferred_id, error='person_busy')
        store.retry(deferred_id)
        assert 'recover' not in json.loads(store.raw_run(deferred_id)['input_json'])
        store.cancel(deferred_id)

    with TestClient(app()) as client:
        assert client.get('/api/agent/capabilities').status_code == 401
        thread = client.post('/api/agent/threads', headers=headers()).json()['id']
        route = '/api/agent/threads/' + thread + '/runs'
        first = client.post(route, json={'message':'Prepare synthetic job 7'}, headers=headers())
        assert first.status_code == 202
        ident = first.json()['id']
        assert client.post(route, json={'message':'Prepare synthetic job 7'}, headers=headers()).json()['id'] == ident
        assert client.post(route, json={'message':'changed'}, headers=headers()).status_code == 409
        assert client.get('/api/agent/runs/' + ident, headers=headers(other)).status_code == 404
        invalid = client.post(route, json={'message':'x','person':'private-marker'}, headers=headers())
        assert invalid.status_code == 422 and 'private-marker' not in invalid.text
        question = wait(client, ident)
        assert question['state'] == 'waiting_for_input', question
        question_route = '/api/agent/interactions/' + question['interactions'][0]['id'] + '/responses'
        assert client.post(question_route, json={'decision':'answer','answer':'Concise'}, headers=headers()).status_code == 403
        reply = client.post(question_route, json={'decision':'answer','answer':'Concise'}, headers=headers(approval))
        assert reply.status_code == 202, reply.text
        pending = wait(client, reply.json()['run_id'])
        assert pending['state'] == 'waiting_for_approval', pending
        action_route = '/api/agent/interactions/' + pending['interactions'][0]['id'] + '/responses'
        assert client.post(action_route, json={'decision':'approve'}, headers=headers()).status_code == 403
        accepted = client.post(action_route, json={'decision':'approve'}, headers=headers(approval))
        completed = wait(client, accepted.json()['run_id'])
        assert completed['state'] == 'completed', completed
        assert completed['result']['outcomes'][0]['reason'] == 'agentic_disabled'
        assert client.post(action_route, json={'decision':'approve'}, headers=headers(approval)).json()['run_id'] == completed['id']
        assert client.post(action_route, json={'decision':'reject'}, headers=headers(approval)).status_code == 409
        events = client.get('/api/agent/runs/' + completed['id'] + '/events', headers=headers())
        assert 'event: completed' in events.text and 'Deferred:' not in events.text
        assert 'What is your synthetic preference?' not in events.text

        # A changed binding cannot approve even the disabled synthetic operation.
        second = client.post(route, json={'message':'Prepare again'}, headers=headers(idem='second')).json()['id']
        stale = wait(client, second)
        interaction = stale['interactions'][0]['id']
        with APIStore('fixture-a') as store:
            payload = dict(stale['interactions'][0]); payload.pop('id'); payload.pop('expires_at'); payload.pop('answered')
            payload['binding']['digest'] = '0' * 64
            with store.conn:
                store.conn.execute('UPDATE api_interactions SET payload=? WHERE id=?', (json.dumps(payload), interaction))
        submitted = client.post('/api/agent/interactions/' + interaction + '/responses',
                                json={'decision':'approve'}, headers=headers(approval))
        rejected = wait(client, submitted.json()['run_id'])
        assert rejected['state'] == 'failed' and rejected['error'] == 'approval_inputs_changed'

        # Document ownership, integrity, and absence of host paths from the API.
        pdf = users.user_dir('fixture-a') / 'fixture.pdf'
        pdf.write_bytes(b'%PDF synthetic fixture')
        import hashlib
        with APIStore('fixture-a') as store, store.conn:
            store.conn.execute('INSERT INTO api_artifacts VALUES(?,?,?,?,?)',
                ('fixture-artifact', completed['id'], 'cv', str(pdf), hashlib.sha256(pdf.read_bytes()).hexdigest()))
        assert client.get('/api/agent/artifacts/fixture-artifact', headers=headers()).content == pdf.read_bytes()
        assert client.get('/api/agent/artifacts/fixture-artifact', headers=headers(other)).status_code == 404
        pdf.write_bytes(b'changed')
        assert client.get('/api/agent/artifacts/fixture-artifact', headers=headers()).status_code == 409

    # Crash recovery is explicit: queued work is claimable; an uncertain running
    # operation is marked interrupted and requires an authenticated retry.
    with APIStore('fixture-a') as store:
        recovery_thread = store.create_thread(skill_version())['id']
        recovery_id = store.enqueue(recovery_thread, {'message':'Recover this synthetic request'}, 'recovery')
        assert store.claim_next()['id'] == recovery_id
    with TestClient(app()) as client:
        assert client.get('/api/agent/runs/' + recovery_id, headers=headers()).json()['state'] == 'interrupted'
        assert client.post('/api/agent/runs/' + recovery_id + '/retry', headers=headers()).status_code == 202
        recovered = wait(client, recovery_id)
        assert recovered['state'] == 'completed', recovered
        assert recovered['result']['answer'] == 'Recovered synthetic request.'
        original_calls = len(seen)
    # Simulate graph completion immediately before the HTTP result was persisted.
    with APIStore('fixture-a') as store, store.conn:
        store.conn.execute("UPDATE api_runs SET state='running',result_json=NULL WHERE id=?", (recovery_id,))
    with TestClient(app()) as client:
        assert client.post('/api/agent/runs/' + recovery_id + '/retry', headers=headers()).status_code == 202
        same = wait(client, recovery_id)
        assert same['state'] == 'completed' and same['result']['answer'] == 'Recovered synthetic request.'
        assert len(seen) == original_calls
        assert same['result']['usage']['model_calls'] == 1
    print('NATIVE API: question, approval, idempotency, isolation, sanitized events, artifacts, stale decision and restart recovery exercised.')


@pytest.mark.parametrize('approval', [False, True])
def test_recovery_requires_fresh_response_for_later_interrupt(tmp_path, monkeypatch, approval):
    from jobwatch import model_choice
    from pipeline.agentic.chat import dispatch
    from pipeline.agentic.execution import Execution
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(model_choice, 'get_model', lambda role: 'claude/sonnet')
    action = lambda text: choice('prepare_application', posting_id=7) if approval else choice('ask_human', question=text)
    llm, seen = transport_llm([action('First question'), action('Second question'), {'answer': 'Should not run yet'}])
    turn = lambda **kw: dispatch(person='fixture-a', thread_id='later-interrupt', config={'agentic': {'enabled':False}}, llm=llm, **kw)
    first = turn(message='Begin', execution=Execution('initial'))
    decision = {'type':'approve'} if approval else {'type':'respond','message':'First answer'}
    args = dict(decisions=[decision], human_decision=True, expected_checkpoint=first['checkpoint_id'])
    later = turn(**args, execution=Execution('resume'))
    assert later['status']=='interrupted'
    recovered = turn(**args, execution=Execution('resume'), recover=True)
    assert recovered['status']=='interrupted', recovered
    assert recovered['checkpoint_id']==later['checkpoint_id']
    assert recovered['interactions']==later['interactions'] and len(seen)==2


def test_recovery_before_first_checkpoint_on_existing_thread(tmp_path, monkeypatch):
    from jobwatch import model_choice
    from pipeline.agentic.chat import dispatch
    from pipeline.agentic.execution import Execution
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(model_choice, 'get_model', lambda role: 'claude/sonnet')
    llm, seen = transport_llm([{'answer':'Previous turn'}, {'answer':'New turn'}])
    turn = lambda **kw: dispatch(person='fixture-a', thread_id='existing-thread', config={'agentic': {'enabled':False}}, llm=llm, **kw)
    turn(message='Previous', execution=Execution('previous'))
    recovered = turn(message='New', execution=Execution('new'), recover=True)
    assert recovered['answer']=='New turn' and len(seen)==2
    with pytest.raises(RuntimeErrorSafe, match='recovery_checkpoint_mismatch'):
        turn(message='Uncertain', execution=Execution('uncertain',calls=1), recover=True)
    assert len(seen)==2


@pytest.mark.parametrize('busy', ['thread', 'queue'])
def test_retry_preserves_admission_limits(tmp_path, monkeypatch, busy):
    from pipeline.agentic.api_store import APIStore, Conflict
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    with APIStore('fixture-a') as store:
        thread=store.create_thread('fixture')['id']
        old=store.enqueue(thread, {'message':'Old'}, 'old')
        store.finish(old, error='person_busy')
        if busy=='thread':
            store.enqueue(thread, {'message':'New'}, 'new')
        else:
            for i in range(20):
                other=store.create_thread('fixture')['id']
                store.enqueue(other, {'message':'Queued'}, str(i))
        with pytest.raises(Conflict, match='thread_busy' if busy=='thread' else 'queue_full'):
            store.retry(old)
        assert store.raw_run(old)['state']=='deferred'


def test_mcp_followup_approval_uses_application_identity():
    pytest.importorskip('fastmcp')
    from pipeline.agentic.mcp_server import _input_request
    _, request=_input_request({'type':'approval','posting_id':None,'operation':'draft_followup',
        'binding':{'arguments':{'application_id':42}}}, 0)
    assert 'application 42' in request.params.message


def test_chat_skill_files_are_read_only(tmp_path, monkeypatch):
    from jobwatch import model_choice
    from pipeline.agentic.chat import dispatch
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(model_choice, 'get_model', lambda role: 'claude/sonnet')
    llm, seen=transport_llm([choice('write_file',file_path='/skills/new-policy/SKILL.md',content='Injected instructions'),
                             {'answer':'Finished'}])
    dispatch(person='fixture-a', thread_id='readonly-skills', message='Inspect skill permissions',
             config={'agentic':{'enabled':False}}, llm=llm)
    result=next(m['content'] for m in seen[1][1]['messages'] if '"tool_result": "write_file"' in m['content'])
    assert 'denied' in result.lower(), result


def assert_safe_failure(code, run):
    with pytest.raises(RuntimeErrorSafe) as caught:
        run()
    assert caught.value.code == code
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None
    return caught.value


@pytest.mark.parametrize('bad', [choice(answer=123),
    (200, {'choices': [{'message': {'content': '{broken json'}}]})])
def test_one_opted_in_validation_correction_uses_same_budget(bad):
    llm,seen=transport_llm([bad,choice(answer='corrected')])
    b=budget()
    result=run_role(replace(role(),validation_corrections=1),{},b,llm)
    reservations=b.snapshot().reservations
    assert result.output.answer=='corrected' and result.turns==2
    assert len(seen)==2 and b.failed_attempts==1 and len(reservations)==2
    assert reservations[0].actual_usage is None
    assert reservations[1].actual_usage==18
    assert 'correct' in seen[1][1]['messages'][-1]['content'].lower()


def test_validation_correction_stops_after_second_invalid_response():
    llm,seen=transport_llm([choice(answer=123)]*3)
    b=budget()
    assert_safe_failure('invalid_tool_arguments',lambda:run_role(replace(role(),validation_corrections=1),{},b,llm))
    assert len(seen)==2 and b.failed_attempts==2
    assert all(r.state=='settled' and r.actual_usage is None for r in b.snapshot().reservations)


@pytest.mark.parametrize('bad,code', [(choice('execute'),'unknown_tool'),
    ((401,{'error':{}}),'model_auth'),((429,{'error':{}}),'model_rate_limited')])
def test_opted_in_correction_never_retries_nonvalidation_failures(bad,code):
    llm,seen=transport_llm([bad,choice()]);b=budget()
    assert_safe_failure(code,lambda:run_role(replace(role(),validation_corrections=1),{},b,llm))
    assert len(seen)==1 and b.failed_attempts==1


def test_one_transient_provider_error_is_retried_once(monkeypatch):
    monkeypatch.setattr('pipeline.agentic.deepagents_runtime.time.sleep',lambda s:None)
    llm,seen=transport_llm([(500,{'error':{}}),choice(),choice()]);b=budget()
    run_role(role(),{},b,llm)
    assert len(seen)==2 and b.failed_attempts==1
    llm,seen=transport_llm([(500,{'error':{}})]*3);b=budget()
    assert_safe_failure('model_transient',lambda:run_role(role(),{},b,llm))
    assert len(seen)==2 and b.failed_attempts==2


def test_validation_correction_cannot_renew_turn_limit():
    llm,seen=transport_llm([choice(answer=123),choice()]);b=budget()
    assert_safe_failure('turn_limit',lambda:run_role(replace(role(),validation_corrections=1),{},b,llm,max_turns=1))
    assert len(seen)==1 and b.failed_attempts==1


def test_validation_correction_retains_failed_reservation_when_budget_runs_out():
    llm,seen=transport_llm([choice(answer=123),choice()]);b=budget(token_ceiling=20_000)
    assert_safe_failure('token_limit',lambda:run_role(replace(role(),validation_corrections=1),{},b,llm))
    assert len(seen)==1 and b.failed_attempts==1
    assert len(b.snapshot().reservations)==1 and b.snapshot().reservations[0].actual_usage is None


def test_validation_correction_cannot_renew_deadline():
    now=[1000]
    def persist(checkpoint, **kwargs):
        if any(r.state=='settled' for r in checkpoint.reservations):now[0]=1900
    b=budget(clock=lambda:now[0],persistence=persist)
    llm,seen=transport_llm([choice(answer=123),choice()])
    assert_safe_failure('deadline_exceeded',lambda:run_role(replace(role(),validation_corrections=1),{},b,llm))
    assert len(seen)==1


def test_invalid_tool_is_never_executed_during_correction():
    invoked=[]
    spec=replace(role(handler=lambda *args:invoked.append(True)),validation_corrections=1)
    llm,seen=transport_llm([choice('read_evidence',source=123),choice()])
    result=run_role(spec,{},budget(),llm)
    assert not invoked and result.tool_trace==('finish',) and len(seen)==2


def test_validation_correction_cannot_reset_existing_failure_limit():
    b=budget()
    for _ in range(MAX_FAILED_ATTEMPTS-1):b.failed('invalid_tool_arguments')
    llm,seen=transport_llm([choice(answer=123),choice()])
    assert_safe_failure('failed_attempt_limit',lambda:run_role(replace(role(),validation_corrections=1),{},b,llm))
    assert len(seen)==1 and b.failed_attempts==MAX_FAILED_ATTEMPTS


def test_correction_is_once_per_role_not_once_per_tool():
    llm,seen=transport_llm([choice('read_evidence',source=123),
        choice('read_evidence',source='verified'),choice(answer=123),choice()])
    b=budget()
    assert_safe_failure('invalid_tool_arguments',lambda:run_role(replace(role(),validation_corrections=1),{},b,llm))
    assert len(seen)==3 and b.failed_attempts==2


def test_correction_does_not_retry_a_clipped_response():
    clipped=(200,{'choices':[{'finish_reason':'length','message':{'content':'{}'}}]})
    llm,seen=transport_llm([clipped,choice()]);b=budget()
    assert_safe_failure('model_truncated_response',lambda:run_role(replace(role(),validation_corrections=1),{},b,llm))
    assert len(seen)==1


@pytest.mark.parametrize('value',[-1,2,True,'1'])
def test_correction_limit_configuration_is_strict(value):
    with pytest.raises(ValueError,match='invalid_validation_corrections'):
        replace(role(),validation_corrections=value)


@pytest.mark.parametrize("remaining,expected", [(800, 180), (35, 35)])
def test_structured_response_timeout_preserves_job_deadline(remaining, expected):
    llm, seen = transport_llm([choice(answer="supported")])
    b = budget(clock=lambda: 1800 - remaining)
    run_role(role(), {}, b, llm)
    assert seen[0][2] == pytest.approx(expected, abs=0.1)


def test_actual_deepagent_compiles_invokes_and_selects_native_tools(monkeypatch):
    built = []
    original = runtime.create_deep_agent

    def build(**kwargs):
        graph = original(**kwargs)
        built.append({"kwargs": kwargs, "invoked": False})

        def invoke(*args, **invoke_kwargs):
            built[-1]["invoked"] = True
            return graph.invoke(*args, **invoke_kwargs)

        return SimpleNamespace(invoke=invoke)

    monkeypatch.setattr(runtime, "create_deep_agent", build)
    calls = []
    llm, seen = transport_llm([choice("read_evidence", source="cv"),
                              choice(answer="supported", citations=["cv"])])
    b = budget()
    result = run_role(role(handler=lambda a, c: calls.append(a.source) or {"verified": "synthetic"}),
                      {"job": "synthetic"}, b, llm)
    assert len(built) == 1 and built[0]["invoked"]
    assert isinstance(built[0]["kwargs"]["model"], BaseChatModel)
    assert [t.name for t in built[0]["kwargs"]["tools"]] == ["read_evidence", "finish"]
    assert built[0]["kwargs"]["tools"][-1].return_direct is True
    assert built[0]["kwargs"]["subagents"] == []
    assert result.output == Answer(answer="supported", citations=("cv",))
    assert result.tool_trace == ("read_evidence", "finish") and calls == ["cv"]
    assert result.turns == len(seen) == b.snapshot().role_turns["evaluator"] == 2
    assert b.charged_tokens == 36
    assert all(r.state == "settled" for r in b.snapshot().reservations)
    assert all(url == BASE_URL + "/chat/completions" for url, _, _ in seen)
    assert '"tool_result": "read_evidence"' in seen[1][1]["messages"][-1]["content"]
    schema_text = seen[0][1]["messages"][0]["content"].split("JSON response): ", 1)[1]
    assert [entry["name"] for entry in json.loads(schema_text)] == ["read_evidence", "finish"]


def test_nested_strict_contract_tuple_fields_accept_json_without_scalar_coercion():
    class NestedTerminal(StrictFrozen):
        extracted: RequirementSet
        nested: tuple[tuple[str, ...], ...]

    payload = {"extracted": {"ad_hash": "a" * 64, "requirements": []},
               "nested": [["cv"]]}
    spec = RoleSpec(name="jd_requirements", model="claude/sonnet", system_prompt="Synthetic",
                    tools=(Tool("finish", NestedTerminal, lambda a, c: a),), terminal_tools=("finish",))
    llm, seen = transport_llm([choice(**payload)])
    result = run_role(spec, {}, budget(), llm)
    assert result.output.extracted.requirements == () and result.output.nested == (("cv",),)
    payload["nested"] = [[42]]
    invalid_llm, _ = transport_llm([choice(**payload)])
    assert_safe_failure("invalid_tool_arguments", lambda: run_role(spec, {}, budget(), invalid_llm))


@pytest.mark.parametrize("tool_name", ["execute", "read_file", "write_file", "edit_file", "delete",
                                        "ls", "glob", "grep", "task", "write_todos", "unknown"])
def test_default_and_unknown_tools_fail_before_execution(tool_name):
    llm, seen = transport_llm([choice(tool_name, private="never execute")])
    b = budget()
    assert_safe_failure("unknown_tool", lambda: run_role(role(), {}, b, llm))
    assert len(seen) == 1 and b.failed_attempts == 1
    assert b.snapshot().reservations[0].actual_usage is None


def test_framework_injected_tool_cannot_reach_model_or_execute(monkeypatch):
    original = runtime.create_deep_agent
    called = []

    @tool
    def execute(command: str) -> str:
        """A forbidden injected shell tool."""
        called.append(command)
        return "forbidden"

    class InjectTool(AgentMiddleware):
        tools = [execute]

    def build(**kwargs):
        kwargs["middleware"].append(InjectTool())
        return original(**kwargs)

    monkeypatch.setattr(runtime, "create_deep_agent", build)
    llm, seen = transport_llm([choice()])
    assert_safe_failure("invalid_registry", lambda: run_role(role(), {}, budget(), llm))
    assert not called and not seen


def test_framework_extra_model_call_is_reserved_and_respects_total_turn_limit(monkeypatch):
    original = runtime.create_deep_agent

    class ExtraModelCall(AgentMiddleware):
        def before_agent(self, state, runtime):
            self.model.invoke([HumanMessage(content="framework maintenance")])

    def build(**kwargs):
        middleware = ExtraModelCall()
        middleware.model = kwargs["model"]
        kwargs["middleware"].append(middleware)
        return original(**kwargs)

    monkeypatch.setattr(runtime, "create_deep_agent", build)
    llm, seen = transport_llm([choice(), choice()])
    b = budget()
    assert_safe_failure("turn_limit", lambda: run_role(role(), {}, b, llm, max_turns=1))
    assert len(seen) == len(b.snapshot().reservations) == 1
    assert b.charged_tokens == 18 and b.snapshot().reservations[0].state == "settled"


@pytest.mark.parametrize("payload,code", [
    ({"answer": "prose completion is insufficient"}, "invalid_tool_call"),
    ({"tool": "finish", "arguments": {"answer": 1}}, "invalid_tool_arguments"),
    ({"tool": "finish", "arguments": {"answer": "private", "extra": "private"}}, "invalid_tool_arguments"),
])
def test_nonterminal_or_wrong_schema_cannot_become_result(payload, code):
    llm, seen = transport_llm([payload])
    assert_safe_failure(code, lambda: run_role(role(), {}, budget(), llm))
    assert len(seen) == 1


def test_exhausted_turns_and_tokens_never_make_an_extra_transport():
    llm, seen = transport_llm([choice("read_evidence", source="cv")] * (MAX_ROLE_TURNS + 1))
    b = budget()
    assert_safe_failure("turn_limit", lambda: run_role(role(), {}, b, llm))
    assert len(seen) == MAX_ROLE_TURNS and b.snapshot().role_turns["evaluator"] == MAX_ROLE_TURNS
    tiny_llm, tiny_seen = transport_llm([choice()])
    assert_safe_failure("token_limit", lambda: run_role(role(), {}, budget(token_ceiling=10), tiny_llm))
    assert not tiny_seen


def test_invocation_budget_deferrals_do_not_accumulate_failed_attempts():
    from pipeline.agentic.execution import Execution, use

    llm, seen = transport_llm([choice()])
    b = budget()
    scope = Execution("synthetic-quota", token_ceiling=0)

    with use(scope):
        for _ in range(2):
            assert_safe_failure("invocation_budget_exhausted", lambda: run_role(role(), {}, b, llm))

    assert not seen
    assert scope.calls == scope.charged_tokens == 0
    assert b.snapshot().reservations == ()
    assert b.charged_tokens == b.batch.charged_tokens == b.failed_attempts == 0


def test_cancelled_invocation_does_not_accumulate_failed_attempts():
    from pipeline.agentic.execution import Execution, use

    llm, seen = transport_llm([choice()])
    b = budget()
    scope = Execution("synthetic-cancel", cancelled=lambda: True)

    with use(scope):
        assert_safe_failure("cancelled", lambda: run_role(role(), {}, b, llm))

    assert not seen
    assert scope.calls == scope.charged_tokens == 0
    assert b.snapshot().reservations == ()
    assert b.charged_tokens == b.batch.charged_tokens == b.failed_attempts == 0


def test_environment_tracing_and_inherited_callbacks_are_isolated(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    observed = []

    class InheritedCallback(BaseCallbackHandler):
        def on_chain_start(self, *args, **kwargs):
            observed.append("private data escaped")

    def forbidden(*args, **kwargs):
        observed.append("tracer created")
        raise AssertionError("external trace created")

    from langchain_core.tracers.langchain import LangChainTracer
    monkeypatch.setattr(LangChainTracer, "__init__", forbidden)
    token = var_child_runnable_config.set({"callbacks": [InheritedCallback()]})
    try:
        llm, seen = transport_llm([choice()])
        assert run_role(role(), {"private": "synthetic"}, budget(), llm).output.answer == "complete"
    finally:
        var_child_runnable_config.reset(token)
    assert not observed and len(seen) == 1


def test_global_debug_and_legacy_tracing_fail_before_private_input(monkeypatch, capsys):
    llm, seen = transport_llm([choice()])
    set_debug(True)
    try:
        assert_safe_failure("tracing_not_allowed", lambda: run_role(role(), {"private": "synthetic"}, budget(), llm))
    finally:
        set_debug(False)
    monkeypatch.setenv("LANGCHAIN_TRACING", "true")
    assert_safe_failure("tracing_not_allowed", lambda: run_role(role(), {}, budget(), llm))
    assert not seen and "synthetic" not in capsys.readouterr().out


def test_429_settles_reservation_and_opens_shared_circuit_without_retry():
    llm, seen = transport_llm([(429, {"error": {"message": "private provider details"}})])
    b = budget()
    assert_safe_failure("model_rate_limited", lambda: run_role(role(), {}, b, llm))
    assert len(seen) == 1 and b.failed_attempts == 1
    assert b.snapshot().reservations[0].state == "settled"
    assert_safe_failure("batch_paused", lambda: run_role(role(), {}, b, llm))
    assert len(seen) == 1


def test_third_failed_call_still_settles_before_failed_attempt_limit(monkeypatch):
    monkeypatch.setattr("pipeline.agentic.deepagents_runtime.time.sleep", lambda s: None)
    llm, seen = transport_llm([(500, {"error": {"message": "private"}})] * MAX_FAILED_ATTEMPTS)
    b = budget()
    for _ in range(MAX_FAILED_ATTEMPTS // 2 - 1):  # each run makes the call and one transient retry
        assert_safe_failure("model_transient", lambda: run_role(role(), {}, b, llm))
    assert_safe_failure("failed_attempt_limit", lambda: run_role(role(), {}, b, llm))
    assert len(seen) == MAX_FAILED_ATTEMPTS and all(r.state == "settled" for r in b.snapshot().reservations)
    assert_safe_failure("failed_attempt_limit", lambda: run_role(role(), {}, b, llm))
    assert len(seen) == MAX_FAILED_ATTEMPTS


def test_reservation_and_dispatch_are_durable_before_each_transport():
    events = []

    def persist(checkpoint, *, expected_revision, reservation_id, operation):
        events.append(operation)

    llm, seen = transport_llm([choice("read_evidence", source="cv"), choice()])
    transport = llm.transport

    def record_transport(*args):
        assert events[-2:] == ["reserve", "dispatched"]
        events.append("transport")
        return transport(*args)

    llm.transport = record_transport
    run_role(role(), {}, budget(persistence=persist), llm)
    assert events == ["reserve", "dispatched", "transport", "settle"] * 2


def test_late_gateway_result_is_charged_and_never_executes_tool():
    clock = [1000]
    called = []
    llm, seen = transport_llm([choice("read_evidence", source="cv")])
    transport = llm.transport

    def late_transport(*args):
        result = transport(*args)
        clock[0] = 1801
        return result

    llm.transport = late_transport
    b = budget(clock=lambda: clock[0])
    assert_safe_failure("deadline_exceeded", lambda: run_role(
        role(handler=lambda a, c: called.append(a)), {}, b, llm))
    assert len(seen) == 1 and not called
    assert b.snapshot().reservations[0].actual_usage is None
    assert b.snapshot().reservations[0].state == "settled"


@pytest.mark.parametrize("kwargs", [{"max_turns": 0}, {"max_turns": "eight"},
                                    {"max_output_tokens": True}, {"max_output_tokens": 0}])
def test_invalid_limits_fail_before_transport(kwargs):
    llm, seen = transport_llm([choice()])
    assert_safe_failure("invalid_request", lambda: run_role(role(), {}, budget(), llm, **kwargs))
    assert not seen


@pytest.mark.parametrize("name", ["candidate_evaluator", "prefill_answers"])
def test_additional_roles_roundtrip_budget_checkpoint(name):
    llm, seen = transport_llm([choice()])
    b = budget()
    run_role(role(name=name), {}, b, llm)
    checkpoint = BudgetCheckpoint.model_validate(b.snapshot().model_dump())
    restored = JobBudget.restore(checkpoint, batch=BatchBudget("b", clock=lambda: 1000), clock=lambda: 1000)
    assert restored.snapshot().role_turns[name] == 1 and restored.charged_tokens == 18


def test_upstream_overload_503_waits_and_retries_same_call(monkeypatch):
    import jobwatch.llm as L
    monkeypatch.setattr(L.time, 'sleep', lambda s: None)
    busy = (503, {'error': {'message': 'auth_unavailable: no auth available (last upstream error: server_is_overloaded)'}})
    llm, seen = transport_llm([busy, choice()]); b = budget()
    run_role(role(), {}, b, llm)
    assert len(seen) == 2 and b.failed_attempts == 0


def test_upstream_overload_never_falls_back_to_claude(monkeypatch):  # owner 2026-10-19: no Claude subscription
    import jobwatch.llm as L
    monkeypatch.setattr(L.time, 'sleep', lambda s: None)
    busy = (503, {'error': {'message': 'server_is_overloaded'}})
    models = []
    llm, seen = transport_llm([busy, busy, busy, choice()]); b = budget()
    inner = llm.transport
    llm.transport = lambda url, h, body, t: (models.append(body['model']), inner(url, h, body, t))[1]
    try:
        run_role(replace(role(), model='openai/sol'), {}, b, llm)
    except Exception:
        pass
    assert models and all(m == 'openai/sol' for m in models)


def _approved_resume(store):
    """A thread whose first run paused for approval and whose approval created a resume run (queued)."""
    from pipeline.agentic.chat import skill_version
    thread = store.create_thread(skill_version())['id']
    first = store.enqueue(thread, {'message': 'Prepare'}, 'first')
    assert store.claim_next()['id'] == first
    store.finish(first, {'interactions': [{'type': 'approval', 'binding': {'digest': 'x'}}], 'checkpoint_id': 'c1'})
    resume, _ = store.respond(store.public_run(first)['interactions'][0]['id'], {'decision': 'approve'})
    return first, resume


def test_retry_refuses_an_approval_resume_after_the_interaction_expired(tmp_path, monkeypatch):
    from pipeline.agentic.api_store import APIStore, Conflict
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    with APIStore('fixture-a') as store:
        first, resume = _approved_resume(store)
        assert store.claim_next()['id'] == resume
        store.recover()  # crash: the resume run is interrupted
        with store.conn:  # the 24h interaction window passes before anyone retries
            store.conn.execute('UPDATE api_interactions SET expires=? WHERE run_id=?', (1.0, first))
        with pytest.raises(Conflict, match='interaction_expired'):
            store.retry(resume)
        assert store.raw_run(resume)['state'] == 'interrupted'


def test_retry_of_a_fresh_approval_resume_still_works_and_clears_cancel_flag(tmp_path, monkeypatch):
    from pipeline.agentic.api_store import APIStore
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    with APIStore('fixture-a') as store:
        first, resume = _approved_resume(store)
        assert store.claim_next()['id'] == resume
        store.cancel(resume)  # cancel requested while running, then the worker dies
        store.recover()
        store.retry(resume)
        row = store.raw_run(resume)
        assert row['state'] == 'queued' and row['cancel_requested'] == 0  # an explicit retry supersedes the old cancel


def test_graceful_shutdown_leaves_inflight_run_interrupted_and_retryable(tmp_path, monkeypatch):
    import threading
    import time
    from fastapi.testclient import TestClient
    from pipeline.agentic.api import create_api, Principal
    from pipeline.agentic.api_store import APIStore
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    key = 'fixture-run-' + 'a' * 40
    started = threading.Event()

    def dispatcher(*, execution, **kw):  # a long run that polls cancellation like the real graph
        started.set()
        while True:
            execution.check()
            time.sleep(0.01)
    app = create_api(credentials={key: Principal('fixture-a')}, config={'agentic': {'enabled': False}}, dispatcher=dispatcher)
    headers = {'Authorization': 'Bearer ' + key, 'Idempotency-Key': 'shutdown'}
    with TestClient(app) as client:
        thread = client.post('/api/agent/threads', headers=headers).json()['id']
        ident = client.post('/api/agent/threads/' + thread + '/runs', json={'message': 'Long'}, headers=headers).json()['id']
        assert started.wait(10)
    # server stopped with the run in flight: that is an unclean stop (retryable), not a user cancellation
    with APIStore('fixture-a') as store:
        row = store.raw_run(ident)
        assert row['state'] == 'interrupted' and row['error'] == 'worker_interrupted', row
        store.retry(ident)
        assert store.raw_run(ident)['state'] == 'queued'


def test_user_cancel_still_finishes_cancelled(tmp_path, monkeypatch):
    import threading
    import time
    from fastapi.testclient import TestClient
    from pipeline.agentic.api import create_api, Principal
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    key = 'fixture-run-' + 'a' * 40
    started = threading.Event()

    def dispatcher(*, execution, **kw):
        started.set()
        while True:
            execution.check()
            time.sleep(0.01)
    app = create_api(credentials={key: Principal('fixture-a')}, config={'agentic': {'enabled': False}}, dispatcher=dispatcher)
    headers = {'Authorization': 'Bearer ' + key, 'Idempotency-Key': 'cancel'}
    with TestClient(app) as client:
        thread = client.post('/api/agent/threads', headers=headers).json()['id']
        ident = client.post('/api/agent/threads/' + thread + '/runs', json={'message': 'Long'}, headers=headers).json()['id']
        assert started.wait(10)
        assert client.post('/api/agent/runs/' + ident + '/cancel', headers=headers).status_code == 202
        deadline = time.monotonic() + 10
        while client.get('/api/agent/runs/' + ident, headers=headers).json()['state'] in ('queued', 'running'):
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert client.get('/api/agent/runs/' + ident, headers=headers).json()['state'] == 'cancelled'


def test_event_stream_never_ends_without_the_terminal_event(tmp_path, monkeypatch):
    """The worker may commit the final events and the terminal state between the stream's two reads."""
    from fastapi.testclient import TestClient
    from pipeline.agentic.api import create_api, Principal
    from pipeline.agentic.api_store import APIStore
    from pipeline.agentic.chat import skill_version
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    key = 'fixture-run-' + 'a' * 40
    app = create_api(credentials={key: Principal('fixture-a')}, config={'agentic': {'enabled': False}},
                     dispatcher=lambda **kw: {'answer': 'unused'})
    headers = {'Authorization': 'Bearer ' + key}
    state = {'depth': 0, 'skip': 1, 'done': False}
    original = {name: getattr(APIStore, name) for name in ('events', 'raw_run')}

    def hooked(name, finalize):
        def wrapper(self, *args, **kwargs):
            state['depth'] += 1
            try:
                out = original[name](self, *args, **kwargs)
            finally:
                state['depth'] -= 1
            if state['depth'] == 0 and not state['done']:
                if state['skip']:  # the endpoint's own existence check before the stream starts
                    state['skip'] -= 1 if name == 'raw_run' else 0
                else:
                    state['done'] = True
                    finalize()  # the worker commits between the stream's first and second read
            return out
        return wrapper
    with TestClient(app) as client:
        with APIStore('fixture-a') as store:
            thread = store.create_thread(skill_version())['id']
            ident = store.enqueue(thread, {'message': 'Stream'}, 'stream')
            assert store.claim_next()['id'] == ident

        def finalize():
            with APIStore('fixture-a') as store:
                store.finish(ident, {'answer': 'Done'})
        for name in original:
            monkeypatch.setattr(APIStore, name, hooked(name, finalize))
        text = client.get('/api/agent/runs/' + ident + '/events', headers=headers).text
    assert state['done'] and 'event: completed' in text, text


def test_api_health_remains_available_while_polling_blocks(tmp_path, monkeypatch):
    """A blocked idle-store poll must not block the HTTP event loop."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient
    from pipeline.agentic.api import create_api, Principal
    from pipeline.agentic.api_store import APIStore
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.delenv('JOBWATCH_LIBRECHAT_IDENTITY_KEY', raising=False)
    monkeypatch.delenv('JOBWATCH_NATIVE_BROWSER_ENABLED', raising=False)
    entered, release = threading.Event(), threading.Event()
    original = APIStore.claim_next
    def blocked(self):
        entered.set()
        release.wait(5)
        return original(self)
    monkeypatch.setattr(APIStore, 'claim_next', blocked)
    app = create_api(credentials={'s' * 40: Principal('fixture-poll')}, config={})
    try:
        with TestClient(app) as client:
            assert entered.wait(2)
            with ThreadPoolExecutor() as pool:
                request = pool.submit(client.get, '/health')
                try:
                    assert request.result(timeout=2).status_code == 200
                    assert not release.is_set()
                finally:
                    release.set()
    finally:
        release.set()
