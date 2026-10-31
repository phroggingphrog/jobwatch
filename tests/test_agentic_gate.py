"""Frozen historical admission tests, retained to compare intentional policy changes.

These exercise the pre-remediation baseline only. Current active policy is tested
in test_agentic_gate_policy.py and candidate/test_eligibility.py. No runtime path
imports this test fixture or can select the old personal defaults.
"""
import hashlib

import pytest

from jobwatch.candidate.contracts import TargetPolicy
from pipeline.agentic.contracts import (
    AgenticEvaluation, Dimension, RequirementSet, RunKey, SourceCitation,
)
from tests.fixtures.frozen_person_gate_20261022 import decide
from pipeline.schemas import JobFacts


AD = (
    "Graduate accounting analyst role based in Melbourne. Hybrid attendance with two days "
    "in the Melbourne office. Part-time, 24 hours per week. Australian work rights required."
)
AD_HASH = hashlib.sha256(AD.encode("utf-8")).hexdigest()


@pytest.fixture(autouse=True)
def historical_person_settings(monkeypatch, _person_profile):
    from jobwatch.candidate import person
    values = {
        'profile.yaml': {'candidate': {'work_rights': {
            'hours_limit_per_fortnight': 48, 'full_time_programs_ok': True}}},
        'interests_and_criteria.yaml': {'target_roles': {'excluded_families': [
            'customer_service', 'hospitality', 'retail', 'shop_floor', 'engineering',
            'health', 'education', 'trades', 'it', 'sales_marketing', 'other']}},
    }
    monkeypatch.setattr(person, '_yaml', lambda name: values[name])


@pytest.fixture
def policy():
    return TargetPolicy(version="test-v1")


@pytest.fixture
def evaluation():
    run_key = RunKey(
        posting_id=123, ad_hash=AD_HASH, evidence_hash="1" * 64,
        rubric_version="test", config_hash="2" * 64,
    )
    citation = SourceCitation(source_id="ad", content_hash=AD_HASH, quote="Melbourne office")
    return AgenticEvaluation(
        run_key=run_key,
        requirements=RequirementSet(ad_hash=AD_HASH, requirements=()),
        matches=(), archetype="graduate accounting",
        global_score=4.0,
        dimensions={name: Dimension(score=4.0, reason="synthetic") for name in
                    ("cv_match", "north_star", "compensation", "culture", "red_flags")},
        facts=JobFacts(
            real_job=True, role_family="Accounting", duties=["reconcile accounts"],
            required_skills=[], preferred_skills=[], seniority="entry", min_years=None,
            hours="part_time_ok", program=True,
            work_rights={"requirement": "none_stated", "quote": ""},
            screening_questions=[],
        ),
        location_fit="melbourne", location_evidence=citation,
        legitimacy="verified", research_available=False, report={k: "synthetic" for k in "ABCDEFG"},
        screening_questions=(),
    )


def test_valid_verified_entry_program_is_routed_to_draft(evaluation, policy):
    result = decide(evaluation, ad_text=AD, policy=policy)
    assert (result.route, result.reason, result.global_score) == ("draft", "eligible", 4.0)


def test_score_threshold_is_inclusive_at_four(evaluation, policy):
    result = decide(evaluation.model_copy(update={"global_score": 2.99}), ad_text=AD, policy=policy)
    assert (result.route, result.reason) == ("archive", "score_below_threshold")  # bar is 3.0 (owner 2026-10-19)
    low_fit = {**evaluation.dimensions, "north_star": Dimension(score=2.0, reason="synthetic")}
    result = decide(evaluation.model_copy(update={"global_score": 3.0, "dimensions": low_fit}), ad_text=AD, policy=policy)
    assert (result.route, result.reason) == ("archive", "score_below_threshold")  # role fit under 3


def test_incomplete_capture_holds_before_other_rules(evaluation, policy):
    result = decide(evaluation, ad_text=AD, policy=policy, captured_complete=False)
    assert (result.route, result.reason) == ("hold", "insufficient_evidence")


def test_ad_hash_mismatch_holds(evaluation, policy):
    result = decide(evaluation, ad_text=AD + " changed", policy=policy)
    assert (result.route, result.reason) == ("hold", "verification_required")


def test_expected_run_key_mismatch_holds(evaluation, policy):
    other = evaluation.run_key.model_copy(update={"posting_id": 124})
    result = decide(evaluation, ad_text=AD, policy=policy, expected_run_key=other)
    assert (result.route, result.reason) == ("hold", "verification_required")


def test_sponsor_availability_is_not_sponsor_only(evaluation, policy):
    ad = "Graduate accounting role in Melbourne office. Part-time. Sponsorship available."
    h = hashlib.sha256(ad.encode()).hexdigest()
    evaluation = AgenticEvaluation.model_validate({
        **evaluation.model_dump(),
        "run_key": evaluation.run_key.model_copy(update={"ad_hash": h}),
        "requirements": RequirementSet(ad_hash=h, requirements=()),
        "location_evidence": {"source_id": "ad", "content_hash": h, "quote": "Melbourne office"},
        "facts": {**evaluation.facts.model_dump(), "work_rights": {
            "requirement": "valid_work_rights", "quote": "Sponsorship available."}},
    })
    result = decide(evaluation, ad_text=ad, policy=policy)
    assert result.route == "draft"


def test_sponsored_applicants_only_is_blocked(evaluation, policy):
    ad = AD + " Sponsored applicants only."
    h = hashlib.sha256(ad.encode()).hexdigest()
    changed = AgenticEvaluation.model_validate({
        **evaluation.model_dump(),
        "run_key": evaluation.run_key.model_copy(update={"ad_hash": h}),
        "requirements": RequirementSet(ad_hash=h, requirements=()),
        "facts": evaluation.facts.model_dump(),
    })
    result = decide(changed, ad_text=ad, policy=policy)
    assert (result.route, result.reason) == ("archive", "hard_gate")


def test_melbourne_hybrid_passes_but_interstate_onsite_contradiction_archives(evaluation, policy):
    hybrid = decide(evaluation, ad_text=AD, policy=policy)
    interstate = AD + " Sydney office attendance is mandatory onsite."
    h = hashlib.sha256(interstate.encode()).hexdigest()
    changed = AgenticEvaluation.model_validate({
        **evaluation.model_dump(),
        "run_key": evaluation.run_key.model_copy(update={"ad_hash": h}),
        "requirements": RequirementSet(ad_hash=h, requirements=()),
        "location_evidence": {"source_id": "ad", "content_hash": h, "quote": "Melbourne office"},
    })
    blocked = decide(changed, ad_text=interstate, policy=policy)
    assert (hybrid.route, blocked.route, blocked.reason) == ("draft", "archive", "hard_gate")


def test_seniority_and_minimum_years_hard_gate(evaluation, policy):
    for update in ({"seniority": "mid"}, {"min_years": 2}):
        facts = evaluation.facts.model_dump()
        facts.update(update)
        changed = AgenticEvaluation.model_validate({**evaluation.model_dump(), "facts": facts})
        result = decide(changed, ad_text=AD, policy=policy)
        assert (result.route, result.reason) == ("archive", "hard_gate")


def test_full_time_program_exception_and_unstated_hours_hold(evaluation, policy):
    full_ad = "Full-time graduate program in accounting based in Melbourne office."
    full_hash = hashlib.sha256(full_ad.encode()).hexdigest()
    full_payload = evaluation.model_dump()
    full_payload.update({
        "run_key": evaluation.run_key.model_copy(update={"ad_hash": full_hash}),
        "requirements": RequirementSet(ad_hash=full_hash, requirements=()),
        "location_evidence": {"source_id": "ad", "content_hash": full_hash, "quote": "Melbourne office"},
        "facts": {**evaluation.facts.model_dump(), "hours": "full_time_only", "program": True},
    })
    program = AgenticEvaluation.model_validate(full_payload)
    assert decide(program, ad_text=full_ad, policy=policy).route == "draft"
    facts = evaluation.facts.model_dump()
    facts.update(hours="unstated", program=False)
    ad = "Graduate accounting analyst role based in Melbourne. Hybrid attendance in the Melbourne office."
    h = hashlib.sha256(ad.encode()).hexdigest()
    payload = evaluation.model_dump()
    payload.update({
        "run_key": evaluation.run_key.model_copy(update={"ad_hash": h}),
        "requirements": RequirementSet(ad_hash=h, requirements=()),
        "location_evidence": {"source_id": "ad", "content_hash": h, "quote": "Melbourne office"},
        "facts": facts,
    })
    unknown = AgenticEvaluation.model_validate(payload)
    result = decide(unknown, ad_text=ad, policy=policy)
    assert result.route == "draft"  # owner 2026-10-19: unstated hours are flagged on the card, not held


def test_excluded_family_and_uncertain_legitimacy(evaluation, policy):
    facts = evaluation.facts.model_dump()
    facts["role_family"] = "Retail"
    excluded = AgenticEvaluation.model_validate({**evaluation.model_dump(), "facts": facts})
    assert decide(excluded, ad_text=AD, policy=policy).reason == "policy_excluded"
    uncertain = AgenticEvaluation.model_validate({**evaluation.model_dump(), "legitimacy": "uncertain"})
    result = decide(uncertain, ad_text=AD, policy=policy)
    assert result.route == "draft"  # owner 2026-10-19: unverified employer is flagged on the card, not held
    suspicious = AgenticEvaluation.model_validate({**evaluation.model_dump(), "legitimacy": "suspicious"})
    assert (decide(suspicious, ad_text=AD, policy=policy).route) == "hold"


def test_long_ad_tail_with_rights_block_is_checked(evaluation, policy):
    tail = "Applicants must be Australian citizens."
    long_ad = "x" * 9500 + " " + tail
    ad_hash = hashlib.sha256(long_ad.encode("utf-8")).hexdigest()
    changed = AgenticEvaluation.model_validate({
        **evaluation.model_dump(),
        "run_key": evaluation.run_key.model_copy(update={"ad_hash": ad_hash}),
        "requirements": RequirementSet(ad_hash=ad_hash, requirements=()),
        "facts": {
            **evaluation.facts.model_dump(),
            "work_rights": {"requirement": "citizen_only", "quote": tail},
        },
    })
    result = decide(changed, ad_text=long_ad, policy=policy)
    assert (result.route, result.reason) == ("archive", "hard_gate")


def rebound(evaluation, ad, **facts):
    h = hashlib.sha256(ad.encode()).hexdigest()
    return AgenticEvaluation.model_validate({
        **evaluation.model_dump(),
        "run_key": evaluation.run_key.model_copy(update={"ad_hash": h}),
        "requirements": RequirementSet(ad_hash=h, requirements=()),
        "location_evidence": {"source_id": "ad", "content_hash": h, "quote": "Melbourne"},
        "facts": {**evaluation.facts.model_dump(), "program": False, **facts},
    })


@pytest.mark.parametrize("ad,reason,route", [
    ("Accounting analyst based in Melbourne. Part-time.", "eligible", "draft"),  # level not stated: flagged (owner 2026-10-19)
    ("Accounting analyst based in Melbourne. Part-time. This is not an entry-level role.", "insufficient_evidence", "hold"),
    ("Junior accounting analyst based in Melbourne.", "eligible", "draft"),  # unstated hours: flagged, not held (owner 2026-10-19)
    ("Junior accounting analyst based in Melbourne. Full-time only.", "hard_gate", "archive"),
    ("Junior accounting analyst based in Melbourne. Part-time, 32 hours per week.", "hard_gate", "archive"),
    ("Junior accounting analyst based in Melbourne. Part-time. Requires 3 years experience.", "hard_gate", "archive"),
    ("Senior accounting analyst role based in Melbourne. Part-time.", "hard_gate", "archive"),
])
def test_model_cannot_assert_away_unknown_or_contradictory_seniority_hours(evaluation, policy, ad, reason, route):
    changed = rebound(evaluation, ad, hours="part_time_ok", seniority="entry", min_years=None)
    decision = decide(changed, ad_text=ad, policy=policy)
    assert (decision.route, decision.reason) == (route, reason)


def test_entry_compatible_hours_range_is_not_mistaken_for_fulltime(evaluation, policy):
    ad = "Junior accounting analyst in Melbourne. Part-time, 20-24 hours per week."
    assert decide(rebound(evaluation, ad), ad_text=ad, policy=policy).route == "draft"


def test_preferred_experience_does_not_override_entry_level(evaluation, policy):
    ad = "Junior accounting analyst based in Melbourne. Part-time. 3 years experience preferred."
    assert decide(rebound(evaluation, ad), ad_text=ad, policy=policy).route == "draft"


@pytest.mark.parametrize("description", [
    "This is not an entry-level accounting role.",
    "This is an experienced bookkeeping position, rather than an entry-level accounting role.",
    "This is not a junior role.",
    "This position is not suitable for entry-level applicants.",
    "This position is not suitable for an entry-level applicant.",
    "This position is not suitable for a junior applicant.",
    "This is not an entry-level or junior role.",
])
def test_negated_entry_wording_is_not_positive_evidence(evaluation, policy, description):
    ad = "Accounting role in Melbourne. Part-time, 15 hours per week. " + description
    decision = decide(rebound(evaluation, ad, seniority="entry", min_years=None),
                      ad_text=ad, policy=policy)
    assert (decision.route, decision.reason) == ("hold", "insufficient_evidence")


@pytest.mark.parametrize("description", [
    "Prior experience is not required. Junior applicants welcome.",
    "This is not a senior role; entry-level applicants welcome.",
    "No previous experience is required.",
    "Not only junior applicants are welcome.",
])
def test_unrelated_negation_preserves_positive_entry_evidence(evaluation, policy, description):
    ad = "Accounting role in Melbourne. Part-time, 15 hours per week. " + description
    assert decide(rebound(evaluation, ad), ad_text=ad, policy=policy).route == "draft"


def unverified_blocker(evaluation, ad, *, match="missing"):
    from pipeline.agentic.contracts import Requirement, RequirementMatch
    h = hashlib.sha256(ad.encode()).hexdigest()
    req = Requirement(id="r1", text="Pre-employment check", tier="stated", importance="critical", blocker=True,
                      jd_signal=SourceCitation(source_id="ad", content_hash=h, quote="accounting"))
    evidence = () if match == "missing" else (SourceCitation(
        source_id="cv.md", content_hash="1" * 64, quote="Synthetic relevant experience"),)
    return AgenticEvaluation.model_validate({**evaluation.model_dump(), "global_score": 5.0,
        "requirements": RequirementSet(ad_hash=h, requirements=(req,)),
        "matches": (RequirementMatch(requirement_id="r1", match=match, evidence=evidence,
                     risk="Status unproven", mitigation="Confirm status with owner"),)})


@pytest.mark.parametrize("match", ["missing", "partial"])
def test_unverified_employer_blocker_holds_even_with_high_score(evaluation, policy, match):
    changed = unverified_blocker(evaluation, AD, match=match)
    result = decide(changed, ad_text=AD, policy=policy)
    assert (result.route, result.reason) == ("hold", "insufficient_evidence")


@pytest.mark.parametrize("suffix", [
    " Applicants must be Australian citizens.",
    " Sponsored applicants only.",
    " Sydney office attendance is mandatory onsite.",
    " Requires 3 years experience.",
    " Part-time, 32 hours per week.",
])
def test_unverified_blocker_does_not_mask_confirmed_policy_exclusion(evaluation, policy, suffix):
    ad = AD + suffix
    changed = unverified_blocker(rebound(evaluation, ad), ad)
    result = decide(changed, ad_text=ad, policy=policy)
    assert (result.route, result.reason) == ("archive", "hard_gate")


def test_ad_quote_cannot_pass_as_candidate_proof_at_gate(evaluation, policy):
    from pipeline.agentic.contracts import Requirement, RequirementMatch
    citation = SourceCitation(source_id="ad", content_hash=AD_HASH, quote="accounting")
    changed = AgenticEvaluation.model_validate({**evaluation.model_dump(),
        "requirements": RequirementSet(ad_hash=AD_HASH, requirements=(Requirement(
            id="r1", text="accounting", tier="stated", importance="high", jd_signal=citation),)),
        "matches": (RequirementMatch(requirement_id="r1", match="strong", evidence=(citation,)),)})
    result = decide(changed, ad_text=AD, policy=policy)
    assert (result.route, result.reason) == ("hold", "verification_required")


@pytest.mark.parametrize("quote,route", [
    ("Fully remote", "hold"), ("Fully remote anywhere in Australia", "draft"),
    ("Fully remote, US residents only", "archive"),
])
def test_remote_location_requires_access_from_candidate_location(evaluation, policy, quote, route):
    ad = f"Junior accounting analyst. Part-time, 24 hours per week. {quote}."
    changed = rebound(evaluation, ad).model_copy(update={
        "location_fit": "remote_accessible", "location_evidence": SourceCitation(
            source_id="ad", content_hash=hashlib.sha256(ad.encode()).hexdigest(), quote=quote)})
    # A known outside restriction is a hard failure even if the model called it accessible.
    assert decide(changed, ad_text=ad, policy=policy).route == route


def test_high_score_without_any_candidate_match_cannot_draft(evaluation, policy):
    from pipeline.agentic.contracts import Requirement, RequirementMatch
    req = Requirement(id="r1", text="Accounting", tier="stated", importance="high",
                      jd_signal=SourceCitation(source_id="ad", content_hash=AD_HASH, quote="accounting"))
    changed = AgenticEvaluation.model_validate({**evaluation.model_dump(), "global_score": 5.0,
        "requirements": RequirementSet(ad_hash=AD_HASH, requirements=(req,)),
        "matches": (RequirementMatch(requirement_id="r1", match="missing", evidence=(),
                     risk="Unproven", mitigation="Ask owner"),)})
    assert decide(changed, ad_text=AD, policy=policy).route == "hold"


@pytest.mark.parametrize('location', [
    'Clayton, VIC, AU, 3168', 'Berwick, VIC, AU, 3806', 'Wantirna, VIC, AU, 3152',
    'Hawthorn East VIC', 'Footscray, Victoria', 'Location: Box Hill, VIC 3128',
    'Join us in our Melbourne office', 'Work with us in Melbourne',
    'Based in Melbourne, you will act as an analyst',
])
def test_cited_verified_metro_locality_can_pass_without_word_melbourne(evaluation, policy, location):
    ad = f'Junior accounting analyst. Part-time, 24 hours per week. Location: {location}.'
    changed = rebound(evaluation, ad)
    changed = changed.model_copy(update={'location_evidence': SourceCitation(
        source_id='ad', content_hash=changed.run_key.ad_hash, quote=location)})
    decision = decide(changed, ad_text=ad, policy=policy)
    assert (decision.route, decision.reason) == ('draft', 'eligible')


# Owner 2026-10-12: "just focus on Victoria" - regional Victoria (Geelong, Little River, Hillside) is in scope;
# another state or country, or a bare place name with no state, is not.
@pytest.mark.parametrize('location', [
    'Clayton', 'Clayton, NSW', 'Clayton, VIC, USA', 'Clayton, VIC, NSW', 'Melbourne, Florida',
    'Melbourne, VIC, US', 'Melbourne, us', 'Melbourne, ACT', 'Melbourne, act',
])
def test_unproven_or_conflicting_location_cannot_pass_on_model_label(evaluation, policy, location):
    ad = f'Junior accounting analyst. Part-time, 24 hours per week. Location: {location}.'
    changed = rebound(evaluation, ad)
    changed = changed.model_copy(update={'location_evidence': SourceCitation(
        source_id='ad', content_hash=changed.run_key.ad_hash, quote=location)})
    decision = decide(changed, ad_text=ad, policy=policy)
    assert decision.route == 'hold'


@pytest.mark.parametrize('title,body,claimed,expected',[
    ('Accounting, Controls & Cash Flow Intern','Full time',True,True),
    ('Internal Accountant','Full time',True,False),
    ('Accountant','Supervise an intern. Full time',True,False),
    ('Accounting Intern','Full time',False,False),
])
def test_intern_title_confirms_claimed_program_without_substring_or_duties_false_positive(title,body,claimed,expected):
    from tests.fixtures.frozen_person_gate_20261022 import _is_program
    assert _is_program(title,body,claimed) is expected


@pytest.mark.parametrize('condition,blocker,score,route,reason', [
    ('The successful candidate will be required to complete national police and bankruptcy checks.',
     False, 4.2, 'draft', 'eligible'),
    ('The successful candidate will be required to complete national police and bankruptcy checks.',
     False, 2.8, 'archive', 'score_below_threshold'),  # bar is 3.0 since 2026-10-19
    ('Applicants must already hold a current police check.',
     True, 4.2, 'hold', 'insufficient_evidence'),
    ('A satisfactory police check is essential.',
     True, 4.2, 'hold', 'insufficient_evidence'),
])
def test_check_timing_preserves_unknowns_and_existing_admission_rules(
        evaluation, policy, condition, blocker, score, route, reason):
    from pipeline.agentic.contracts import Requirement, RequirementMatch
    ad = AD + ' ' + condition
    base = rebound(evaluation, ad)
    h = base.run_key.ad_hash
    requirements = (
        Requirement(id='skill', text='Accounting', tier='stated', importance='high',
                    jd_signal=SourceCitation(source_id='ad', content_hash=h, quote='accounting')),
        Requirement(id='check', text=condition, tier='stated', importance='critical', blocker=blocker,
                    jd_signal=SourceCitation(source_id='ad', content_hash=h, quote=condition)),
    )
    matches = (
        RequirementMatch(requirement_id='skill', match='strong', evidence=(SourceCitation(
            source_id='cv.md', content_hash='1'*64, quote='Synthetic relevant experience'),)),
        RequirementMatch(requirement_id='check', match='missing', evidence=(),
                         risk='Completion and consent unresolved', mitigation='Owner review required'),
    )
    changed = AgenticEvaluation.model_validate({**base.model_dump(), 'global_score': score,
        'requirements': RequirementSet(ad_hash=h, requirements=requirements), 'matches': matches})
    result = decide(changed, ad_text=ad, policy=policy)
    assert (result.route, result.reason) == (route, reason)
    assert changed.matches[1].match == 'missing' and changed.matches[1].evidence == ()


def test_melbourne_suburb_named_in_a_sentence_or_list_counts():
    from pipeline.agentic.location import cited_melbourne_location as melbourne
    assert melbourne("Based in Glen Iris, Victoria")
    assert melbourne("Located in Box Hill, Epworth Eastern is a state-of-the-art facility")
    assert melbourne("Melbourne, VIC; Sydney, NSW")
    assert not melbourne("Based in Box Hill, NSW")
    assert not melbourne("experience in Research and analysis")
    assert not melbourne("Based out of our Bacchus Marsh quarry")


@pytest.mark.parametrize('location', ['Geelong, VIC', 'Little River, VIC', 'Clayton VIC or Geelong VIC',
                                      'Hillside, VIC', 'Based out of our Bacchus Marsh quarry',
                                      'our vibrant Preston Support Office four days a week',
                                      'Lyndhurst Primary School (LPS) is located in the outer-south eastern suburb '
                                      'of Lyndhurst in the City of Casey.'])
def test_regional_victoria_is_in_scope(location):
    from pipeline.agentic.location import cited_victoria_location, km_from_home
    assert cited_victoria_location(location)
    assert km_from_home("Glen Iris, Melbourne VIC", "brunswick") == 13


def test_suburb_of_a_queensland_city_is_not_a_victorian_place():
    from pipeline.agentic.location import cited_victoria_location
    assert not cited_victoria_location('Beenleigh, a suburb of Logan City.')
    assert cited_victoria_location('Lyndhurst Primary School is in the outer-south eastern suburb of Lyndhurst in the City of Casey.')


def test_program_where_you_nominate_your_office_is_in_scope(evaluation, policy):
    ad = ("2026/27 Vacationer (Intern) Program. Graduate program for entry students. Location of this job: "
          "nominate your KPMG office location during the application process. Part-time study load welcome.")
    h = hashlib.sha256(ad.encode()).hexdigest()
    changed = AgenticEvaluation.model_validate({
        **evaluation.model_dump(), "run_key": evaluation.run_key.model_copy(update={"ad_hash": h}),
        "requirements": RequirementSet(ad_hash=h, requirements=()), "location_fit": "unknown",
        "location_evidence": {"source_id": "ad", "content_hash": h,
                              "quote": "nominate your KPMG office location during the application process."}})
    assert decide(changed, ad_text=ad, title="2026/27 KPMG Vacationer (Intern) Program", policy=policy).route == "draft"
    plain = changed.model_copy(update={"facts": changed.facts.model_copy(update={"program": False})})
    assert decide(plain, ad_text=ad, title="Accounts officer", policy=policy).route == "hold"


def test_unknown_family_is_read_from_the_archetype():
    from tests.fixtures.frozen_person_gate_20261022 import _family_from_archetype
    assert _family_from_archetype("Vacation/intern program — Tax / Graduate Accountant + Data Analyst", True) == "finance_program"
    assert _family_from_archetype("Accounts & Administration", False) == "back_office_admin"
    assert _family_from_archetype("Barista", False) == "unknown"


def test_ad_inviting_visa_holders_is_not_a_citizenship_requirement():
    from jobwatch.reader import rights_backstop
    welcome = ("Casual data entry clerk. If you are not a citizen or permanent resident please provide details of your "
               "visa type, expiry date, and working hours restrictions if any.")
    assert rights_backstop(welcome) is None
    assert rights_backstop("Applicants must be Australian citizens or permanent residents.") is not None


@pytest.mark.parametrize("title,ad,exempt", [
    ("Graduate Accountant - 2027", "Full-time role starting February 2027.", True),
    ("Summer Vacationer - Audit", "Full-time over the summer break.", True),
    ("Accounts Officer", "Join our 2027 graduate program. Full-time.", True),
    ("Finance Intern", "Full-time, 38 hours per week.", False),
    ("Office Coordinator Trainee", "Full-time traineeship.", False),
])
def test_only_graduate_and_vacation_roles_bypass_full_time(title, ad, exempt):
    from tests.fixtures.frozen_person_gate_20261022 import _full_time_exempt
    assert _full_time_exempt(title, ad) is exempt


def test_graduate_and_vacation_roles_draft_from_3_5(evaluation, policy):
    ad = "Full-time graduate program in accounting based in Melbourne office."
    h = hashlib.sha256(ad.encode()).hexdigest()
    payload = evaluation.model_dump()
    payload.update({
        "run_key": evaluation.run_key.model_copy(update={"ad_hash": h}),
        "requirements": RequirementSet(ad_hash=h, requirements=()),
        "location_evidence": {"source_id": "ad", "content_hash": h, "quote": "Melbourne office"},
        "facts": {**evaluation.facts.model_dump(), "hours": "full_time_only", "program": True},
        "global_score": 3.5,
    })
    grad = AgenticEvaluation.model_validate(payload)
    assert decide(grad, ad_text=ad, title="Graduate Accountant - 2027", policy=policy).route == "draft"
    assert decide(grad, ad_text=ad.replace("graduate program", "role"), title="Accountant",
                  policy=policy).route != "draft"


@pytest.mark.parametrize("text,general", [
    ("Right to work in Australia", True),
    ("Valid working rights / visa for Australia", True),
    ("Australian citizenship or permanent residency", False),
    ("Must hold a baseline security clearance", False),
])
def test_general_work_rights_excludes_citizenship_pr_and_clearance(text, general):
    from types import SimpleNamespace
    from tests.fixtures.frozen_person_gate_20261022 import _general_work_rights
    assert _general_work_rights(SimpleNamespace(id="req", text=text, jd_signal=None)) is general


@pytest.mark.parametrize("rid,text,exempt,expected", [
    ("application_documents", "Submit a resume and cover letter", False, True),
    ("location", "Based in our Southbank office, hybrid after six months", False, True),
    ("full_time", "Full-time position", True, True),
    ("full_time", "Full-time position", False, False),
    ("screen_work_rights", "Right to work in Australia", True, False),
    ("degree", "Completed accounting degree", True, False),
    ("future_checks", "Police check before employment", True, False),
])
def test_logistics_requirements_never_hold_a_job(rid, text, exempt, expected):
    from types import SimpleNamespace
    from tests.fixtures.frozen_person_gate_20261022 import _logistics
    assert _logistics(SimpleNamespace(id=rid, text=text, jd_signal=None), exempt) is expected


def test_commute_home_follows_the_current_person_not_the_first_one_cached(tmp_path, monkeypatch):
    from jobwatch import users
    from jobwatch.candidate import approved
    from pipeline.agentic.location import km_from_home
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path)); monkeypatch.delenv('JOBWATCH_PROFILE_DIR', raising=False)
    locations = {'owner': 'Brunswick, VIC', 'bob': 'Geelong, VIC'}
    monkeypatch.setattr(approved, 'settings', lambda person, name: {'candidate': {'location': locations[person]}})
    with users.use('owner'):
        near = km_from_home('Glen Iris, Melbourne VIC')
    with users.use('bob'):
        far = km_from_home('Glen Iris, Melbourne VIC')
    assert near == 13 and far is not None and far > 50  # a second person must not inherit the first person's home
