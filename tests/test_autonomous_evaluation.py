"""Synthetic provider transport through the actual autonomous Deep Agents graph."""
import copy
import json
import sqlite3

import pytest

from jobwatch.util.llm import LLM
from pipeline.agentic.autonomous import evaluate_autonomous
from pipeline.agentic.runtime import RuntimeErrorSafe
from test_agentic_evaluate import build_case, budget


def transport(choices, *, include_usage=True, reasoning=False):
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
        if reasoning:
            message['reasoning_content'] = f'synthetic-reasoning-{len(seen)}'
        response = {'choices': [{'message': message}]}
        if include_usage:
            response['usage'] = {'prompt_tokens': 11, 'completion_tokens': 7}
        return 200, response
    return LLM(transport=send, keys=['synthetic-key']), seen


def combined_native_choices(roles):
    """Use the combined extraction protocol for tests of native tool recovery.

    Keep this three-reply script independent of the split extraction protocol:
    callers rely on extraction, evidence read, and completion in that order.
    """
    return [roles[1], roles[2],
            {'tool': 'complete_evaluation', 'arguments': copy.deepcopy(roles[-1]['arguments'])}]


def native_choices(roles):
    ext = roles[1]['arguments']
    facts = {key: ext[key] for key in ('facts', 'location_fit', 'location_evidence', 'legitimacy', 'uncertainties')
             if key in ext}
    return [{'tool': 'complete_requirement_set', 'arguments': ext['requirements']},
            {'tool': 'complete_ad_facts', 'arguments': facts},
            roles[2],
            {'tool': 'complete_evaluation', 'arguments': copy.deepcopy(roles[-1]['arguments'])}]


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
    assert len(seen) == 4 and b.charged_tokens == 72
    assert all('tools' in body and 'response_format' not in body for body in seen)
    names = {t['function']['name'] for t in seen[0]['tools']}
    assert 'complete_evaluation' in names
    assert not names & {'task', 'complete_requirement_matches', 'complete_job_assessment',
                        'ls', 'glob', 'grep', 'execute', 'write_file', 'edit_file'}
    first = json.dumps(seen[0]['messages'])
    assert 'autonomous-screening' in first and 'autonomous-evaluation' in first
    assert 'Synthetic candidate' not in first and bundle.bundle_hash not in first
    assert any(m['role'] == 'tool' and m.get('tool_call_id') for body in seen for m in body['messages'])
    assert evaluate_autonomous(key, ad, b, llm, **args) == result and len(seen) == 4
    counts = json.loads(conn.execute("SELECT payload FROM autonomous_results WHERE identity LIKE '%:counts'").fetchone()[0])
    assert counts['calls'] == 4 and counts['tokens'] == 72
    assert counts['charged_tokens'] == 72 and counts['unknown_usage_calls'] == 0
    assert counts['prompt_tokens'] == 44 and counts['completion_tokens'] == 28
    assert counts['purposes'] == {'requirements': 2, 'evidence_matching': 1, 'evaluation': 1}
    assert len(counts['details']) == 4 and counts['seconds'] >= 0


def test_unknown_native_usage_remains_conservatively_charged(tmp_path):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    llm, seen = transport(native_choices(roles), include_usage=False)
    b = budget(key)
    with sqlite3.connect(':memory:', check_same_thread=False) as conn:
        evaluate_autonomous(key, ad, b, llm, conn=conn, posting={}, screen={'outcome': 'admit'},
                            evidence_bundle=bundle, model='claude/sonnet')
        value = json.loads(conn.execute("SELECT payload FROM autonomous_results WHERE identity LIKE '%:counts'").fetchone()[0])
    assert len(seen) == 4 and value['unknown_usage_calls'] == 4
    assert value['tokens'] == 0 and value['charged_tokens'] == b.charged_tokens > 0
    assert all(d['usage_known'] is False for d in value['details'])

def test_default_off_and_configuration_validation(monkeypatch):
    from pipeline.agentic.service import _config
    from jobwatch.util import model_choice as model_choice
    monkeypatch.setattr(model_choice, 'chosen', lambda: {})
    assert _config({}).get('autonomous_evaluation', False) is False
    assert _config({'agentic': {'autonomous_evaluation': True}})['autonomous_version']
    with pytest.raises(Exception, match='invalid_configuration'):
        _config({'agentic': {'autonomous_evaluation': 'true'}})


def test_native_reasoning_is_preserved_through_tool_turns_and_checkpoint_resume(tmp_path):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    llm, seen = transport(native_choices(roles), reasoning=True)
    with sqlite3.connect(':memory:', check_same_thread=False) as conn:
        args = dict(conn=conn, posting={}, screen={'outcome': 'admit'}, evidence_bundle=bundle, model='claude/sonnet')
        result = evaluate_autonomous(key, ad, budget(key), llm, **args)
        assert result.matches
        for number, request in enumerate(seen[1:], start=1):
            assistant = [m for m in request['messages'] if m['role'] == 'assistant']
            assert [m['reasoning_content'] for m in assistant] == [f'synthetic-reasoning-{i}' for i in range(1, number+1)]
        assert evaluate_autonomous(key, ad, budget(key), llm, **args) == result
        assert len(seen) == 4


def test_reasoning_journal_replay_after_tool_interruption_keeps_paid_responses(tmp_path, monkeypatch):
    from pipeline.agentic.matching import RequirementEvidenceSearch
    from pipeline.agentic.runtime import BatchBudget, JobBudget

    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    llm, seen = transport(native_choices(roles), reasoning=True)
    path = tmp_path / 'checkpoints.sqlite'
    args = dict(posting={}, screen={'outcome': 'admit'}, evidence_bundle=bundle, model='claude/sonnet')
    original = RequirementEvidenceSearch.read

    def interrupted(*args, **kwargs):
        raise RuntimeError('synthetic failure after journal before tool checkpoint')

    b = budget(key)
    monkeypatch.setattr(RequirementEvidenceSearch, 'read', interrupted)
    with sqlite3.connect(path, check_same_thread=False) as conn:
        with pytest.raises(RuntimeError, match='after journal before tool checkpoint'):
            evaluate_autonomous(key, ad, b, llm, conn=conn, **args)
        assert len(seen) == 3
        assert conn.execute("SELECT count(*) FROM autonomous_results WHERE identity LIKE '%:response:%'").fetchone()[0] == 3
        conn.execute('DELETE FROM chat_writes')
        conn.execute('DELETE FROM chat_checkpoints')
        conn.commit()

    monkeypatch.setattr(RequirementEvidenceSearch, 'read', original)
    resumed_budget = JobBudget.restore(b.snapshot(), batch=BatchBudget('synthetic', token_ceiling=2_000_000))
    with sqlite3.connect(path, check_same_thread=False) as conn:
        result = evaluate_autonomous(key, ad, resumed_budget, llm, conn=conn, **args)
        assert result.matches[0].judgment.status == 'demonstrated'
        assert len(seen) == 4
        assistant = [m for m in seen[-1]['messages'] if m['role'] == 'assistant']
        assert [m['reasoning_content'] for m in assistant] == ['synthetic-reasoning-1', 'synthetic-reasoning-2', 'synthetic-reasoning-3']
        assert [m['tool_calls'][0]['id'] for m in assistant] == ['call-1-0', 'call-2-0', 'call-3-0']
        counts = json.loads(conn.execute("SELECT payload FROM autonomous_results WHERE identity LIKE '%:counts'").fetchone()[0])
        assert counts['calls'] == 4 and counts['tokens'] == 72
        assert evaluate_autonomous(key, ad, resumed_budget, llm, conn=conn, **args) == result
        assert len(seen) == 4


def test_reasoning_checkpoint_restart_after_provider_interruption_preserves_wire_history(tmp_path):
    from pipeline.agentic.runtime import BatchBudget, JobBudget

    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    choices = native_choices(roles)
    llm, seen = transport([*choices[:2], OSError('synthetic provider interruption')], reasoning=True)
    path = tmp_path / 'checkpoints.sqlite'
    args = dict(posting={}, screen={'outcome': 'admit'}, evidence_bundle=bundle, model='claude/sonnet')
    b = budget(key)
    with sqlite3.connect(path, check_same_thread=False) as conn:
        with pytest.raises(RuntimeErrorSafe, match='model_unavailable'):
            evaluate_autonomous(key, ad, b, llm, conn=conn, **args)
        assert len(seen) == 3
        assert conn.execute('SELECT count(*) FROM chat_checkpoints').fetchone()[0] > 0

    resumed_budget = JobBudget.restore(b.snapshot(), batch=BatchBudget('synthetic', token_ceiling=2_000_000))
    resumed_llm, resumed_seen = transport(choices[2:], reasoning=True)
    with sqlite3.connect(path, check_same_thread=False) as conn:
        result = evaluate_autonomous(key, ad, resumed_budget, resumed_llm, conn=conn, **args)
        assert result.matches[0].judgment.status == 'demonstrated'
        assert len(resumed_seen) == 2
        assistant = [m for m in resumed_seen[0]['messages'] if m['role'] == 'assistant']
        assert [m['reasoning_content'] for m in assistant] == ['synthetic-reasoning-1', 'synthetic-reasoning-2']
        assert [m['tool_calls'][0]['id'] for m in assistant] == ['call-1-0', 'call-2-0']
        assert resumed_seen[0]['messages'] == seen[-1]['messages']
        counts = json.loads(conn.execute("SELECT payload FROM autonomous_results WHERE identity LIKE '%:counts'").fetchone()[0])
        assert counts['calls'] == 5 and counts['tokens'] == 72
        assert counts['unknown_usage_calls'] == 1
        assert evaluate_autonomous(key, ad, resumed_budget, resumed_llm, conn=conn, **args) == result
        assert len(resumed_seen) == 2


@pytest.mark.parametrize('change', ['ad', 'person', 'config', 'screen', 'model', 'skills', 'insights', 'commute'])
def test_changed_inputs_cannot_reuse_result(tmp_path, monkeypatch, change):
    from jobwatch import users
    from contextlib import nullcontext
    bundle, ad, key, llm, seen, conn, args = run_case(tmp_path)
    evaluate_autonomous(key, ad, budget(key), llm, **args)
    if change == 'ad':
        with pytest.raises(RuntimeErrorSafe, match='ad_hash_mismatch'):
            evaluate_autonomous(key, ad + ' changed', budget(key), llm, **args)
        assert len(seen) == 4
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
    assert len(seen) == 5


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
    assert len(resumed_seen) == 2 and len(seen) == 3


def test_response_journal_survives_failure_before_tool_checkpoint(tmp_path, monkeypatch):
    from pipeline.agentic.matching import RequirementEvidenceSearch
    bundle, ad, key, llm, seen, conn, args = run_case(tmp_path)
    original = RequirementEvidenceSearch.read
    def fail(*args, **kwargs):
        raise RuntimeError('synthetic checkpoint interruption')
    monkeypatch.setattr(RequirementEvidenceSearch, 'read', fail)
    with pytest.raises(RuntimeError, match='synthetic checkpoint interruption'):
        evaluate_autonomous(key, ad, budget(key), llm, **args)
    assert len(seen) == 3
    conn.execute('DELETE FROM chat_writes')
    conn.execute('DELETE FROM chat_checkpoints')
    conn.commit()
    monkeypatch.setattr(RequirementEvidenceSearch, 'read', original)
    result = evaluate_autonomous(key, ad, budget(key), llm, **args)
    assert result.matches[0].match == 'strong' and len(seen) == 4


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
    if change == 'no_retrieval': choices.pop(2)
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
    choices.append(copy.deepcopy(choices[-1]))
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


def test_configured_turn_limit_survives_resume(tmp_path):
    bundle, ad, key, llm, seen, conn, args = run_case(tmp_path, choices=[
        {'tool': 'read_file', 'arguments': {'file_path': '/skills/autonomous-evaluation/SKILL.md'}} for _ in range(8)])
    bounded = budget(key)
    bounded.role_turn_limit = 3
    for _ in range(2):
        with pytest.raises(RuntimeErrorSafe, match='turn_limit'):
            evaluate_autonomous(key, ad, bounded, llm, **args)
    assert len(seen) == 3


def test_unlimited_does_not_convert_six_call_target_to_a_cap(tmp_path):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    choices = [{'tool':'read_file','arguments':{'file_path': '/skills/autonomous-evaluation/SKILL.md'}} for _ in range(7)] + native_choices(roles)
    llm, seen = transport(choices)
    unlimited = budget(key)
    unlimited.role_turn_limit = None
    with sqlite3.connect(':memory:',check_same_thread=False) as conn:
        result=evaluate_autonomous(key,ad,unlimited,llm,conn=conn,posting={},screen={'outcome':'admit'},
            evidence_bundle=bundle,model='claude/sonnet')
    assert result.matches and len(seen)==11


def test_native_json_text_cannot_trigger_protocol_fallback(tmp_path):
    bundle, ad, key, llm, seen, conn, args = run_case(tmp_path, choices=[json.dumps({'tool': 'complete_evaluation'})])
    with pytest.raises(RuntimeErrorSafe, match='missing_evaluation'):
        evaluate_autonomous(key, ad, budget(key), llm, **args)
    assert len(seen) == 1 and 'response_format' not in seen[0]


def test_default_off_and_configuration_validation(monkeypatch):
    from pipeline.agentic.service import _config
    from jobwatch.util import model_choice
    monkeypatch.setattr(model_choice, 'chosen', lambda: {})
    assert _config({}).get('autonomous_evaluation', False) is False
    assert _config({'agentic': {'autonomous_evaluation': True}})['autonomous_version']
    with pytest.raises(Exception, match='invalid_configuration'):
        _config({'agentic': {'autonomous_evaluation': 'true'}})


def test_batch_retrieval_and_uncertainties_survive_cached_read(tmp_path):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    choices = native_choices(roles)
    choices[1]['arguments']['uncertainties'] = ['Working days unknown']
    choices[2] = {'tool': 'search_candidate_evidence_batch', 'arguments': {'queries': [{'requirement_id': 'r1'}]}}
    llm, seen = transport(choices)
    with sqlite3.connect(':memory:', check_same_thread=False) as conn:
        args = dict(conn=conn, posting={}, screen={'outcome': 'flag'}, evidence_bundle=bundle, model='claude/sonnet')
        result = evaluate_autonomous(key, ad, budget(key), llm, **args)
        assert 'Working days unknown' in result.report['E']
        assert result.matching_diagnostics['searches'][0]['requirement_id'] == 'r1'
        assert evaluate_autonomous(key, ad, budget(key), llm, **args) == result and len(seen) == 4


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


def test_incomplete_native_requirements_get_schema_feedback_without_protocol_fallback(tmp_path):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    choices = [{'tool':'complete_requirements','arguments':{'requirements':roles[1]['arguments']['requirements']}},
               *native_choices(roles)]
    llm, seen = transport(choices)
    with sqlite3.connect(':memory:',check_same_thread=False) as conn:
        result=evaluate_autonomous(key,ad,budget(key),llm,conn=conn,posting={},
            screen={'outcome':'admit'},evidence_bundle=bundle,model='claude/sonnet')
    assert result.matches and len(seen)==5
    assert 'missing_required_fields' in json.dumps(seen[1]['messages'])
    assert all('response_format' not in body for body in seen)


@pytest.mark.parametrize('fault', ['rights_quote', 'overlength_report'])
def test_invalid_completion_gets_one_targeted_correction_without_restarting(tmp_path, fault):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    valid = native_choices(roles)
    if fault == 'rights_quote':
        invalid = copy.deepcopy(valid[1])
        invalid['arguments']['facts']['work_rights'] = {'requirement': 'none_stated', 'quote': 'Absent fabricated quotation'}
        choices = [valid[0], invalid, valid[1], *valid[2:]]
        field = 'facts.work_rights.quote'
    else:
        invalid = copy.deepcopy(valid[-1])
        invalid['arguments']['report']['B'] = 'x' * 4971
        choices = [*valid[:-1], invalid, valid[-1]]
        field = 'report.B'
    llm, seen = transport(choices)
    with sqlite3.connect(':memory:', check_same_thread=False) as conn:
        result = evaluate_autonomous(key, ad, budget(key), llm, conn=conn, posting={},
            screen={'outcome': 'admit'}, evidence_bundle=bundle, model='claude/sonnet')
        assert result.matches
        assert len(seen) == 5
        feedback = [m['content'] for body in seen for m in body['messages'] if m['role'] == 'tool']
        assert any(field in value for value in feedback)
        assert evaluate_autonomous(key, ad, budget(key), llm, conn=conn, posting={},
            screen={'outcome': 'admit'}, evidence_bundle=bundle, model='claude/sonnet') == result
        assert len(seen) == 5


def test_independent_schema_and_citation_errors_each_get_one_correction(tmp_path):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    valid = native_choices(roles)
    incomplete = {'tool': 'complete_requirements', 'arguments': {'requirements': valid[0]['arguments']['requirements']}}
    invalid_quote = copy.deepcopy(valid[1])
    invalid_quote['arguments']['facts']['work_rights'] = {'requirement': 'none_stated', 'quote': 'Invented absence statement'}
    llm, seen = transport([incomplete, invalid_quote, *valid])
    with sqlite3.connect(':memory:', check_same_thread=False) as conn:
        result = evaluate_autonomous(key, ad, budget(key), llm, conn=conn, posting={},
            screen={'outcome': 'admit'}, evidence_bundle=bundle, model='claude/sonnet')
    assert result.matches and len(seen) == 6
