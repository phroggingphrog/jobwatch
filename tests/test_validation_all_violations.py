"""One correction reports every broken evaluation rule, not only the first one found.

Before the change, validate_evaluation raised at the first failure and each correction allowance was keyed by
tool and code, so a model that fixed one field learned about the next error only after another paid generation
(posting 4602: invalid_citation, then unknown_evidence, then invalid_model_payload)."""
import copy
import json
import sqlite3
from types import SimpleNamespace

import pytest

from pipeline.agentic.autonomous import CompletionError, evaluate_autonomous, validate_evaluation
from pipeline.agentic.contracts import SourceCitation
from pipeline.agentic.runtime import RuntimeErrorSafe
from test_agentic_evaluate import build_case, budget
from test_autonomous_evaluation import native_choices, transport

HASH = 'a' * 64

def _extraction():
    requirement = SimpleNamespace(id='r1', blocker=False, importance='high')
    return SimpleNamespace(requirements=SimpleNamespace(requirement_hash=HASH, requirements=(requirement,)),
                           uncertainties=())

def _search(accessed=()):
    return SimpleNamespace(accessed=set(accessed), diagnostics=lambda model: {})

def _broken_evaluation(bundle, *, report_e='Evidence-grounded synthetic analysis'):
    """A citation inside cv.md but outside the evidence item, an unseen reviewed id, and an over-long report."""
    item = bundle.items[0]
    citation = SourceCitation(source_id=item.source_file, content_hash=item.source_hash,
                              quote='# Synthetic candidate')
    match = SimpleNamespace(
        requirement_id='r1', match='strong', risk='', mitigation='', evidence=(citation,),
        judgment=SimpleNamespace(status='demonstrated', reviewed_evidence_ids=('not-returned',),
                                 contradiction_evidence=()))
    return SimpleNamespace(requirements_hash=HASH, matches=(match,), archetype='entry accounting',
        global_score=4.2, report={key: report_e if key == 'E' else 'Evidence-grounded synthetic analysis'
                                  for key in 'ABCDEFG'},
        dimensions={name: SimpleNamespace(score=4.2, reason='Bound synthetic evidence reviewed')
                    for name in ('cv_match', 'north_star', 'compensation', 'culture', 'red_flags')})

def _violations(value, bundle):
    with pytest.raises(CompletionError) as caught:
        validate_evaluation(value, key=None, extraction=_extraction(), bundle=bundle,
                            search=_search(), model='deepseek-flash', commute_km=None)
    return caught.value

def test_one_error_lists_citation_unknown_evidence_and_long_report(tmp_path):
    bundle, _, _, _ = build_case(tmp_path / 'evidence')
    error = _violations(_broken_evaluation(bundle, report_e='x' * 4001), bundle)
    assert error.code == 'invalid_evaluation'
    assert dict(error.violations) == {
        'invalid_candidate_citation': ('matches.0.evidence',),
        'unretrieved_evidence': ('matches.0.judgment.reviewed_evidence_ids',),
        'invalid_evaluation': ('report.E',)}
    assert 'report.E' in error.fields

def _bad_completion(choices):
    """A partial gap with no risk, an unread reviewed id and a citation outside the evidence item."""
    bad = copy.deepcopy(choices[-1])
    match = bad['arguments']['matches'][0]
    match['match'] = 'partial'
    match['judgment']['status'] = 'partial'
    match['judgment']['open_question'] = 'What primary evidence establishes the remaining requirement?'
    match['evidence'][0]['quote'] = '# Synthetic candidate'
    match['judgment']['reviewed_evidence_ids'].append('not-returned')
    return bad

def test_feedback_answer_carries_every_violation_once(tmp_path):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    choices = native_choices(roles)
    llm, seen = transport([*choices[:-1], _bad_completion(choices), choices[-1]])
    with sqlite3.connect(':memory:', check_same_thread=False) as conn:
        result = evaluate_autonomous(key, ad, budget(key), llm, conn=conn, posting={'title': 'Synthetic analyst'},
            screen={'outcome': 'admit', 'rules_hash': 'test'}, evidence_bundle=bundle, model='deepseek-flash')
    assert result.matches[0].requirement_id == 'r1' and result.matches[0].match == 'strong' 
    answers = [json.loads(message['content']) for body in seen for message in body['messages']
               if message['role'] == 'tool' and isinstance(message.get('content'), str)
               and '"violations"' in message['content']]
    assert len(answers) == 1
    assert {entry['error'] for entry in answers[0]['violations']} == {
        'invalid_candidate_citation', 'unretrieved_evidence', 'invalid_evaluation'}
    assert all(entry['action'] for entry in answers[0]['violations'])

def test_third_invalid_submission_on_a_tool_stops_the_run(tmp_path):
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    choices = native_choices(roles)
    bad = _bad_completion(choices)
    llm, _ = transport([*choices[:-1], bad, copy.deepcopy(bad), copy.deepcopy(bad)])
    with sqlite3.connect(':memory:', check_same_thread=False) as conn:
        with pytest.raises(RuntimeErrorSafe) as caught:
            evaluate_autonomous(key, ad, budget(key), llm, conn=conn, posting={'title': 'Synthetic analyst'},
                screen={'outcome': 'admit', 'rules_hash': 'test'}, evidence_bundle=bundle, model='deepseek-flash')
    assert caught.value.code == 'invalid_evaluation'
