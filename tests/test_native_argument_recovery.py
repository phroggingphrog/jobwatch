"""Malformed native tool JSON gets feedback without executing a guessed repair."""
import copy
import json
import sqlite3

import pytest

from pipeline.agentic.autonomous import evaluate_autonomous
from pipeline.agentic.runtime import BatchBudget, JobBudget, RuntimeErrorSafe
from test_agentic_evaluate import build_case, budget
from test_autonomous_evaluation import native_choices, transport


def malformed_transport(choices, malformed_turns):
    llm, seen = transport(choices, reasoning=True)
    original = llm.transport
    def send(*args, **kwargs):
        status, payload = original(*args, **kwargs)
        if len(seen) in malformed_turns:
            payload['choices'][0]['message']['tool_calls'][0]['function']['arguments'] += '}'
        return status, payload
    llm.transport = send
    return llm, seen


def test_missing_fields_then_extra_brace_receives_correction_and_completes(tmp_path, monkeypatch):
    monkeypatch.setattr('pipeline.agentic.evaluator.evaluate_job',
                        lambda *a, **kw: pytest.fail('legacy fallback reached'))
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    choices = native_choices(roles)
    incomplete = copy.deepcopy(choices[0])
    incomplete['arguments'] = {'requirements': incomplete['arguments']['requirements']}
    llm, seen = malformed_transport([incomplete, choices[0], *choices], {2})
    with sqlite3.connect(':memory:', check_same_thread=False) as conn:
        args = dict(conn=conn, posting={}, screen={'outcome': 'admit'}, evidence_bundle=bundle, model='deepseek-flash')
        result = evaluate_autonomous(key, ad, budget(key), llm, **args)
        assert result.matches[0].judgment.status == 'demonstrated'
        outputs = [json.loads(m['content']) for m in seen[2]['messages'] if m['role'] == 'tool']
        assert [m['error'] for m in outputs] == ['missing_required_fields', 'invalid_tool_arguments_json']
        assert outputs[-1]['fields'] == ['arguments']
        assistant = [m for m in seen[2]['messages'] if m['role'] == 'assistant']
        assert assistant[-1]['tool_calls'][0]['function']['arguments'] == json.dumps(choices[0]['arguments']) + '}'
        assert assistant[-1]['reasoning_content'] == 'synthetic-reasoning-2'
        assert all('jobwatch' not in str(m.keys()) for m in seen[2]['messages'])
        assert all('response_format' not in request for request in seen)
        assert evaluate_autonomous(key, ad, budget(key), llm, **args) == result
        assert len(seen) == 5


@pytest.mark.parametrize('initial_missing', [False, True])
def test_malformed_feedback_replays_after_checkpoint_loss_without_reset_or_repurchase(tmp_path, initial_missing):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    choices = native_choices(roles)
    incomplete = copy.deepcopy(choices[0])
    incomplete['arguments'] = {'requirements': incomplete['arguments']['requirements']}
    initial = [incomplete, choices[0]] if initial_missing else choices[:2]
    llm, seen = malformed_transport([*initial, OSError('synthetic outage')], {2})
    args = dict(posting={}, screen={'outcome': 'admit'}, evidence_bundle=bundle, model='deepseek-flash')
    b = budget(key)
    path = tmp_path / 'checkpoints.sqlite'
    with sqlite3.connect(path, check_same_thread=False) as conn:
        with pytest.raises(RuntimeErrorSafe, match='model_unavailable'):
            evaluate_autonomous(key, ad, b, llm, conn=conn, **args)
        conn.execute('DELETE FROM chat_writes')
        conn.execute('DELETE FROM chat_checkpoints')
        conn.commit()
    restored = JobBudget.restore(b.snapshot(), batch=BatchBudget('synthetic', token_ceiling=2_000_000))
    resumed, requests = transport(choices if initial_missing else choices[1:], reasoning=True)
    with sqlite3.connect(path, check_same_thread=False) as conn:
        result = evaluate_autonomous(key, ad, restored, resumed, conn=conn, **args)
        assert result.matches
        assert requests[0]['messages'] == seen[-1]['messages']
        assert len(requests) == 2 + initial_missing and len(seen) == 3
        assert evaluate_autonomous(key, ad, restored, resumed, conn=conn, **args) == result
        assert len(requests) == 2 + initial_missing


def test_repeated_malformed_arguments_exhaust_persisted_boundary(tmp_path):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    choice = native_choices(roles)[0]
    llm, seen = malformed_transport([choice, choice], {1, 2})
    with sqlite3.connect(':memory:', check_same_thread=False) as conn:
        for _ in range(2):
            with pytest.raises(RuntimeErrorSafe, match='invalid_tool_arguments_json'):
                evaluate_autonomous(key, ad, budget(key), llm, conn=conn, posting={},
                    screen={'outcome': 'admit'}, evidence_bundle=bundle, model='deepseek-flash')
    assert len(seen) == 2


def test_saved_rejection_precedes_restored_state_on_journal_replay(tmp_path):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    choices = native_choices(roles)
    llm, seen = transport([choices[1], choices[0], choices[1], OSError('synthetic outage')], reasoning=True)
    args = dict(posting={}, screen={'outcome': 'admit'}, evidence_bundle=bundle, model='deepseek-flash')
    path = tmp_path / 'checkpoint.sqlite'
    b = budget(key)
    with sqlite3.connect(path, check_same_thread=False) as conn:
        with pytest.raises(RuntimeErrorSafe, match='model_unavailable'):
            evaluate_autonomous(key, ad, b, llm, conn=conn, **args)
        conn.execute('DELETE FROM chat_writes')
        conn.execute('DELETE FROM chat_checkpoints')
        conn.commit()
    restored = JobBudget.restore(b.snapshot(), batch=BatchBudget('synthetic', token_ceiling=2_000_000))
    resumed, requests = transport(choices[-1:], reasoning=True)
    with sqlite3.connect(path, check_same_thread=False) as conn:
        result = evaluate_autonomous(key, ad, restored, resumed, conn=conn, **args)
        assert result.matches and len(requests) == 1
        assert requests[0]['messages'] == seen[-1]['messages']


def test_parallel_valid_skill_and_malformed_evidence_do_not_grant_evidence_access(tmp_path):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    choices = native_choices(roles)
    skill = {'tool': 'read_file', 'arguments': {'file_path': '/skills/autonomous-evaluation/SKILL.md'}}
    llm, seen = malformed_transport([choices[0], [choices[1], skill], choices[-1], *choices[1:]], {2})
    with sqlite3.connect(':memory:', check_same_thread=False) as conn:
        result = evaluate_autonomous(key, ad, budget(key), llm, conn=conn, posting={},
            screen={'outcome': 'admit'}, evidence_bundle=bundle, model='deepseek-flash')
    assert result.matches and len(seen) == 5
    outputs = [json.loads(m['content']) for m in seen[3]['messages'] if m['role'] == 'tool']
    assert any(m.get('error') == 'unretrieved_evidence' for m in outputs)
    assert any(m.get('path') == '/skills/autonomous-evaluation/SKILL.md' for m in outputs)
    assert not any(m.get('items') for m in outputs)


@pytest.mark.parametrize('change', ['unknown_tool', 'missing_id', 'non_object_args'])
def test_unidentifiable_or_nonobject_calls_still_fail_closed(tmp_path, change):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    llm, seen = transport([native_choices(roles)[0]], reasoning=True)
    original = llm.transport
    def send(*args, **kwargs):
        status, payload = original(*args, **kwargs)
        call = payload['choices'][0]['message']['tool_calls'][0]
        if change == 'unknown_tool': call['function']['name'] = 'confirmed_submit'
        if change == 'missing_id': call['id'] = ''
        if change == 'non_object_args': call['function']['arguments'] = '[]'
        return status, payload
    llm.transport = send
    with sqlite3.connect(':memory:', check_same_thread=False) as conn:
        with pytest.raises(RuntimeErrorSafe, match='invalid_native_response'):
            evaluate_autonomous(key, ad, budget(key), llm, conn=conn, posting={},
                screen={'outcome': 'admit'}, evidence_bundle=bundle, model='deepseek-flash')
        assert not conn.execute("SELECT 1 FROM autonomous_results WHERE identity LIKE '%:requirements'").fetchone()
    assert len(seen) == 1
