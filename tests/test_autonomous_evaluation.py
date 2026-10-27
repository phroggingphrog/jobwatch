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


def native_choices(roles):
    return [roles[1], roles[2], {'tool': 'complete_evaluation', 'arguments': copy.deepcopy(roles[-1]['arguments'])}]


def run_case(tmp_path, choices=None, **case_args):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence', **case_args)
    llm, seen = transport(choices if choices is not None else native_choices(roles))
    conn = sqlite3.connect(tmp_path / 'checkpoints.sqlite', check_same_thread=False)
    args = dict(conn=conn, posting={'title': 'Synthetic analyst'}, screen={'outcome': 'admit', 'rules_hash': 'test'},
                evidence_bundle=bundle, model='claude/sonnet')
    return bundle, ad, key, llm, seen, conn, args


def test_native_assessment_three_calls_skills_and_idempotency(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('old evaluator must never run')
    monkeypatch.setattr('pipeline.agentic.evaluator.evaluate_job', forbidden)
    bundle, ad, key, llm, seen, conn, args = run_case(tmp_path)
    b = budget(key)
    result = evaluate_autonomous(key, ad, b, llm, **args)
    assert result.matches[0].judgment.status == 'demonstrated'
    assert len(seen) == 3 and b.charged_tokens == 54
    assert all('tools' in body and 'response_format' not in body for body in seen)
    names = {t['function']['name'] for t in seen[0]['tools']}
    assert 'complete_evaluation' in names
    assert not names & {'task', 'complete_requirement_matches', 'complete_job_assessment'}
    first = json.dumps(seen[0]['messages'])
    assert 'autonomous-screening' in first and 'autonomous-evaluation' in first
    assert 'Synthetic candidate' not in first and bundle.bundle_hash not in first
    assert any(m['role'] == 'tool' and m.get('tool_call_id') for body in seen for m in body['messages'])
    assert evaluate_autonomous(key, ad, b, llm, **args) == result and len(seen) == 3
    counts = json.loads(conn.execute("SELECT payload FROM autonomous_results WHERE identity LIKE '%:counts'").fetchone()[0])
    assert counts['calls'] == 3 and counts['tokens'] == 54
    assert counts['prompt_tokens'] == 33 and counts['completion_tokens'] == 21
    assert counts['purposes'] == {'requirements': 1, 'evidence_matching': 1, 'evaluation': 1}
    assert len(counts['details']) == 3 and counts['seconds'] >= 0


@pytest.mark.parametrize('change', ['ad', 'person', 'config', 'screen', 'model', 'skills', 'insights', 'commute'])
def test_changed_inputs_cannot_reuse_result(tmp_path, monkeypatch, change):
    from jobwatch import users
    from contextlib import nullcontext
    bundle, ad, key, llm, seen, conn, args = run_case(tmp_path)
    evaluate_autonomous(key, ad, budget(key), llm, **args)
    if change == 'ad':
        with pytest.raises(RuntimeErrorSafe, match='ad_hash_mismatch'):
            evaluate_autonomous(key, ad + ' changed', budget(key), llm, **args)
        assert len(seen) == 3
        return
    if change == 'config': key = key.model_copy(update={'config_hash': '3' * 64})
    if change == 'screen': args['screen'] = {'outcome': 'flag', 'rules_hash': 'new'}
    if change == 'model': args['model'] = 'openai/sol'
    if change == 'skills': monkeypatch.setattr('pipeline.agentic.autonomous.version', lambda: 'changed')
    if change == 'insights': args['model_insights'] = {'new': True}
    if change == 'commute': args['commute_km'] = 21
    with users.use('synthetic-other') if change == 'person' else nullcontext():
        with pytest.raises(RuntimeErrorSafe, match='model_unavailable'):
            evaluate_autonomous(key, ad, budget(key), llm, **args)
    assert len(seen) == 4


def test_partial_resume_rebuilds_access_without_completed_paid_replay(tmp_path):
    from pipeline.agentic.runtime import JobBudget, BatchBudget
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    choices = native_choices(roles)
    llm, seen = transport([*choices[:2], OSError('synthetic outage')])
    path = tmp_path / 'checkpoints.sqlite'
    args = dict(posting={'title': 'Synthetic analyst'}, screen={'outcome': 'admit'}, evidence_bundle=bundle,
                model='claude/sonnet')
    b = budget(key)
    with sqlite3.connect(path, check_same_thread=False) as conn:
        with pytest.raises(RuntimeErrorSafe, match='model_unavailable'):
            evaluate_autonomous(key, ad, b, llm, conn=conn, **args)
    b = JobBudget.restore(b.snapshot(), batch=BatchBudget('synthetic', token_ceiling=2_000_000))
    resumed, resumed_seen = transport(choices[2:])
    with sqlite3.connect(path, check_same_thread=False) as conn:
        result = evaluate_autonomous(key, ad, b, resumed, conn=conn, **args)
    assert result.matches[0].judgment.status == 'demonstrated'
    assert len(resumed_seen) == 1 and len(seen) == 3


def test_response_journal_survives_failure_before_tool_checkpoint(tmp_path, monkeypatch):
    from pipeline.agentic.matching import RequirementEvidenceSearch
    bundle, ad, key, llm, seen, conn, args = run_case(tmp_path)
    original = RequirementEvidenceSearch.read
    def fail(*args, **kwargs):
        raise RuntimeError('synthetic checkpoint interruption')
    monkeypatch.setattr(RequirementEvidenceSearch, 'read', fail)
    with pytest.raises(RuntimeError, match='synthetic checkpoint interruption'):
        evaluate_autonomous(key, ad, budget(key), llm, **args)
    assert len(seen) == 2
    conn.execute('DELETE FROM chat_writes')
    conn.execute('DELETE FROM chat_checkpoints')
    conn.commit()
    monkeypatch.setattr(RequirementEvidenceSearch, 'read', original)
    result = evaluate_autonomous(key, ad, budget(key), llm, **args)
    assert result.matches[0].match == 'strong' and len(seen) == 3


def test_skip_does_not_dispatch_any_paid_model(tmp_path):
    bundle, ad, key, llm, seen, conn, args = run_case(tmp_path, choices=[])
    args['screen'] = {'outcome': 'skip'}
    with pytest.raises(RuntimeErrorSafe, match='prescreen_skip'):
        evaluate_autonomous(key, ad, budget(key), llm, **args)
    assert not seen


@pytest.mark.parametrize('change,error', [
    ('no_retrieval', 'unretrieved_evidence'), ('candidate_citation', 'invalid_citation'),
    ('coverage', 'invalid_evaluation'), ('requirements_hash', 'requirements_changed'),
    ('judgment', 'invalid_evaluation'), ('not_applicable', 'contradictory_match'),
    ('partial_no_citation', 'invalid_model_payload'), ('fabricated_contradiction', 'invalid_citation')])
def test_invalid_matching_fails_closed(tmp_path, change, error):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    choices = native_choices(roles)
    output = choices[-1]['arguments']
    match = output['matches'][0]
    if change == 'no_retrieval': choices.pop(1)
    if change == 'candidate_citation': match['evidence'][0]['source_id'] = 'career_ops_profile.md'
    if change == 'coverage': output['matches'] = []
    if change == 'requirements_hash': output['requirements_hash'] = 'a' * 64
    if change == 'judgment': match.pop('judgment')
    if change == 'not_applicable':
        match.update(match='not_applicable', evidence=[])
        match['judgment']['status'] = 'not_applicable'
    if change == 'partial_no_citation':
        match.update(match='partial', evidence=[])
        match['judgment'].update(status='partial', open_question='What evidence?')
    if change == 'fabricated_contradiction':
        citation = copy.deepcopy(match['evidence'][0]); citation['quote'] = 'Invented contradiction'
        match.update(match='missing', evidence=[], risk='Gap', mitigation='Ask owner')
        match['judgment'].update(status='contradicted', contradiction_evidence=[citation], open_question='Which proof?')
    llm, seen = transport(choices)
    with sqlite3.connect(':memory:', check_same_thread=False) as conn:
        with pytest.raises(Exception, match=error):
            evaluate_autonomous(key, ad, budget(key), llm, conn=conn, posting={}, screen={'outcome': 'admit'},
                                evidence_bundle=bundle, model='claude/sonnet')


def test_canonical_gate_holds_missing_evidence_despite_high_score(tmp_path):
    from jobwatch.candidate.policy import default_policy
    from pipeline.agentic.gate import decide
    bundle, ad, key, llm, seen, conn, args = run_case(tmp_path, match='missing', score=5)
    result = evaluate_autonomous(key, ad, budget(key), llm, **args)
    gate = decide(result, ad_text=ad, title='Synthetic analyst', policy=default_policy(),
                  captured_complete=True, expected_run_key=key, evidence_bundle=bundle)
    assert gate.route == 'hold' and gate.reason == 'insufficient_evidence'


def test_six_call_limit_survives_resumes(tmp_path):
    bundle, ad, key, llm, seen, conn, args = run_case(tmp_path, choices=[
        {'tool': 'read_full_ad', 'arguments': {}} for _ in range(8)])
    for _ in range(2):
        with pytest.raises(RuntimeErrorSafe, match='assessment_call_limit'):
            evaluate_autonomous(key, ad, budget(key), llm, **args)
    assert len(seen) == 6


def test_native_json_text_cannot_trigger_protocol_fallback(tmp_path):
    bundle, ad, key, llm, seen, conn, args = run_case(tmp_path, choices=[json.dumps({'tool': 'complete_evaluation'})])
    with pytest.raises(RuntimeErrorSafe, match='missing_evaluation'):
        evaluate_autonomous(key, ad, budget(key), llm, **args)
    assert len(seen) == 1 and 'response_format' not in seen[0]


def test_default_off_and_configuration_validation(monkeypatch):
    from pipeline.agentic.service import _config
    from jobwatch import model_choice
    monkeypatch.setattr(model_choice, 'chosen', lambda: {})
    assert _config({}).get('autonomous_evaluation', False) is False
    assert _config({'agentic': {'autonomous_evaluation': True}})['autonomous_version']
    with pytest.raises(Exception, match='invalid_configuration'):
        _config({'agentic': {'autonomous_evaluation': 'true'}})


def test_batch_retrieval_and_uncertainties_survive_cached_read(tmp_path):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    choices = native_choices(roles)
    choices[0]['arguments']['uncertainties'] = ['Working days unknown']
    choices[1] = {'tool': 'search_candidate_evidence_batch', 'arguments': {'queries': [{'requirement_id': 'r1'}]}}
    llm, seen = transport(choices)
    with sqlite3.connect(':memory:', check_same_thread=False) as conn:
        args = dict(conn=conn, posting={}, screen={'outcome': 'flag'}, evidence_bundle=bundle, model='claude/sonnet')
        result = evaluate_autonomous(key, ad, budget(key), llm, **args)
        assert 'Working days unknown' in result.report['E']
        assert result.matching_diagnostics['searches'][0]['requirement_id'] == 'r1'
        assert evaluate_autonomous(key, ad, budget(key), llm, **args) == result and len(seen) == 3


def test_numeric_token_details_omit_arbitrary_provider_metadata():
    from pipeline.agentic.autonomous import _token_metrics
    assert _token_metrics({'prompt_tokens': 9, 'completion_tokens': 4,
        'prompt_tokens_details': {'cached_tokens': 3, 'candidate': 'private'},
        'completion_tokens_details': {'reasoning_tokens': 2, 'audio_tokens': -1},
        'text': 'private'}) == {'prompt_tokens': 9, 'completion_tokens': 4,
        'prompt_tokens_details': {'cached_tokens': 3}, 'completion_tokens_details': {'reasoning_tokens': 2}}


def test_evidence_and_candidate_identity_mismatch_refused_before_paid_calls(tmp_path):
    bundle, ad, key, llm, seen, conn, args = run_case(tmp_path)
    for field in ('evidence_hash', 'candidate_hash'):
        changed = key.model_copy(update={field: 'a' * 64})
        with pytest.raises(Exception, match=field + '_mismatch'):
            evaluate_autonomous(changed, ad, budget(changed), llm, **args)
    assert not seen
