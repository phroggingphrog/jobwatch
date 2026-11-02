"""Synthetic completion/recovery for the observed native tool sequence."""
import json
import sqlite3

import pytest

from pipeline.agentic.autonomous import evaluate_autonomous
from pipeline.agentic.runtime import RuntimeErrorSafe
from test_agentic_evaluate import build_case, budget
from test_autonomous_evaluation import native_choices, transport


def test_observed_search_and_wrong_filename_sequence_completes_canonically(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('legacy evaluator reached')
    monkeypatch.setattr('pipeline.agentic.evaluator.evaluate_job', forbidden)
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    choices = native_choices(roles)
    batch = {'tool': 'search_candidate_evidence_batch', 'arguments': {'queries': [{'requirement_id': 'r1'}]}}
    refine = {'tool': 'search_candidate_evidence', 'arguments': {'requirement_id': 'r1', 'related_terms': ['ledger']}}
    wrong = {'tool': 'read_file', 'arguments': {'file_path': 'master_resume.md', 'limit': 100}}
    llm, requests = transport([choices[0], batch, choices[1], choices[1], refine, wrong,
                               choices[1], choices[-1]], reasoning=True)
    with sqlite3.connect(':memory:', check_same_thread=False) as conn:
        args = dict(conn=conn, posting={}, screen={'outcome': 'admit'}, evidence_bundle=bundle, model='deepseek-flash')
        result = evaluate_autonomous(key, ad, budget(key), llm, **args)
        assert result.matches[0].judgment.status == 'demonstrated'
        outputs = [json.loads(m['content']) for m in requests[-1]['messages'] if m['role'] == 'tool']
        assert sum(len(o.get('items', [])) for o in outputs) == len(bundle.items)
        assert outputs[-2]['error'] == 'skill_path_not_allowed'
        assert outputs[-2]['fields'] == ['file_path']
        assert 'content' not in outputs[-2]
        assert all('reasoning_content' in m for m in requests[-1]['messages'] if m['role'] == 'assistant')
        assert evaluate_autonomous(key, ad, budget(key), llm, **args) == result
        assert len(requests) == 8


def test_exhausted_skill_correction_survives_private_checkpoint_restart(tmp_path):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    wrong = {'tool': 'read_file', 'arguments': {'file_path': 'master_resume.md'}}
    # Two corrections are allowed per tool: the third wrong path exhausts the persisted boundary.
    llm, requests = transport([native_choices(roles)[0], wrong, wrong, wrong], reasoning=True)
    args = dict(posting={}, screen={'outcome': 'admit'}, evidence_bundle=bundle, model='deepseek-flash')
    path = tmp_path / 'checkpoint.sqlite'
    b = budget(key)
    for _ in range(2):
        with sqlite3.connect(path, check_same_thread=False) as conn:
            with pytest.raises(RuntimeErrorSafe, match='skill_path_not_allowed'):
                evaluate_autonomous(key, ad, b, llm, conn=conn, **args)
    assert len(requests) == 4
