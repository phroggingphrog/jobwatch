"""Synthetic provider transport through the actual autonomous Deep Agents graph."""
import copy
import json
import sqlite3

import pytest

from jobwatch.llm import LLM
from pipeline.agentic.autonomous import evaluate_autonomous
from pipeline.agentic.runtime import RuntimeErrorSafe
from test_agentic_evaluate import build_case, budget


def transport(choices):
    pending = iter(choices)
    seen = []
    def send(url, headers, body, timeout):
        seen.append(copy.deepcopy(body))
        item = next(pending)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, str):
            message = {'content': item}
        else:
            items = item if isinstance(item, list) else [item]
            message = {'content': None, 'tool_calls': [
                {'id': f'call-{len(seen)}-{i}', 'type': 'function', 'function':
                 {'name': t['tool'], 'arguments': json.dumps(t['arguments'])}} for i, t in enumerate(items)]}
        return 200, {'choices': [{'message': message}], 'usage': {'prompt_tokens': 11, 'completion_tokens': 7}}
    return LLM(transport=send, keys=['synthetic-key']), seen


def task(name):
    return {'tool': 'task', 'arguments': {'subagent_type': name, 'description': 'Run the bound stage.'}}


def run_case(tmp_path, choices=None, **case_args):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence', **case_args)
    llm, seen = transport(choices if choices is not None else [task('screening'), task('evaluation'), *roles, 'Finished.'])
    conn = sqlite3.connect(tmp_path / 'checkpoints.sqlite', check_same_thread=False)
    args = dict(conn=conn, posting={'title': 'Synthetic analyst'}, screen={'outcome': 'admit', 'rules_hash': 'test'},
                evidence_bundle=bundle, model='claude/sonnet')
    return bundle, ad, key, llm, seen, conn, args


def test_native_delegation_idempotency_and_counts(tmp_path):
    bundle, ad, key, llm, seen, conn, args = run_case(tmp_path)
    b = budget(key)
    result = evaluate_autonomous(key, ad, b, llm, **args)
    assert result.matches[0].judgment.status == 'demonstrated'
    assert len(seen) == 8
    assert all('tools' in body and 'response_format' not in body for body in seen)
    assert any(m['role'] == 'tool' and m.get('tool_call_id') for body in seen for m in body['messages'])
    assert b.charged_tokens == 8 * 18
    cached = evaluate_autonomous(key, ad, b, llm, **args)
    assert cached == result and len(seen) == 8
    counts = [json.loads(r[0]) for r in conn.execute("SELECT payload FROM autonomous_results WHERE identity LIKE '%:counts'")]
    assert counts == [{'calls': 8, 'tokens': 144, 'seconds': counts[0]['seconds']}]
    assert counts[0]['seconds'] >= 0


def test_default_off_and_configuration_validation(monkeypatch):
    from pipeline.agentic.service import _config
    from jobwatch import model_choice
    monkeypatch.setattr(model_choice, 'chosen', lambda: {})
    assert _config({}).get('autonomous_evaluation', False) is False
    assert _config({'agentic': {'autonomous_evaluation': True}})['autonomous_version']
    with pytest.raises(Exception, match='invalid_configuration'):
        _config({'agentic': {'autonomous_evaluation': 'true'}})


def test_snapshot_change_cannot_reuse_result(tmp_path):
    bundle, ad, key, llm, seen, conn, args = run_case(tmp_path)
    evaluate_autonomous(key, ad, budget(key), llm, **args)
    with pytest.raises(RuntimeErrorSafe, match='ad_hash_mismatch'):
        evaluate_autonomous(key, ad + ' changed', budget(key), llm, **args)
    other = key.model_copy(update={'config_hash': '3' * 64})
    # A different config starts a new graph; this exhausted transport cannot supply it.
    with pytest.raises(RuntimeErrorSafe, match='model_unavailable'):
        evaluate_autonomous(other, ad, budget(other), llm, **args)
    assert len(seen) == 9


def test_native_transport_keeps_parallel_calls_and_never_parses_json_fallback():
    llm, seen = transport([[task('screening'), task('evaluation')]])
    reply = llm.chat_once('claude/sonnet', [{'role': 'user', 'content': 'test'}],
        tools=[{'type': 'function', 'function': {'name': 'task', 'parameters': {}}}], native_response=True)
    assert len(reply.data['tool_calls']) == 2
    assert 'response_format' not in seen[0]


def test_partial_resume_reuses_extraction_and_rebuilds_evidence_access(tmp_path):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    llm, seen = transport([task('screening'), task('evaluation'), *roles[:3], OSError('synthetic outage')])
    path = tmp_path / 'checkpoints.sqlite'
    args = dict(posting={'title': 'Synthetic analyst'}, screen={'outcome': 'admit'}, evidence_bundle=bundle,
                model='claude/sonnet')
    b = budget(key)
    with sqlite3.connect(path, check_same_thread=False) as conn:
        with pytest.raises(RuntimeErrorSafe, match='model_unavailable'):
            evaluate_autonomous(key, ad, b, llm, conn=conn, **args)
    from pipeline.agentic.runtime import JobBudget, BatchBudget
    b = JobBudget.restore(b.snapshot(), batch=BatchBudget('synthetic', token_ceiling=2_000_000))
    resumed, resumed_seen = transport([*roles[3:], 'Finished.'])
    with sqlite3.connect(path, check_same_thread=False) as conn:
        result = evaluate_autonomous(key, ad, b, resumed, conn=conn, **args)
    assert result.matches[0].judgment.status == 'demonstrated'
    assert len(resumed_seen) == 3
    assert all('complete_requirements' not in {t['function']['name'] for t in body['tools']} for body in resumed_seen)


def test_screening_cannot_be_bypassed(tmp_path):
    bundle, ad, key, llm, seen, conn, args = run_case(tmp_path, choices=[task('evaluation')])
    with pytest.raises(RuntimeErrorSafe, match='screening_required'):
        evaluate_autonomous(key, ad, budget(key), llm, **args)
    assert len(seen) == 1


def test_skip_does_not_dispatch_evaluation_roles(tmp_path):
    bundle, ad, key, llm, seen, conn, args = run_case(tmp_path, choices=[task('screening'), task('evaluation')])
    args['screen'] = {'outcome': 'skip'}
    with pytest.raises(RuntimeErrorSafe, match='prescreen_skip'):
        evaluate_autonomous(key, ad, budget(key), llm, **args)
    assert len(seen) == 2


def test_canonical_gate_holds_missing_evidence_despite_high_score(tmp_path):
    from jobwatch.candidate.policy import default_policy
    from pipeline.agentic.gate import decide
    bundle, ad, key, llm, seen, conn, args = run_case(tmp_path, match='missing', score=5)
    result = evaluate_autonomous(key, ad, budget(key), llm, **args)
    gate = decide(result, ad_text=ad, title='Synthetic analyst', policy=default_policy(),
                  captured_complete=True, expected_run_key=key, evidence_bundle=bundle)
    assert gate.route == 'hold' and gate.reason == 'insufficient_evidence'


def test_person_and_rules_changes_start_separate_checkpoints(tmp_path):
    from jobwatch import users
    bundle, ad, key, llm, seen, conn, args = run_case(tmp_path)
    evaluate_autonomous(key, ad, budget(key), llm, **args)
    for person, screen in [('synthetic-other', args['screen']), (users.current(), {'outcome': 'admit', 'rules_hash': 'new'})]:
        args['screen'] = screen
        with users.use(person), pytest.raises(RuntimeErrorSafe, match='model_unavailable'):
            evaluate_autonomous(key, ad, budget(key), llm, **args)
    assert conn.execute('SELECT COUNT(DISTINCT thread) FROM chat_checkpoints WHERE ns=""').fetchone()[0] >= 3


def test_native_json_text_cannot_finish_a_role_or_trigger_protocol_fallback(tmp_path):
    bundle, ad, key, llm, seen, conn, args = run_case(tmp_path, choices=[task('screening'), task('evaluation'),
        json.dumps({'tool': 'complete_requirements', 'arguments': {}})])
    with pytest.raises(RuntimeErrorSafe, match='missing_terminal'):
        evaluate_autonomous(key, ad, budget(key), llm, **args)
    assert len(seen) == 3
    assert all('response_format' not in body for body in seen)


from test_agentic_service import world, SyntheticGateway


def test_service_switch_dispatches_adapter_and_saves_count_only_artifact(world, monkeypatch):
    from pipeline.agentic.service import agentic_batch_run
    from pipeline.agentic.evaluator import evaluate_job
    conn, config, bundle, add = world
    config.settings['pipeline']['agentic']['autonomous_evaluation'] = True
    add(42)
    calls = []
    def selected(key, ad, b, llm, *, source_conn, posting, **kwargs):
        assert source_conn is conn and key.posting_id == 42
        calls.append(key)
        return evaluate_job(key, ad, b, llm, **kwargs)
    monkeypatch.setattr('pipeline.agentic.autonomous.evaluate_posting', selected)
    llm = LLM(transport=SyntheticGateway(bundle), keys=['synthetic-key'])
    summary = agentic_batch_run([42], config, conn, evidence_bundle=bundle, llm=llm, operation='evaluate')
    assert len(calls) == 1 and summary['processed'] == 1, (summary, [tuple(r) for r in conn.execute('SELECT reason FROM agentic_runs')], llm.calls)
    row = conn.execute("SELECT path FROM agentic_artifacts WHERE kind='evaluation_counts'").fetchone()
    from pathlib import Path
    counts = json.loads(Path(row[0]).read_text())
    assert set(counts) == {'mode', 'calls', 'charged_tokens', 'seconds'}
    assert counts['mode'] == 'autonomous_native' and counts['calls'] > 0
