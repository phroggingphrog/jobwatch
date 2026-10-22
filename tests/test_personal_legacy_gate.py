"""Retained pipeline routes through the same confirmed-person eligibility service."""
from types import SimpleNamespace
from unittest.mock import Mock

from pipeline.nodes import gate
from pipeline.schemas import JobFacts, MatchScore


def facts(**changes):
    return JobFacts.model_validate(dict(real_job=True, role_family='engineering', duties=['Design systems'],
        required_skills=[], preferred_skills=[], seniority='senior', min_years=12,
        hours='full_time_only', program=False, work_rights={'requirement': 'none_stated', 'quote': ''},
        screening_questions=[], **changes))


def score():
    return MatchScore.model_validate({**{k: {'score': 1, 'evidence': 'Unknown profile evidence'}
        for k in ('technical_skills', 'experience', 'domain')}, 'wanted': 'not_wanted',
        'justification': 'A model taste score does not confirm an exclusion.'})


def test_low_domain_score_and_senior_full_time_are_not_shared_exclusions(monkeypatch):
    service = Mock(return_value=SimpleNamespace(status='eligible', reason='eligible', questions=()))
    monkeypatch.setattr('jobwatch.candidate.eligibility.evaluate_eligibility', service)
    route, decision = gate.decide(facts(), score(), 'Senior engineering role', 'Engineer',
                                 posting={'company': 'Acme', 'location': 'Sydney NSW'})
    assert route == 'draft' and decision.passed
    payload = service.call_args.args[0]
    assert payload['company'] == 'Acme' and payload['location'] == 'Sydney NSW'
    assert payload['min_years'] == 12


def test_confirmed_exclusion_and_unresolved_fact_keep_distinct_routes(monkeypatch):
    for status, route, reason in [('excluded', 'archive', 'excluded_by_rule'),
                                  ('held', 'review', 'work_rights_unknown')]:
        monkeypatch.setattr('jobwatch.candidate.eligibility.evaluate_eligibility',
                            Mock(return_value=SimpleNamespace(status=status, reason=reason, questions=())))
        got, decision = gate.decide(facts(), score(), 'Complete ad')
        assert (got, decision.reason) == (route, reason)
        assert not decision.passed


def test_non_job_is_rejected_before_person_eligibility(monkeypatch):
    service = Mock(side_effect=AssertionError('must not call'))
    monkeypatch.setattr('jobwatch.candidate.eligibility.evaluate_eligibility', service)
    f = facts().model_copy(update={'real_job': False})
    route, decision = gate.decide(f, score(), 'Not a job')
    assert (route, decision.reason) == ('archive', 'not_a_real_job')
