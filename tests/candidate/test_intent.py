from jobwatch.candidate.eligibility import evaluate_eligibility
from jobwatch.candidate.intent import normalize_intent
from jobwatch.candidate.policy import DecisionPolicy
from .policy_fixtures import fact, policy_of


def decision(*facts, text='The role is 38 hours per week.', **job):
    return evaluate_eligibility(job, policy=policy_of(*facts), ad_text=text)


def test_intent_separates_sources_and_ignores_inferences():
    intent = normalize_intent([fact('career_focus', 'Administration', fid='goal'),
        fact('preference', {'regions': ['VIC']}, fid='pref'),
        fact('constraint', {'regions': ['NSW'], 'exclusive': True}, fid='limit'),
        fact('work_rights', {'citizen': False}, fid='rights'),
        fact('constraint', 'Maybe 20 hours', fid='question'),
        fact('work_rights', {'citizen': True}, basis='inference')])
    assert [f.source_fact_id for f in intent.preferences] == ['goal', 'pref', 'question']
    assert [f.source_fact_id for f in intent.constraints] == ['limit']
    assert [f.source_fact_id for f in intent.work_rights] == ['rights']
    assert intent.ambiguous[0].source_fact_id == 'question'


def test_preferred_location_and_hours_do_not_exclude():
    result = decision(fact('location', 'Melbourne VIC'), fact('preference', {'max_hours_per_week': 24}),
                      location='Sydney NSW')
    assert result.status == 'eligible'


def test_absent_intent_hash_variants_and_real_intent_tampering():
    import pytest
    from jobwatch.candidate.contracts import digest
    policy = policy_of(fact('preference', 'Administrative roles'))
    absent = policy.model_dump(mode='json')
    absent['intent'] = None
    absent['policy_hash'] = digest({k:v for k,v in absent.items() if k != 'policy_hash'})
    assert DecisionPolicy.model_validate(absent).intent is None
    legacy = {k:v for k,v in absent.items() if k != 'intent'}
    legacy['policy_hash'] = digest({k:v for k,v in legacy.items() if k != 'policy_hash'})
    assert DecisionPolicy.model_validate(legacy).intent is None
    tampered = policy.model_dump(mode='json')
    tampered['intent']['preferences'] = []
    with pytest.raises(ValueError, match='policy_hash_mismatch'):
        DecisionPolicy.model_validate(tampered)


def test_exclusive_location_and_hours_exclude():
    assert decision(fact('location', {'regions': ['VIC'], 'exclusive': True}), location='Sydney NSW').status == 'excluded'
    assert decision(fact('constraint', {'max_hours_per_week': 24, 'exclusive': True})).reason == 'hours_exceeded'


def test_negated_exclusivity_is_not_a_constraint():
    from jobwatch.candidate.intent import is_exclusive
    for text in ('not only Melbourne', 'not exclusively Melbourne', 'I prefer not only Melbourne', 'must not only Melbourne'):
        assert not is_exclusive(text)
        assert decision(fact('location', text), location='Sydney NSW').status == 'eligible'
    assert is_exclusive('Only Melbourne')


def test_exclusive_location_does_not_include_other_preferred_location():
    policy = policy_of(fact('location', 'Sydney NSW'),
                       fact('location', {'regions': ['Melbourne VIC'], 'exclusive': True}))
    assert policy.regions == ('VIC',)
    assert evaluate_eligibility({'location': 'Sydney NSW'}, policy=policy, ad_text='Office based.').status == 'excluded'
    assert evaluate_eligibility({'location': 'Melbourne VIC'}, policy=policy, ad_text='Office based.').status == 'eligible'


def test_exclusive_hours_do_not_authorize_preferred_location():
    result = decision(fact('location', 'Melbourne VIC'),
                      fact('constraint', {'max_hours_per_week': 40, 'exclusive': True}), location='Sydney NSW')
    assert result.status == 'eligible'


def test_goal_is_not_seniority_exclusion_and_legal_limit_still_applies():
    goal = fact('career_focus', 'Administration internship')
    assert decision(goal, seniority='junior').status == 'eligible'
    assert decision(goal, fact('work_rights', {'hours_limit_per_fortnight': 48}), seniority='junior').reason == 'hours_exceeded'


def test_old_and_new_serialized_policy_hashes_validate():
    from jobwatch.candidate.contracts import digest
    policy = policy_of(fact('preference', 'clerical work'))
    assert DecisionPolicy.model_validate(policy.model_dump(mode='json')) == policy
    old = policy.model_dump(mode='json', exclude={'intent', 'policy_hash'})
    old['policy_hash'] = digest(old)
    assert DecisionPolicy.model_validate(old).intent is None


def test_confirmed_numeric_bound_and_preference_are_distinct():
    hard = fact('constraint', {'max_hours_per_week': 24})
    soft = fact('preference', {'max_hours_per_week': 24})
    assert decision(hard).reason == 'hours_exceeded'
    assert decision(soft).status == 'eligible'
    commute = fact('constraint', 'Must not commute more than 30 km')
    assert policy_of(commute).max_commute_km == 30
    assert evaluate_eligibility({'location': 'Sydney NSW'}, policy=policy_of(commute),
                                ad_text='Office based.', commute_km=40).reason == 'commute_exceeded'


def test_preferred_place_is_retained_without_a_hard_region():
    policy = policy_of(fact('location', 'Melbourne VIC'))
    assert policy.regions == () and 'location' not in policy.open_questions
    assert policy.intent.preferences[0].value == 'Melbourne VIC'


def test_ambiguous_constraint_creates_question():
    assert 'exclusion:maybe' in policy_of(fact('constraint', 'Maybe 20 hours', fid='maybe')).open_questions
