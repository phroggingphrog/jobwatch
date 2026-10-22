"""Synthetic tests for the gate's decision-policy path (location, commute and exclusions follow the profile)."""
import hashlib

import pytest

from jobwatch.candidate.contracts import TargetPolicy
from pipeline.agentic import gate
from pipeline.agentic.contracts import AgenticError, AgenticEvaluation, RequirementSet
from pipeline.agentic.gate import decide
from tests.candidate.policy_fixtures import fact, policy_of
from tests.test_agentic_gate import evaluation, policy  # noqa: F401  (shared synthetic fixtures)
from tests.test_agentic_gate import AD

RIGHTS = " Australian work rights required."
SYDNEY_AD = "Graduate accounting analyst based in the Sydney NSW office." + RIGHTS
MELBOURNE_AD = "Graduate accounting analyst based in Melbourne VIC." + RIGHTS
REMOTE_AD = "Graduate accounting analyst, remote within Australia." + RIGHTS
BOTH_AD = ("Graduate accounting analyst based in Melbourne VIC or Sydney NSW. "
           "Sydney office attendance is required." + RIGHTS)
SYDNEY_ONSITE_AD = "Graduate accounting analyst. Sydney office attendance required." + RIGHTS

VIC = fact("location", "Melbourne, VIC")
NSW = fact("location", "Sydney, NSW")


def retarget(evaluation, ad, quote, **changes):
    """The fixture evaluation rebuilt for a new ad: run key, requirements and the location citation follow `ad`."""
    h = hashlib.sha256(ad.encode()).hexdigest()
    return AgenticEvaluation.model_validate({
        **evaluation.model_dump(),
        "run_key": evaluation.run_key.model_copy(update={"ad_hash": h}),
        "requirements": RequirementSet(ad_hash=h, requirements=()),
        "location_evidence": {"source_id": "ad", "content_hash": h, "quote": quote},
        **changes,
    })


def outcome(ev, ad, policy, dp, **kwargs):
    result = decide(ev, ad_text=ad, policy=policy, decision_policy=dp, **kwargs)
    return result.route, result.reason


def test_nsw_person_is_not_archived_for_a_sydney_job(evaluation, policy):
    ev = retarget(evaluation, SYDNEY_AD, "Sydney NSW")   # the stored legacy label stays 'melbourne' and is ignored
    assert ev.location_fit == "melbourne"
    assert outcome(ev, SYDNEY_AD, policy, policy_of(NSW)) == ("draft", "eligible")


def test_nsw_person_archives_a_melbourne_job(evaluation, policy):
    ev = retarget(evaluation, MELBOURNE_AD, "Melbourne VIC")
    assert outcome(ev, MELBOURNE_AD, policy, policy_of(NSW)) == ("archive", "hard_gate")


def test_stored_outside_label_is_ignored(evaluation, policy):
    ev = retarget(evaluation, MELBOURNE_AD, "Melbourne VIC", location_fit="outside")
    assert outcome(ev, MELBOURNE_AD, policy, policy_of(VIC)) == ("draft", "eligible")


def test_interstate_onsite_rule_follows_the_persons_regions(evaluation, policy):
    ev = retarget(evaluation, BOTH_AD, "Melbourne VIC or Sydney NSW")
    # A Victorian person is open to the listed Melbourne office, but Sydney attendance is an interstate on-site demand.
    assert outcome(ev, BOTH_AD, policy, policy_of(VIC)) == ("archive", "hard_gate")
    # The same ad for a NSW person: Sydney is their region, and the Melbourne alternative is not on-site.
    assert outcome(ev, BOTH_AD, policy, policy_of(NSW)) == ("draft", "eligible")
    # No regions: no area filter at all.
    assert outcome(ev, BOTH_AD, policy, policy_of(fact("experience", "x"))) == ("draft", "eligible")


def test_interstate_ad_cited_at_the_interstate_office(evaluation, policy):
    ev = retarget(evaluation, SYDNEY_ONSITE_AD, "Sydney office attendance required")
    assert outcome(ev, SYDNEY_ONSITE_AD, policy, policy_of(VIC)) == ("archive", "hard_gate")
    assert outcome(ev, SYDNEY_ONSITE_AD, policy, policy_of(NSW)) == ("draft", "eligible")
    assert outcome(ev, SYDNEY_ONSITE_AD, policy, policy_of(fact("experience", "x"))) == ("draft", "eligible")


def test_no_location_policy_never_blocks_on_location(evaluation, policy):
    ev = evaluation.model_copy(update={"location_fit": "unknown", "location_evidence": None})
    assert outcome(ev, AD, policy, policy_of(fact("experience", "x"))) == ("draft", "eligible")


def test_unknown_location_with_regions_holds(evaluation, policy):
    ad = "Graduate accounting analyst. Level 3, 1 Example St." + RIGHTS
    ev = retarget(evaluation, ad, "Level 3, 1 Example St", location_fit="unknown")
    assert outcome(ev, ad, policy, policy_of(VIC)) == ("hold", "insufficient_evidence")


def test_missing_location_evidence_with_regions_holds(evaluation, policy):
    ev = evaluation.model_copy(update={"location_evidence": None})
    assert outcome(ev, AD, policy, policy_of(VIC)) == ("hold", "insufficient_evidence")


def test_nominate_your_office_program_keeps_unresolved_location_open(evaluation, policy):
    ad = "Graduate program. Nominate your office location when you apply." + RIGHTS
    ev = retarget(evaluation, ad, "Nominate your office location when you apply", location_fit="unknown")
    assert outcome(ev, ad, policy, policy_of(VIC)) == ("hold", "insufficient_evidence")


def test_non_australia_only_ads_are_archived(evaluation, policy):
    ad = MELBOURNE_AD + " US residents only."
    ev = retarget(evaluation, ad, "Melbourne VIC")
    assert outcome(ev, ad, policy, policy_of(VIC)) == ("archive", "hard_gate")


def test_commute_limit_comes_only_from_the_policy(evaluation, policy):
    dp30 = policy_of(fact("constraint", "no more than 30 km commute"), VIC)
    dp_none = policy_of(VIC)
    assert outcome(evaluation, AD, policy, dp30, commute_km=40) == ("archive", "hard_gate")
    assert outcome(evaluation, AD, policy, dp30, commute_km=25) == ("draft", "eligible")
    assert outcome(evaluation, AD, policy, dp30) == ("hold", "insufficient_evidence")   # material distance stays unresolved
    assert outcome(evaluation, AD, policy, dp_none, commute_km=500) == ("draft", "eligible")
    remote = retarget(evaluation, REMOTE_AD, "remote within Australia", location_fit="remote_accessible")
    assert outcome(remote, REMOTE_AD, policy, dp30, commute_km=40) == ("draft", "eligible")


def test_remote_ad_is_not_archived_on_distance(evaluation, policy):
    limit = fact("constraint", "no more than 30 km commute")
    remote = retarget(evaluation, REMOTE_AD, "remote within Australia", location_fit="remote_accessible")
    assert outcome(remote, REMOTE_AD, policy, policy_of(limit), commute_km=40) == ("draft", "eligible")   # no regions
    ad = "Graduate accounting analyst. Remote, Melbourne VIC." + RIGHTS
    named = retarget(evaluation, ad, "Remote, Melbourne VIC", location_fit="remote_accessible")
    assert outcome(named, ad, policy, policy_of(limit, VIC), commute_km=40) == ("draft", "eligible")
    # The person rules remote work out: distance applies again.
    assert outcome(named, ad, policy, policy_of(limit, VIC, fact("preference", "no remote")),
                   commute_km=40) == ("archive", "hard_gate")
    # A job that is not remote keeps the distance rule.
    assert outcome(evaluation, AD, policy, policy_of(limit, VIC), commute_km=40) == ("archive", "hard_gate")


def test_remote_ad_must_establish_australia(evaluation, policy):
    europe_ad = "Graduate accounting analyst. Remote - Europe." + RIGHTS
    europe = retarget(evaluation, europe_ad, "Remote - Europe", location_fit="remote_accessible")
    assert outcome(europe, europe_ad, policy, policy_of(VIC)) == ("hold", "insufficient_evidence")
    anywhere_ad = "Graduate accounting analyst. Remote - anywhere in Europe." + RIGHTS
    anywhere = retarget(evaluation, anywhere_ad, "Remote - anywhere in Europe", location_fit="remote_accessible")
    assert outcome(anywhere, anywhere_ad, policy, policy_of(VIC)) == ("hold", "insufficient_evidence")
    in_au_ad = "Graduate accounting analyst. Remote - anywhere in Australia." + RIGHTS
    in_au = retarget(evaluation, in_au_ad, "Remote - anywhere in Australia", location_fit="remote_accessible")
    assert outcome(in_au, in_au_ad, policy, policy_of(VIC)) == ("draft", "eligible")
    wide_ad = "Graduate accounting analyst. Remote, Australia wide." + RIGHTS
    wide = retarget(evaluation, wide_ad, "Remote, Australia wide", location_fit="remote_accessible")
    assert outcome(wide, wide_ad, policy, policy_of(VIC)) == ("draft", "eligible")


def _rule(kind, value):
    return fact("exclusion", {"kind": kind, "value": value})


EXCLUSION_CASES = [
    # id, rule, ad, quote, location_fit, company, title, expected
    ("family", _rule("family", "accounting"), AD, "Melbourne office", "melbourne", "", "", ("archive", "policy_excluded")),
    ("employer", _rule("employer", "example"), AD, "Melbourne office", "melbourne", "Example Pty Ltd", "",
     ("archive", "policy_excluded")),
    ("employer-whole-word", _rule("employer", "sales"), AD, "Melbourne office", "melbourne", "Salesforce Pty", "",
     ("draft", "eligible")),
    ("employer-no-company", _rule("employer", "example"), AD, "Melbourne office", "melbourne", "", "",
     ("draft", "eligible")),
    ("title-term", _rule("title_term", "graduate"), AD, "Melbourne office", "melbourne", "", "Graduate Accountant",
     ("archive", "policy_excluded")),
    ("work-type-remote", _rule("work_type", "remote"), REMOTE_AD, "remote within Australia", "remote_accessible", "", "",
     ("archive", "policy_excluded")),
    ("location-only", _rule("location", "NSW"), SYDNEY_AD, "Sydney NSW", "melbourne", "", "",
     ("archive", "policy_excluded")),
    ("location-alternatives", _rule("location", "NSW"), "Graduate accounting analyst in Sydney NSW or Melbourne VIC." + RIGHTS,
     "Sydney NSW or Melbourne VIC", "melbourne", "", "", ("draft", "eligible")),
]


@pytest.mark.parametrize("rule,ad,quote,fit,company,title,expected",
                         [c[1:] for c in EXCLUSION_CASES], ids=[c[0] for c in EXCLUSION_CASES])
def test_exclusions_are_rules(evaluation, policy, rule, ad, quote, fit, company, title, expected):
    ev = retarget(evaluation, ad, quote, location_fit=fit)
    result = decide(ev, ad_text=ad, title=title, policy=policy, decision_policy=policy_of(rule), company=company)
    assert (result.route, result.reason) == expected


def test_unemployment_does_not_override_exclusion(evaluation, policy):
    dp = policy_of(fact("employment_status", "Currently unemployed"),
                   fact("exclusion", {"kind": "family", "value": "accounting"}))
    assert evaluation.global_score == 4.0   # the score would pass, so the exclusion is the cause
    assert outcome(evaluation, AD, policy, dp) == ("archive", "policy_excluded")


def test_a_family_rule_holds_an_ad_the_evaluator_could_not_place(evaluation, policy):
    ev = evaluation.model_copy(update={"facts": evaluation.facts.model_copy(update={"role_family": "unknown"})})
    assert outcome(ev, AD, policy, policy_of(_rule("family", "accounting"))) == ("hold", "insufficient_evidence")
    assert outcome(ev, AD, policy, policy_of(VIC)) == ("draft", "eligible")   # no family rule: nothing to hold for


def test_allowed_families_and_live_exclusions_are_not_consulted_on_the_policy_path(evaluation, policy):
    only_acc = TargetPolicy(version="t", allowed_families=("accounting",))
    ev = evaluation.model_copy(update={"facts": evaluation.facts.model_copy(update={"role_family": "engineering"})})
    # Neither a structural projection nor an unapproved live file is a confirmed exclusion.
    assert outcome(ev, AD, only_acc, policy_of(VIC)) == ("draft", "eligible")
    assert outcome(ev, AD, only_acc, None) == ("draft", "eligible")


def test_policy_path_reads_no_profile_files_or_victoria_constants(evaluation, policy, monkeypatch):
    def boom(name):
        def raiser(*a, **k):
            raise AssertionError(name)
        return raiser
    for name in ("hours_limit_per_fortnight", "full_time_programs_ok", "excluded_families", "cited_victoria_location"):
        monkeypatch.setattr(gate, name, boom(name), raising=False)
    assert outcome(evaluation, AD, policy, policy_of(VIC)) == ("draft", "eligible")


def test_wrong_input_types_raise_the_fixed_code(evaluation, policy):
    for kwargs in ({"decision_policy": "not a policy"}, {"company": 7}):
        with pytest.raises(AgenticError) as caught:
            decide(evaluation, ad_text=AD, policy=policy, **kwargs)
        assert str(caught.value) == "invalid_gate_input"


def test_company_defaults_to_empty_and_none_policy_remains_neutral(evaluation, policy):
    assert outcome(evaluation, AD, policy, None) == ("draft", "eligible")


# Personal eligibility uses public gate behavior; deleted donor heuristics are not a contract.
from pipeline.agentic.contracts import Requirement, RequirementMatch, SourceCitation  # noqa: E402

PLAIN = fact("experience", "x")


def rights(**value):
    return fact("work_rights", value)


def stated(*levels):
    words = ["mid-level" if level == "mid" else level for level in levels]
    return policy_of(fact("preference", {"seniority": words})) if levels else policy_of(PLAIN)


def job(evaluation, ad, *, quote="Melbourne", **facts):
    return retarget(evaluation, ad, quote, facts={**evaluation.facts.model_dump(), **facts})


def with_blocker(ev, rid, text, quote):
    """One unsupported material requirement plus a separately evidenced skill."""
    h = ev.run_key.ad_hash
    skill = Requirement(id="skill", text="Accounting", tier="stated", importance="high",
                        jd_signal=SourceCitation(source_id="ad", content_hash=h, quote="accounting"))
    req = Requirement(id=rid, text=text, tier="stated", importance="critical", blocker=True,
                      jd_signal=SourceCitation(source_id="ad", content_hash=h, quote=quote))
    cv = SourceCitation(source_id="cv.md", content_hash="1" * 64, quote="Synthetic relevant experience")
    return AgenticEvaluation.model_validate({**ev.model_dump(),
        "requirements": RequirementSet(ad_hash=h, requirements=(skill, req)),
        "matches": (RequirementMatch(requirement_id="skill", match="strong", evidence=(cv,)),
                    RequirementMatch(requirement_id=rid, match="missing", evidence=(),
                                     risk="Unproven", mitigation="Ask the person"))})


FULL_TIME_AD = "Accounting analyst based in Melbourne VIC. Full-time position." + RIGHTS
GRADUATE_AD = "Full-time graduate program in accounting based in Melbourne VIC." + RIGHTS


def test_no_hours_limit_reads_neither_an_employment_label_nor_a_live_profile_limit(evaluation, policy):
    ev = job(evaluation, FULL_TIME_AD, hours="full_time_only", program=False)
    assert outcome(ev, FULL_TIME_AD, policy, policy_of(PLAIN)) == ("draft", "eligible")
    assert outcome(ev, FULL_TIME_AD, policy, None) == ("draft", "eligible")


@pytest.mark.parametrize('label,weekly,expected', [
    ('Full-time', 20, ('draft', 'eligible')),
    ('Full-time', 32, ('archive', 'hard_gate')),
    ('Part-time', 20, ('draft', 'eligible')),
    ('Part-time', 32, ('archive', 'hard_gate')),
])
def test_actual_hours_are_compared_to_the_confirmed_limit(evaluation, policy, label, weekly, expected):
    ad = f"Accounting analyst based in Melbourne VIC. {label}, {weekly} hours per week." + RIGHTS
    dp = policy_of(rights(hours_limit_per_fortnight=40))
    ev = job(evaluation, ad, hours='full_time_only' if label == 'Full-time' else 'part_time_ok', program=False)
    assert outcome(ev, ad, policy, dp) == expected


@pytest.mark.parametrize('ad,program,title', [(FULL_TIME_AD, False, 'Accountant'),
    (GRADUATE_AD, True, 'Graduate Accountant')])
@pytest.mark.parametrize('program_preference', [True, False, None])
def test_material_missing_hours_stay_unknown_even_for_a_wanted_program(evaluation, policy, ad, program, title, program_preference):
    values = {'hours_limit_per_fortnight':40}
    if program_preference is not None:
        values['full_time_programs_ok'] = program_preference
    ev = job(evaluation, ad, hours='full_time_only', program=program)
    assert outcome(ev, ad, policy, policy_of(rights(**values)), title=title) == ('hold', 'insufficient_evidence')


@pytest.mark.parametrize('levels,level,years,expected', [
    (('entry','junior'), 'mid', None, ('archive','hard_gate')),
    (('entry','junior'), 'junior', 4, ('draft','eligible')),
    (('mid',), 'senior', None, ('archive','hard_gate')),
    (('mid',), 'mid', 8, ('draft','eligible')),
    (('senior',), 'senior', 8, ('draft','eligible')),
    ((), 'senior', 8, ('draft','eligible')),
])
def test_confirmed_levels_are_distinct_from_required_years(evaluation, policy, levels, level, years, expected):
    ev = job(evaluation, AD, seniority=level, min_years=years, program=False)
    assert outcome(ev, AD, policy, stated(*levels)) == expected


@pytest.mark.parametrize('wording', ['Requires 4 years experience.', '4 years experience preferred.',
    'Minimum of 5-7 years of professional experience.', 'No previous experience is required.'])
def test_years_wording_has_no_shared_junior_ceiling(evaluation, policy, wording):
    ad = 'Junior accounting analyst based in Melbourne VIC. ' + wording + RIGHTS
    ev = job(evaluation, ad, seniority='junior', min_years=4, program=False)
    assert outcome(ev, ad, policy, stated('junior')) == ('draft','eligible')


def test_material_requirement_gaps_still_hold_independently_of_high_scores(evaluation, policy):
    ev = with_blocker(job(evaluation, AD), 'certification', 'Accounting certification', 'accounting')
    assert outcome(ev, AD, policy, policy_of(PLAIN)) == ('hold','insufficient_evidence')


CITIZENS_AD = 'Graduate accounting analyst based in Melbourne VIC. Australian citizens and permanent residents only.'


@pytest.mark.parametrize('approved,expected', [
    ({'citizen':True}, ('draft','eligible')),
    ({'permanent_resident':True}, ('draft','eligible')),
    ({'citizen_or_pr':True}, ('draft','eligible')),
    ({'citizen':False, 'permanent_resident':False}, ('archive','hard_gate')),
    ({}, ('hold','insufficient_evidence')),
])
def test_citizen_or_pr_requirement_preserves_known_and_unknown_statuses(evaluation, policy, approved, expected):
    ev = job(evaluation, CITIZENS_AD, work_rights={'requirement':'citizen_or_pr',
        'quote':'Australian citizens and permanent residents only'})
    assert outcome(ev, CITIZENS_AD, policy, policy_of(rights(**approved)) if approved else policy_of(PLAIN)) == expected


@pytest.mark.parametrize('approved,expected', [
    ({'citizen':True}, ('draft','eligible')),
    ({'permanent_resident':True}, ('hold','insufficient_evidence')),
    ({'citizen_or_pr':True}, ('hold','insufficient_evidence')),
    ({'citizen':False,'permanent_resident':True}, ('archive','hard_gate')),
    ({}, ('hold','insufficient_evidence')),
])
def test_permanent_residency_never_establishes_citizenship(evaluation, policy, approved, expected):
    ad = 'Graduate accounting analyst based in Melbourne VIC. Australian citizens only.'
    ev = job(evaluation, ad, work_rights={'requirement':'citizen_only','quote':'Australian citizens only'})
    assert outcome(ev, ad, policy, policy_of(rights(**approved)) if approved else policy_of(PLAIN)) == expected


def test_an_unsupported_model_rights_label_does_not_become_a_fact(evaluation, policy):
    ad = 'Graduate accounting analyst based in Melbourne VIC. Eligibility to work is required.'
    ev = job(evaluation, ad, work_rights={'requirement':'citizen_only','quote':'Eligibility to work is required'})
    assert outcome(ev, ad, policy, policy_of(rights(citizen=True))) == ('hold','verification_required')


@pytest.mark.parametrize('sentence', [
    'Candidates must hold a baseline clearance.', 'Baseline security clearance required.',
    'You will need NV1 clearance.', 'Clearance is a prerequisite for this role.',
    'Baseline clearance is compulsory.', 'Applicants will be subject to a security clearance.',
])
def test_actual_clearance_requirements_hold_unknowns_and_respect_confirmed_absence(evaluation, policy, sentence):
    ad = f'Graduate accounting analyst based in Melbourne VIC. {sentence}'
    ev = job(evaluation, ad, work_rights={'requirement':'none_stated','quote':''})
    assert outcome(ev, ad, policy, policy_of(rights(citizen=True))) == ('hold','insufficient_evidence')
    assert outcome(ev, ad, policy, policy_of(rights(citizen=True, clearances=[]))) == ('archive','hard_gate')


@pytest.mark.parametrize('sentence', [
    'No security clearance is required.', 'Baseline security clearance not required.',
    'Join our solar team working on PV systems.', 'Our team will establish baseline metrics.',
    'Customs clearance experience is useful.', 'Vetting of vendors is part of the role.',
    'No security clearance is needed.',
])
def test_clearance_terms_without_a_requirement_add_no_personal_blocker(evaluation, policy, sentence):
    ad = f'Graduate accounting analyst based in Melbourne VIC. {sentence}'
    assert outcome(job(evaluation, ad), ad, policy, policy_of(rights(citizen=True))) == ('draft','eligible')


def test_clearance_and_citizenship_demands_are_independent(evaluation, policy):
    ad = 'Graduate accounting analyst based in Melbourne VIC. Australian citizens only. Baseline security clearance required.'
    ev = job(evaluation, ad, work_rights={'requirement':'citizen_only','quote':'Australian citizens only'})
    assert outcome(ev, ad, policy, policy_of(rights(citizen=True))) == ('hold','insufficient_evidence')
    assert outcome(ev, ad, policy, policy_of(rights(citizen=True, clearances=['BASELINE']))) == ('draft','eligible')
    assert outcome(ev, ad, policy, policy_of(rights(citizen=False, clearances=['BASELINE']))) == ('archive','hard_gate')


def test_explicit_legacy_configuration_cannot_reactivate_donor_rules(evaluation, policy):
    from pipeline.agentic import service
    assert service.decision_policy_mode({'pipeline':{'agentic':{}}}) == 'profile'
    assert service.decision_policy_mode({'pipeline':{'agentic':{'decision_policy':'legacy'}}}) == 'profile'
    assert outcome(job(evaluation, FULL_TIME_AD, hours='full_time_only', seniority='senior', program=False),
                   FULL_TIME_AD, policy, None) == ('draft','eligible')
