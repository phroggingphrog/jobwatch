"""Native evidence transport keeps prior source access without repeating payloads."""
import json
import sqlite3

import pytest

from test_agentic_evaluate import build_case, budget
from test_autonomous_evaluation import native_choices, transport
from pipeline.agentic.autonomous import evaluate_autonomous
from pipeline.agentic.runtime import RuntimeErrorSafe


def test_repeated_reads_return_references_and_unknown_ids_get_targeted_feedback(tmp_path):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    choices = native_choices(roles)
    read = choices[1]
    llm, seen = transport([choices[0], read, read,
        {'tool': 'read_candidate_evidence', 'arguments': {'evidence_ids': ['invented-id']}},
        choices[-1]])
    with sqlite3.connect(':memory:', check_same_thread=False) as conn:
        result = evaluate_autonomous(key, ad, budget(key), llm, conn=conn, posting={},
            screen={'outcome': 'admit'}, evidence_bundle=bundle, model='claude/sonnet')
    assert result.matches[0].judgment.status == 'demonstrated'
    outputs = [json.loads(m['content']) for m in seen[-1]['messages'] if m['role'] == 'tool']
    assert outputs[1]['items']
    assert outputs[2]['items'] == []
    assert outputs[2]['already_returned_evidence_ids'] == read['arguments']['evidence_ids']
    assert outputs[3]['error'] == 'unknown_evidence'
    assert 'invented-id' in str(outputs[3]['fields'])
    assert 'read_full_ad' not in {t['function']['name'] for t in seen[0]['tools']}


def test_batch_search_then_read_does_not_repeat_primary_payload(tmp_path):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    choices = native_choices(roles)
    llm, seen = transport([choices[0],
        {'tool': 'search_candidate_evidence_batch', 'arguments': {'queries': [{'requirement_id': 'r1'}]}},
        choices[1], choices[-1]])
    with sqlite3.connect(':memory:', check_same_thread=False) as conn:
        args = dict(conn=conn, posting={}, screen={'outcome': 'admit'}, evidence_bundle=bundle, model='claude/sonnet')
        result = evaluate_autonomous(key, ad, budget(key), llm, **args)
        assert evaluate_autonomous(key, ad, budget(key), llm, **args) == result
    outputs = [json.loads(m['content']) for m in seen[-1]['messages'] if m['role'] == 'tool']
    assert outputs[1]['items']
    assert outputs[2]['items'] == []
    assert result.matching_diagnostics['accessed_evidence_ids']
    assert len(seen) == 4


def test_unknown_evidence_correction_remains_bounded_and_cannot_grant_access(tmp_path):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    bad = {'tool': 'read_candidate_evidence', 'arguments': {'evidence_ids': ['invented-id']}}
    llm, seen = transport([native_choices(roles)[0], bad, bad])
    with sqlite3.connect(':memory:', check_same_thread=False) as conn:
        with pytest.raises(RuntimeErrorSafe, match='unknown_evidence'):
            evaluate_autonomous(key, ad, budget(key), llm, conn=conn, posting={},
                screen={'outcome': 'admit'}, evidence_bundle=bundle, model='claude/sonnet')
        assert not conn.execute("SELECT 1 FROM autonomous_results WHERE identity LIKE '%:evaluation'").fetchone()
    assert len(seen) == 3


def test_candidate_filename_cannot_be_read_as_skill_and_gets_canonical_guidance(tmp_path):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    choices = native_choices(roles)
    llm, seen = transport([choices[0],
        {'tool': 'read_file', 'arguments': {'file_path': 'master_resume.md'}},
        choices[1], choices[-1]])
    with sqlite3.connect(':memory:', check_same_thread=False) as conn:
        result = evaluate_autonomous(key, ad, budget(key), llm, conn=conn, posting={},
            screen={'outcome': 'admit'}, evidence_bundle=bundle, model='claude/sonnet')
    assert result.matches
    outputs = [json.loads(m['content']) for m in seen[-1]['messages'] if m['role'] == 'tool']
    assert outputs[1]['error'] == 'skill_path_not_allowed'
    assert outputs[1]['fields'] == ['file_path']
    assert 'read_candidate_evidence' in outputs[1]['action']
    assert 'content' not in outputs[1]
    description = next(t['function']['description'] for t in seen[0]['tools'] if t['function']['name'] == 'read_file')
    assert 'skills only' in description


def test_checkpoint_loss_after_successful_read_replays_primary_payload_without_rebuying_responses(tmp_path):
    from pipeline.agentic.runtime import BatchBudget, JobBudget

    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    choices = native_choices(roles)
    llm, seen = transport([*choices[:2], OSError('synthetic outage after evidence read')], reasoning=True)
    path = tmp_path / 'checkpoints.sqlite'
    args = dict(posting={}, screen={'outcome': 'admit'}, evidence_bundle=bundle, model='claude/sonnet')
    b = budget(key)
    with sqlite3.connect(path, check_same_thread=False) as conn:
        with pytest.raises(RuntimeErrorSafe, match='model_unavailable'):
            evaluate_autonomous(key, ad, b, llm, conn=conn, **args)
        assert len(seen) == 3
        actions = json.loads(conn.execute("SELECT payload FROM autonomous_results WHERE identity LIKE '%:actions'").fetchone()[0])
        assert actions == [{'name': 'read_candidate_evidence', 'arguments': choices[1]['arguments']}]
        conn.execute('DELETE FROM chat_writes')
        conn.execute('DELETE FROM chat_checkpoints')
        conn.commit()

    resumed_budget = JobBudget.restore(b.snapshot(), batch=BatchBudget('synthetic', token_ceiling=2_000_000))
    resumed, requests = transport(choices[2:], reasoning=True)
    with sqlite3.connect(path, check_same_thread=False) as conn:
        result = evaluate_autonomous(key, ad, resumed_budget, resumed, conn=conn, **args)
        assert result.matches[0].judgment.status == 'demonstrated'
        assert len(requests) == 1
        outputs = [json.loads(m['content']) for m in requests[0]['messages'] if m['role'] == 'tool']
        records = [record for output in outputs for record in output.get('items', [])]
        assert {record['id'] for record in records} == set(choices[1]['arguments']['evidence_ids'])
        assert records[0]['quote'] == bundle.items[0].quote
        assert requests[0]['messages'] == seen[-1]['messages']
        assert evaluate_autonomous(key, ad, resumed_budget, resumed, conn=conn, **args) == result
        assert len(requests) == 1
