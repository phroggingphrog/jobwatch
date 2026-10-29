"""Native schemas advertise the same closed keys as canonical completion."""
import copy
import json
import sqlite3

from pipeline.agentic.autonomous import evaluate_autonomous
from pipeline.agentic.contracts import DIMENSIONS, REPORT_FIELDS
from test_agentic_evaluate import build_case, budget
from test_autonomous_evaluation import native_choices, transport


def test_dimension_error_identifies_dimensions_and_advertises_required_keys(tmp_path):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    choices = native_choices(roles)
    bad = copy.deepcopy(choices[-1])
    bad['arguments']['dimensions']['wrong_name'] = bad['arguments']['dimensions'].pop('cv_match')
    llm, seen = transport([*choices[:3], bad, choices[-1]])
    with sqlite3.connect(':memory:', check_same_thread=False) as conn:
        result = evaluate_autonomous(key, ad, budget(key), llm, conn=conn, posting={},
            screen={'outcome': 'admit'}, evidence_bundle=bundle, model='deepseek-flash')
    assert result.matches
    feedback = json.loads([m for m in seen[-1]['messages'] if m['role'] == 'tool'][-1]['content'])
    assert feedback['fields'] == ['dimensions']
    assert feedback['expected_keys']['dimensions'] == list(DIMENSIONS)
    tool = next(t['function'] for t in seen[0]['tools'] if t['function']['name'] == 'complete_evaluation')
    for field, keys in [('dimensions', DIMENSIONS), ('report', REPORT_FIELDS)]:
        shape = tool['parameters']['properties'][field]
        assert set(shape['required']) == set(keys)
        assert shape['additionalProperties'] is False


def test_primary_evidence_progress_identifies_unseen_records(tmp_path):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence', skill='Reconciled ledgers\n- Prepared budgets')
    assert len(bundle.items) >= 2
    choices = native_choices(roles)
    extra = {'tool': 'read_candidate_evidence', 'arguments': {'evidence_ids': [i.id for i in bundle.items]}}
    llm, seen = transport([choices[0], choices[1], choices[2], extra, choices[-1]])
    with sqlite3.connect(':memory:', check_same_thread=False) as conn:
        result = evaluate_autonomous(key, ad, budget(key), llm, conn=conn, posting={},
            screen={'outcome': 'admit'}, evidence_bundle=bundle, model='deepseek-flash')
    assert result.matches
    progress = []
    for body in seen:
        for message in body['messages']:
            if message['role'] != 'tool' or not isinstance(message.get('content'), str):
                continue
            try:
                payload = json.loads(message['content'])
            except ValueError:
                continue
            if isinstance(payload, dict) and 'evidence_progress' in payload:
                progress.append(payload['evidence_progress'])
    first = progress[0]
    last = progress[-1]
    assert first['remaining_evidence_ids'] and first['all_primary_evidence_returned'] is False
    assert last['remaining_evidence_ids'] == [] and last['all_primary_evidence_returned'] is True
    assert last['returned'] == last['total'] == len(bundle.items)


def test_essential_gap_reports_both_missing_risk_fields_without_rewriting_matches(tmp_path):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence', match='missing', score=3)
    choices = native_choices(roles)
    bad = copy.deepcopy(choices[-1])
    bad['arguments']['matches'][0].update(risk='', mitigation='')
    llm, seen = transport([*choices[:3], bad, choices[-1]])
    with sqlite3.connect(':memory:', check_same_thread=False) as conn:
        result = evaluate_autonomous(key, ad, budget(key), llm, conn=conn, posting={},
            screen={'outcome': 'admit'}, evidence_bundle=bundle, model='deepseek-flash')
    assert result.matches[0].judgment.status == 'unknown'
    feedback = json.loads([m for m in seen[-1]['messages'] if m['role'] == 'tool'][-1]['content'])
    assert feedback['fields'] == ['matches.0.risk', 'matches.0.mitigation']


def test_invalid_requirement_citation_is_corrected_before_split_ad_facts(tmp_path):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    choices = native_choices(roles)
    bad = copy.deepcopy(choices[0])
    bad['arguments']['requirements'][0]['jd_signal']['source_id'] = 'posting_ad'
    llm, seen = transport([bad, *choices])
    with sqlite3.connect(':memory:', check_same_thread=False) as conn:
        args = dict(conn=conn, posting={}, screen={'outcome': 'admit'},
                    evidence_bundle=bundle, model='deepseek-flash')
        result = evaluate_autonomous(key, ad, budget(key), llm, **args)
        assert result.matches
        feedback = json.loads([m for m in seen[1]['messages'] if m['role'] == 'tool'][-1]['content'])
        assert feedback['error'] == 'invalid_citation'
        assert feedback['fields'] == ['requirements.0.jd_signal']
        assert feedback['expected_ad_source'] == {'source_id': 'ad', 'content_hash': key.ad_hash}
        def citation_shapes(value):
            if isinstance(value, dict):
                properties = value.get('properties', {})
                if {'source_id', 'content_hash', 'quote'} <= properties.keys():
                    yield properties
                for child in value.values():
                    yield from citation_shapes(child)
            elif isinstance(value, list):
                for child in value:
                    yield from citation_shapes(child)

        for tool in seen[0]['tools']:
            function = tool['function']
            if function['name'] in {'complete_requirement_set', 'complete_ad_facts', 'complete_requirements'}:
                shapes = list(citation_shapes(function['parameters']))
                assert shapes
                assert all(citation['source_id']['const'] == 'ad' for citation in shapes)
                assert all(citation['content_hash']['const'] == key.ad_hash for citation in shapes)
            elif function['name'] == 'complete_evaluation':
                shapes = list(citation_shapes(function['parameters']))
                assert shapes
                assert all('const' not in citation['source_id'] for citation in shapes)
                assert all('const' not in citation['content_hash'] for citation in shapes)
        assert all(r.jd_signal.source_id == 'ad' for r in result.requirements.requirements)
        assert evaluate_autonomous(key, ad, budget(key), llm, **args) == result
        assert len(seen) == 5
