import pytest

from tests.candidate.policy_fixtures import fact, policy_of
from tests.test_agentic_gate import AD, evaluation, policy  # noqa: F401
from tests.test_agentic_gate_policy import job, outcome


@pytest.mark.parametrize('level', ['junior', 'entry'])
def test_internship_goal_does_not_exclude_other_entry_work(evaluation, policy, level):
    dp = policy_of(fact('career_focus', 'Find an internship in administration or clerical work'))
    ev = job(evaluation, AD, seniority=level, min_years=0, program=False)
    assert 'administration' in dp.focus[0]
    assert outcome(ev, AD, policy, dp) == ('draft', 'eligible')
    assert dp.seniority == ()


def test_seniority_preference_without_exclusive_intent_is_not_a_gate(evaluation, policy):
    dp = policy_of(fact('preference', {'seniority': ['entry']}))
    ev = job(evaluation, AD, seniority='junior', min_years=0, program=False)
    assert dp.seniority == ()
    assert outcome(ev, AD, policy, dp) == ('draft', 'eligible')


def test_confirmed_exclusive_seniority_still_gates(evaluation, policy):
    dp = policy_of(fact('constraint', {'seniority': ['entry'], 'exclusive': True}))
    ev = job(evaluation, AD, seniority='junior', min_years=0, program=False)
    assert dp.seniority == ('entry',)
    assert outcome(ev, AD, policy, dp) == ('archive', 'hard_gate')


def test_unconfirmed_exclusive_constraint_is_not_a_gate():
    value = fact('constraint', {'seniority': ['entry'], 'exclusive': True})
    value['basis'] = 'inference'
    assert policy_of(value).seniority == ()


def test_explicit_exclusive_text_is_a_gate():
    assert policy_of(fact('preference', 'Only junior roles')).seniority == ('junior',)
    assert policy_of(fact('preference', 'Only Melbourne; junior roles are fine')).seniority == ()
