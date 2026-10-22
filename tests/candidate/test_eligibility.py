"""Invented contrasting profiles; no candidate records or provider calls."""
import pytest
from jobwatch.candidate.eligibility import evaluate_eligibility
from .policy_fixtures import fact, policy_of

def check(text, *facts, **job):
    return evaluate_eligibility({'title': 'Example role', **job}, policy=policy_of(*facts), ad_text=text)

def test_hours_compare_numbers_not_fulltime_label():
    limited = fact('work_rights', {'hours_limit_per_fortnight': 80})
    assert check('Full-time, 38 hours per week.', limited, hours='full_time_only').status == 'eligible'
    assert check('Full-time, 42 hours per week.', limited, hours='full_time_only').status == 'excluded'
    assert check('Full-time.', limited, hours='full_time_only').status == 'held'

def test_missing_hours_are_unresolved_only_when_limit_matters():
    assert check('A real vacancy.', fact('work_rights', {'hours_limit_per_fortnight': 48})).status == 'held'
    assert check('A real vacancy.').status == 'eligible'

def test_junior_preference_does_not_impose_two_year_cap():
    assert check('Junior role, 4 years experience required.', fact('preference', {'seniority': ['junior']}),
                 seniority='junior', min_years=4).status == 'eligible'

@pytest.mark.parametrize('rights,wanted', [({'permanent_resident': True}, 'held'),
    ({'citizen': False, 'permanent_resident': True}, 'excluded'), ({'citizen': True}, 'eligible'),
    ({'citizen_or_pr': True}, 'held')])
def test_pr_is_not_citizenship(rights, wanted):
    q = 'Applicants must be Australian citizens only.'
    assert check(q, fact('work_rights', rights), work_rights={'requirement': 'citizen_only', 'quote': q}).status == wanted

def test_clearance_matches_level_and_unknown_never_becomes_no():
    q = 'An existing NV1 security clearance is required.'
    job = {'work_rights': {'requirement': 'clearance', 'quote': q}}
    assert check(q, fact('work_rights', {'clearances': ['NV1']}), **job).status == 'eligible'
    assert check(q, fact('work_rights', {'clearances': []}), **job).status == 'excluded'
    assert check(q, **job).status == 'held'

def test_no_sponsorship_only_blocks_confirmed_need():
    q = 'We cannot provide visa sponsorship.'
    assert check(q, fact('work_rights', {'requires_sponsorship': False})).status == 'eligible'
    assert check(q, fact('work_rights', {'requires_sponsorship': True})).status == 'excluded'
    assert check(q).status == 'held'

def test_location_and_remote_are_personal():
    job = {'location': 'Sydney NSW', 'seniority': 'senior'}
    assert check('Based in Sydney NSW.', fact('location', 'Sydney NSW'), **job).status == 'eligible'
    assert check('Based in Sydney NSW.', fact('location', 'Melbourne VIC'), **job).status == 'excluded'
    assert check('Remote anywhere in Australia.', fact('preference', {'remote_ok': False}), remote=True).status == 'excluded'

def test_explicit_none_is_neutral_and_does_not_read_live_profile(monkeypatch):
    monkeypatch.setattr('jobwatch.candidate.policy.policy_for', lambda _: pytest.fail('read live profile'))
    assert evaluate_eligibility({'seniority': 'senior', 'hours': 'full_time_only'}, policy=None,
                                ad_text='Full-time senior vacancy.').status == 'eligible'

def test_rights_quotes_must_resolve():
    assert check('Other words.', fact('work_rights', {'citizen': True}),
        work_rights={'requirement': 'citizen_only', 'quote': 'Applicants must be Australian citizens only.'}).status == 'held'


@pytest.mark.parametrize('claim', ['British citizen on an Australian temporary visa',
    'United States citizen', 'Permanent resident of Canada', 'New Zealand permanent resident',
    'British citizen in Australia on a temporary visa', 'I am not a citizen of Canada.',
    'I am not a citizen or permanent resident of Canada.',
    'I am not a citizen or permanent resident in Canada.',
    'British citizen or permanent resident of Australia',
    'Australian citizen or permanent resident of Canada'])
def test_foreign_status_does_not_establish_australian_status(claim):
    q = 'Applicants must be Australian citizens or permanent residents.'
    assert check(q, fact('work_rights', claim),
                 work_rights={'requirement': 'citizen_or_pr', 'quote': q}).status == 'held'


def test_plural_pr_alternative_does_not_waive_nationality_conjunction():
    q = 'Applicants must be citizens or PRs and hold full working rights.'
    decision = check(q, fact('work_rights', {'citizen': False, 'permanent_resident': False,
        'valid_work_rights': True, 'unrestricted_work_rights': False}))
    assert decision.status != 'eligible'


def test_boolean_keyword_flood_stays_bounded():
    import time
    started = time.monotonic()
    decision = check('or ' * 7000)
    assert decision.status == 'eligible'
    assert time.monotonic() - started < 2


def test_negated_citizenship_requirement_cannot_be_reintroduced_by_model_label():
    q = 'Australian citizenship is not required.'
    result = check(q, fact('work_rights', {'citizen': False}),
        work_rights={'requirement': 'citizen_only', 'quote': q})
    assert result.status != 'excluded'


def test_verbatim_unrelated_quote_does_not_prove_citizenship_requirement():
    q = 'Join our friendly team and learn new skills.'
    result = check(q, fact('work_rights', {'citizen': False}),
        work_rights={'requirement': 'citizen_only', 'quote': q})
    assert result.status == 'held'
    assert result.reason == 'verification_required'


def test_same_sentence_requires_both_citizenship_and_clearance():
    q = 'Applicants must be Australian citizens and hold an existing NV1 security clearance.'
    assert check(q, fact('work_rights', {'citizen': False, 'permanent_resident': True,
        'clearances': ['NV1']})).status == 'excluded'


def test_confirmed_disjunctive_rights_statement_does_not_prove_citizenship_alone():
    q = 'Applicants must be Australian citizens only.'
    assert check(q, fact('work_rights', 'Australian citizen or permanent resident')).status == 'held'


def test_negative_citizenship_disjunction_does_not_become_positive_residence():
    q = 'Applicants must be Australian citizens or permanent residents.'
    assert check(q, fact('work_rights', 'I am not an Australian citizen or permanent resident.')).status == 'excluded'


@pytest.mark.parametrize('facts', [
    ({'clearances': []}, {'clearances': ['NV1']}),
    ({'clearances': ['NV1']}, {'clearances': []}),
])
def test_contradictory_confirmed_clearance_claims_require_resolution(facts):
    q = 'An existing NV1 security clearance is required.'
    assert check(q, *(fact('work_rights', value) for value in facts)).status == 'held'


def test_able_to_obtain_clearance_does_not_require_already_holding_it():
    q = 'Applicants must be eligible to obtain NV1 security clearance.'
    assert check(q, fact('work_rights', {'clearances': []})).status == 'held'


def test_clearance_text_cannot_make_one_level_prove_another():
    q = 'An existing NV1 or NV2 security clearance is required.'
    assert check(q, fact('work_rights', {'clearances': ['NV2']})).status == 'eligible'


@pytest.mark.parametrize('hours', [
    'The role is 38 hours per week. The cafeteria opens 10 hours per week.',
    'The role is 38 hours per week, with 5 hours per week of training included.',
])
def test_unrelated_or_included_hours_do_not_reduce_required_working_hours(hours):
    assert check(hours, fact('work_rights', {'hours_limit_per_fortnight': 48})).status == 'excluded'


def test_multiple_confirmed_hour_limits_do_not_expand_permission_by_fact_order():
    facts = [fact('work_rights', {'hours_limit_per_fortnight': n}) for n in (48, 80)]
    for ordered in (facts, list(reversed(facts))):
        assert check('The role is 38 hours per week.', *ordered).status in ('held', 'excluded')


def test_numeric_weekly_hour_limit_inside_work_rights_is_not_dropped():
    assert check('The role is 38 hours per week.',
        fact('work_rights', {'max_hours_per_week': 24})).status == 'excluded'


def test_profile_title_exception_cannot_override_approved_hours_limit():
    assert check('The role is 38 hours per week.',
        fact('work_rights', {'hours_limit_per_fortnight': 48, 'full_time_programs_ok': True}),
        title='Graduate Accountant').status == 'excluded'


def test_no_sponsorship_support_needed_is_not_an_employer_refusal():
    q = 'No sponsorship restrictions apply; visa sponsorship is available for this position.'
    assert check(q, fact('work_rights', {'requires_sponsorship': True})).status == 'eligible'


def test_contradictory_explicit_citizen_claims_cannot_be_resolved_by_combined_claim():
    q = 'Applicants must be Australian citizens or permanent residents.'
    assert check(q, fact('work_rights', {'citizen': True}),
        fact('work_rights', {'citizen': False})).status == 'held'


def test_required_onsite_location_overrides_generic_office_alternatives():
    text = 'Offices in Melbourne VIC or Sydney NSW. This role requires attendance at the Sydney NSW office.'
    assert check(text, fact('location', 'Melbourne VIC'), location='Melbourne VIC or Sydney NSW').status == 'excluded'
    assert check(text, fact('location', 'Sydney NSW'), location='Melbourne VIC or Sydney NSW').status == 'eligible'


def test_required_onsite_location_missing_from_metadata_is_still_checked():
    text = 'This role requires attendance at the Sydney NSW office.'
    assert check(text, fact('location', 'Melbourne VIC')).status == 'excluded'


def test_missing_location_or_commute_cannot_become_verified_eligibility():
    assert check('Office based role.', fact('location', 'Sydney NSW')).status == 'held'
    result = check('Office based role in Sydney NSW.', fact('location', 'Sydney NSW'),
        fact('constraint', {'max_commute_km': 15}), location='Sydney NSW')
    assert result.status == 'held' and 'commute_distance' in result.questions


def test_omitted_policy_resolves_only_the_current_person_on_each_call(monkeypatch):
    from jobwatch import users
    policies = {'synthetic-a': policy_of(fact('work_rights', {'citizen': True})),
                'synthetic-b': policy_of(fact('work_rights', {'citizen': False}))}
    monkeypatch.setattr('jobwatch.candidate.policy.policy_for', policies.get)
    text = 'Applicants must be Australian citizens only.'
    for person, status in (('synthetic-a', 'eligible'), ('synthetic-b', 'excluded'), ('synthetic-a', 'eligible')):
        with users.use(person):
            assert evaluate_eligibility({}, ad_text=text).status == status


def test_inferred_rights_cannot_certify_a_restriction():
    text = 'Applicants must be Australian citizens only.'
    assert check(text, fact('work_rights', {'citizen': True}, basis='inference')).status == 'held'


def test_generic_clearance_prerequisite_is_unknown_without_a_confirmed_clearance():
    assert check('Clearance is prerequisite.').status == 'held'


def test_supplied_quote_must_corroborate_rights_independently_of_another_sentence():
    text = 'Process invoices weekly. Applicants must be Australian citizens.'
    assert check(text, fact('work_rights', {'citizen': False}),
        work_rights={'requirement': 'citizen_only', 'quote': 'Process invoices weekly.'}).reason == 'verification_required'


def test_named_visa_alternative_does_not_require_citizenship_or_establish_visa_match():
    text = 'Applicants must be a citizen of Australia or hold a Graduate Visa.'
    assert check(text, fact('work_rights', {'citizen': False, 'permanent_resident': False,
        'valid_work_rights': True})).status == 'held'


def test_explicit_valid_rights_requirement_is_unresolved_without_approved_rights():
    assert check('Applicants must have valid working rights in Australia.').status == 'held'


def test_only_allowlisted_split_keywords_are_repaired_for_rights_scanning():
    q = 'Applicants must be a C itizen of Australia.'
    assert check(q, fact('work_rights', {'citizen': False}),
        work_rights={'requirement': 'citizen_only', 'quote': q}).status == 'excluded'


def test_attendance_requirement_keeps_location_before_the_required_word():
    text = 'Melbourne VIC or Sydney NSW offices. Sydney office attendance is required.'
    assert check(text, fact('location', 'Melbourne VIC'), location='Melbourne VIC or Sydney NSW').status == 'excluded'


def test_remote_work_needs_posting_evidence_for_the_supported_country():
    assert check('Remote Europe. Australian work rights required.', fact('location', 'Melbourne VIC'),
        remote=True, location='Remote Europe').status == 'held'


def test_conflicting_explicit_rights_are_not_overwritten_by_citizenship_inference():
    text = 'Applicants must have valid working rights in Australia.'
    assert check(text, fact('work_rights', {'citizen': True, 'valid_work_rights': False})).status == 'held'


def test_conflicting_combined_and_independent_rights_need_resolution():
    text = 'Applicants must be Australian citizens or permanent residents.'
    assert check(text, fact('work_rights', {'citizen_or_pr': True, 'citizen': False,
        'permanent_resident': False})).status == 'held'
    assert check(text, fact('work_rights', {'citizen_or_pr': False, 'citizen': True})).status == 'held'


def test_conflicting_combined_rights_claims_do_not_make_a_negative_fact():
    text = 'Applicants must be Australian citizens or permanent residents.'
    assert check(text, fact('work_rights', {'citizen_or_pr': True}),
        fact('work_rights', {'citizen_or_pr': False})).status == 'held'


def test_inconsistent_sponsorship_and_citizenship_facts_need_resolution():
    assert check('We cannot provide visa sponsorship.',
        fact('work_rights', {'citizen': True, 'requires_sponsorship': True})).status == 'held'


@pytest.mark.parametrize('location,text', [
    ('New York, USA', 'This role requires you to be based in the United States.'),
    ('London, UK', 'Must be based in the UK.'),
])
def test_supported_country_boundary_applies_without_personal_regional_limits(location, text):
    assert check(text, fact('location', 'Anywhere in Australia'), location=location).status == 'excluded'


def test_citizenship_and_negated_clearance_are_independent_clauses():
    assert check('Applicants must be Australian citizens and no security clearance is required.',
        fact('work_rights', {'citizen': True, 'clearances': []})).status == 'eligible'


@pytest.mark.parametrize('approved,expected', [
    ({'citizen': True, 'clearances': []}, 'eligible'),
    ({'citizen': False, 'clearances': ['NV1']}, 'eligible'),
    ({'citizen': False, 'clearances': []}, 'excluded'),
    ({'clearances': []}, 'held'),
])
def test_citizenship_or_clearance_allows_either_confirmed_alternative(approved, expected):
    text = 'Applicants must be Australian citizens or hold NV1 clearance.'
    assert check(text, fact('work_rights', approved)).status == expected


@pytest.mark.parametrize('family', ['retail sales floor', 'unclassified_role', 'unknown', None])
def test_unrecognized_family_does_not_bypass_a_confirmed_family_exclusion(family):
    result = check('A real vacancy.', fact('exclusion', {'kind': 'family', 'value': 'retail'}), role_family=family)
    assert result.status == 'held' and 'role_family' in result.questions


@pytest.mark.parametrize('disclaimer', ['Sydney office attendance is not required.',
    'You are not required to attend the Sydney office.'])
def test_negated_onsite_requirement_does_not_override_remote_availability(disclaimer):
    assert check('Remote anywhere in Australia. ' + disclaimer,
        fact('location', 'Melbourne VIC'), fact('preference', {'remote_ok': True}),
        remote=True, location='Remote anywhere in Australia').status == 'eligible'


def test_without_restrictions_or_sponsorship_is_not_a_choice_of_restrictions():
    text = 'Applicants must have the right to work without restriction or requiring visa sponsorship.'
    assert check(text, fact('work_rights', {'valid_work_rights': True,
        'unrestricted_work_rights': False, 'requires_sponsorship': False})).status == 'excluded'


@pytest.mark.parametrize('text', ['Applicants must reside in the UK.',
    'Applicants must live in the United States.', 'Applicants must be residents of Canada.'])
def test_foreign_residency_requirement_uses_reside_live_and_resident_wording(text):
    assert check(text, fact('location', 'Anywhere in Australia')).status == 'excluded'


@pytest.mark.parametrize('text', [
    'Applicants must be based in Australia or the United Kingdom.',
    'Applicants must be based in Sydney NSW or London UK.',
    'Applicants must reside in the UK or Australia.',
])
def test_explicit_supported_country_alternative_is_not_a_foreign_only_restriction(text):
    assert check(text, fact('location', 'Anywhere in Australia'), location='Sydney NSW').status != 'excluded'


@pytest.mark.parametrize('text', ['You must not attend the Sydney office.',
    'You must not be based in the UK.', 'You are required not to attend the Sydney office.'])
def test_negative_attendance_and_residency_requirements_are_not_positive_demands(text):
    assert check('Remote anywhere in Australia. ' + text,
        fact('location', 'Melbourne VIC'), fact('preference', {'remote_ok': True}),
        remote=True, location='Remote anywhere in Australia').status == 'eligible'


@pytest.mark.parametrize('text', ['Applicants must be based in Australia or the United Kingdom only.',
    'Applicants must reside in Australia or Canada only.', 'Australia or New Zealand residents only.'])
def test_foreign_only_shortcut_also_preserves_australian_alternatives(text):
    assert check(text, fact('location', 'Anywhere in Australia'), location='Sydney NSW').status != 'excluded'


def test_duties_for_foreign_residents_are_not_an_applicant_residency_requirement():
    assert check('This role requires supporting residents in the UK.',
        fact('location', 'Melbourne VIC'), location='Melbourne VIC').status == 'eligible'
