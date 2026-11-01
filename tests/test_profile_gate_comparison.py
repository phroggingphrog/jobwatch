"""Frozen-input comparisons include jobs rejected by the former default gate."""
import pytest

from jobwatch.candidate.policy import profile_target_policy
from pipeline.agentic.gate import decide, assessment_audit
from tests.fixtures.frozen_person_gate_20261022 import decide as historical_decide
from tests.test_agentic_gate import evaluation, policy, AD  # noqa: F401
from tests.test_agentic_gate_policy import retarget
from tests.candidate.policy_fixtures import fact, policy_of


@pytest.mark.parametrize('place', ['Sydney NSW', 'Perth WA'])
def test_historical_rejects_current_confirmed_locations(evaluation, policy, place):
    ad = f'Junior analyst based in {place}. Part-time 24 hours per week.'
    ev = retarget(evaluation, ad, place, location_fit='outside')
    old = historical_decide(ev, ad_text=ad, policy=policy)
    current = decide(ev, ad_text=ad, policy=profile_target_policy(), decision_policy=policy_of(fact('location', place)))
    assert old.route == 'archive'
    assert current.route == 'draft'
    preferred = decide(ev, ad_text=ad, policy=profile_target_policy(), decision_policy=policy_of(fact('location', 'Melbourne VIC')))
    assert preferred.route == 'draft'
    other = decide(ev, ad_text=ad, policy=profile_target_policy(), decision_policy=policy_of(
        fact('location', {'regions': ['Melbourne VIC'], 'exclusive': True})))
    assert other.route == 'archive'


def test_weak_career_score_is_comparison_data_not_exclusion(evaluation, policy):
    ev = evaluation.model_copy(update={'global_score': 2.0,
        'dimensions': {**evaluation.dimensions, 'north_star': evaluation.dimensions['north_star'].model_copy(update={'score': 1.0})}})
    assert historical_decide(ev, ad_text=AD, policy=policy).route == 'archive'
    current = decide(ev, ad_text=AD, policy=profile_target_policy(),
        decision_policy=policy_of(fact('employment_status', 'unemployed'), fact('location', 'Melbourne VIC')))
    assert current.route == 'draft' and current.global_score == 2.0


def test_unverified_location_remains_visible_as_partial(evaluation, policy):
    ev = evaluation.model_copy(update={'location_evidence': None})
    dp = policy_of(fact('location', 'Sydney NSW'))
    assert decide(ev, ad_text=AD, policy=policy, decision_policy=dp).route == 'draft'
    audit = assessment_audit(ev, ad_text=AD, decision_policy=dp).model_dump()
    assert audit['completeness'] == 'partial' and 'location_citation_unverified' in audit['unknowns']


def test_explicit_exclusion_still_wins_over_good_scores(evaluation, policy):
    dp = policy_of(fact('exclusion', {'kind': 'family', 'value': 'accounting'}))
    assert decide(evaluation, ad_text=AD, policy=policy, decision_policy=dp).reason == 'policy_excluded'


def test_remote_label_cannot_bypass_commute_without_ad_evidence(evaluation, policy):
    ev = evaluation.model_copy(update={'location_fit': 'remote_accessible'})
    dp = policy_of(fact('location', 'Melbourne VIC'), fact('constraint', {'max_commute_km': 10}))
    result = decide(ev, ad_text=AD, policy=policy, decision_policy=dp, commute_km=100)
    assert result.route == 'archive' and result.reason == 'hard_gate'
    audit = assessment_audit(ev, ad_text=AD, decision_policy=dp, commute_km=100, decision=result).model_dump()
    assert audit['explicit_conflicts'] == ('hard_gate',)


def test_recorded_unknown_seniority_does_not_become_the_schema_placeholder(evaluation, policy):
    ev = evaluation.model_copy(update={'matching_diagnostics': {'ad_uncertainties': ['seniority unknown']}})
    for level in ['entry', 'junior']:
        dp = policy_of(fact('preference', {'seniority': [level]}))
        result = decide(ev, ad_text=AD, policy=policy, decision_policy=dp)
        assert (result.route, result.reason) == ('draft', 'eligible')
        audit = assessment_audit(ev, ad_text=AD, decision_policy=dp).model_dump()
        assert 'ad_uncertainty: seniority unknown' in audit['unknowns'] and audit['recommendation'] == 'needs_clarification'
