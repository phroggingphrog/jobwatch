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


def test_nominate_your_office_program_is_open_to_the_persons_region(evaluation, policy):
    ad = "Graduate program. Nominate your office location when you apply." + RIGHTS
    ev = retarget(evaluation, ad, "Nominate your office location when you apply", location_fit="unknown")
    assert outcome(ev, ad, policy, policy_of(VIC)) == ("draft", "eligible")


def test_non_australia_only_ads_are_archived(evaluation, policy):
    ad = MELBOURNE_AD + " US residents only."
    ev = retarget(evaluation, ad, "Melbourne VIC")
    assert outcome(ev, ad, policy, policy_of(VIC)) == ("archive", "hard_gate")


def test_commute_limit_comes_only_from_the_policy(evaluation, policy):
    dp30 = policy_of(fact("constraint", "no more than 30 km commute"), VIC)
    dp_none = policy_of(VIC)
    assert outcome(evaluation, AD, policy, dp30, commute_km=40) == ("archive", "hard_gate")
    assert outcome(evaluation, AD, policy, dp30, commute_km=25) == ("draft", "eligible")
    assert outcome(evaluation, AD, policy, dp30) == ("draft", "eligible")   # distance unknown never archives
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


def test_allowed_families_and_live_exclusions_are_not_consulted_on_the_policy_path(evaluation, policy):
    only_acc = TargetPolicy(version="t", allowed_families=("accounting",))
    ev = evaluation.model_copy(update={"facts": evaluation.facts.model_copy(update={"role_family": "engineering"})})
    # The autouse live profile excludes engineering; the legacy path would archive this.
    assert outcome(ev, AD, only_acc, policy_of(VIC)) == ("draft", "eligible")
    assert outcome(ev, AD, only_acc, None) == ("archive", "policy_excluded")


def test_policy_path_reads_no_profile_files_or_victoria_constants(evaluation, policy, monkeypatch):
    def boom(name):
        def raiser(*a, **k):
            raise AssertionError(name)
        return raiser
    for name in ("hours_limit_per_fortnight", "full_time_programs_ok", "excluded_families", "cited_victoria_location"):
        monkeypatch.setattr(gate, name, boom(name))
    assert outcome(evaluation, AD, policy, policy_of(VIC)) == ("draft", "eligible")


def test_wrong_input_types_raise_the_fixed_code(evaluation, policy):
    for kwargs in ({"decision_policy": "not a policy"}, {"company": 7}):
        with pytest.raises(AgenticError) as caught:
            decide(evaluation, ad_text=AD, policy=policy, **kwargs)
        assert str(caught.value) == "invalid_gate_input"


def test_company_defaults_to_empty_and_none_policy_is_legacy(evaluation, policy):
    assert outcome(evaluation, AD, policy, None) == ("draft", "eligible")


# ----------------------------------------------------------------------------- hours, work rights and level (Task 5)
from pipeline.agentic.contracts import Requirement, RequirementMatch, SourceCitation  # noqa: E402

PLAIN = fact("experience", "x")                        # a policy with nothing in it
LOCATION_QUOTE = "Melbourne"


def rights(**value):
    return fact("work_rights", value)


def stated(*levels):
    """A policy whose person states these levels (the policy reads 'mid' only as 'mid-level')."""
    # A person who writes only "mid" gets no stated level, because the policy reads "mid-level" only.
    words = ["mid-level" if level == "mid" else level for level in levels]
    return policy_of(fact("preference", {"seniority": words})) if levels else policy_of(PLAIN)


def job(evaluation, ad, *, quote=LOCATION_QUOTE, **facts):
    """The fixture evaluation for `ad` with some facts replaced; the cited location is `quote`."""
    return retarget(evaluation, ad, quote, facts={**evaluation.facts.model_dump(), **facts})


def with_blocker(ev, rid, text, quote):
    """`ev` plus one blocker requirement that is not met (match 'missing'), quoting the ad, and one strong skill match
    so that the job has candidate evidence."""
    h = ev.run_key.ad_hash
    skill = Requirement(id="skill", text="Accounting", tier="stated", importance="high",
                        jd_signal=SourceCitation(source_id="ad", content_hash=h, quote="accounting"))
    req = Requirement(id=rid, text=text, tier="stated", importance="critical", blocker=True,
                      jd_signal=SourceCitation(source_id="ad", content_hash=h, quote=quote))
    cv = SourceCitation(source_id="cv.md", content_hash="1" * 64, quote="Synthetic relevant experience")
    return AgenticEvaluation.model_validate({
        **ev.model_dump(), "global_score": 5.0,
        "requirements": RequirementSet(ad_hash=h, requirements=(skill, req)),
        "matches": (RequirementMatch(requirement_id="skill", match="strong", evidence=(cv,)),
                    RequirementMatch(requirement_id=rid, match="missing", evidence=(),
                                     risk="Unproven", mitigation="Ask the person"))})


FULL_TIME_AD = "Accounting analyst based in Melbourne VIC. Full-time position." + RIGHTS
GRADUATE_AD = "Full-time graduate program in accounting based in Melbourne VIC." + RIGHTS


def test_no_hours_limit_never_archives_on_hours(evaluation, policy):
    # The autouse live profile has a 48 hour limit; a policy that sets none must ignore it.
    ev = job(evaluation, FULL_TIME_AD, hours="full_time_only", program=False)
    assert outcome(ev, FULL_TIME_AD, policy, policy_of(PLAIN)) == ("draft", "eligible")
    long_ad = "Accounting analyst based in Melbourne VIC. Part-time, 32 hours per week." + RIGHTS
    assert outcome(job(evaluation, long_ad, program=False), long_ad, policy, policy_of(PLAIN)) == ("draft", "eligible")
    # The same ad on the legacy path still meets the live limit.
    assert outcome(ev, FULL_TIME_AD, policy, None) == ("archive", "hard_gate")


def test_hours_limit_from_policy_archives_full_time_only(evaluation, policy):
    limit = policy_of(fact("work_rights", "work rights up to 40 hours per fortnight"))
    assert limit.work_rights["hours_limit_per_fortnight"] == 40
    ev = job(evaluation, FULL_TIME_AD, hours="full_time_only", program=False)
    assert outcome(ev, FULL_TIME_AD, policy, limit) == ("archive", "hard_gate")
    # Hours stated in the ad beyond half the fortnight limit per week also archive; within it they do not.
    over = "Accounting analyst based in Melbourne VIC. Part-time, 32 hours per week." + RIGHTS
    assert outcome(job(evaluation, over, program=False), over, policy, limit) == ("archive", "hard_gate")
    within = "Accounting analyst based in Melbourne VIC. Part-time, 20 hours per week." + RIGHTS
    assert outcome(job(evaluation, within, program=False), within, policy, limit) == ("draft", "eligible")


def test_graduate_exemption_needs_the_policy_to_allow_it(evaluation, policy):
    ev = job(evaluation, GRADUATE_AD, hours="full_time_only", program=True)
    allowed = policy_of(rights(hours_limit_per_fortnight=40, full_time_programs_ok=True))
    not_allowed = policy_of(rights(hours_limit_per_fortnight=40, full_time_programs_ok=False))
    unsaid = policy_of(rights(hours_limit_per_fortnight=40))
    assert outcome(ev, GRADUATE_AD, policy, allowed, title="Graduate Accountant") == ("draft", "eligible")
    assert outcome(ev, GRADUATE_AD, policy, not_allowed, title="Graduate Accountant") == ("archive", "hard_gate")
    assert outcome(ev, GRADUATE_AD, policy, unsaid, title="Graduate Accountant") == ("archive", "hard_gate")
    # The exemption is for graduate and vacation roles only.
    plain = job(evaluation, FULL_TIME_AD, hours="full_time_only", program=False)
    assert outcome(plain, FULL_TIME_AD, policy, allowed, title="Accountant") == ("archive", "hard_gate")


@pytest.mark.parametrize("stated_levels,ad_level,title,years,expect", [
    (("entry", "junior"), "mid", "Accountant", None, ("archive", "hard_gate")),
    (("entry", "junior"), "entry", "Accountant", 3, ("archive", "hard_gate")),
    (("mid",), "senior", "Accountant", None, ("archive", "hard_gate")),
    (("mid",), "mid", "Senior Accountant", None, ("archive", "hard_gate")),
    (("mid",), "mid", "Accountant", 3, ("draft", "eligible")),
    (("senior",), "senior", "Senior Accountant", 8, ("draft", "eligible")),
    ((), "senior", "Senior Accountant", 8, ("draft", "eligible")),
])
def test_seniority_follows_the_levels_the_person_stated(evaluation, policy, stated_levels, ad_level, title, years, expect):
    dp = stated(*stated_levels)
    assert dp.seniority == stated_levels
    ev = job(evaluation, AD, seniority=ad_level, min_years=years, program=False)
    assert outcome(ev, AD, policy, dp, title=title) == expect


def test_years_stated_in_the_ad_count_only_for_a_junior_or_lower_seeker(evaluation, policy):
    ad = "Accounting analyst based in Melbourne VIC. Requires 3 years experience." + RIGHTS
    ev = job(evaluation, ad, program=False)
    assert outcome(ev, ad, policy, stated("entry", "junior")) == ("archive", "hard_gate")
    assert outcome(ev, ad, policy, stated("junior")) == ("archive", "hard_gate")
    assert outcome(ev, ad, policy, stated("mid")) == ("draft", "eligible")
    assert outcome(ev, ad, policy, stated()) == ("draft", "eligible")
    preferred = "Accounting analyst based in Melbourne VIC. 3 years experience preferred." + RIGHTS
    assert outcome(job(evaluation, preferred, program=False), preferred, policy, stated("entry")) == ("draft", "eligible")
    one = "Accounting analyst based in Melbourne VIC. Requires 1 year of experience." + RIGHTS
    assert outcome(job(evaluation, one, program=False), one, policy, stated("entry")) == ("draft", "eligible")


def test_a_senior_title_in_the_ad_text_raises_the_ad_level(evaluation, policy):
    ad = "We are hiring a senior accountant to join the Melbourne office." + RIGHTS
    ev = job(evaluation, ad, seniority="entry", program=False)
    assert outcome(ev, ad, policy, stated("entry", "junior")) == ("archive", "hard_gate")
    assert outcome(ev, ad, policy, stated("mid")) == ("archive", "hard_gate")
    assert outcome(ev, ad, policy, stated("senior")) == ("draft", "eligible")


def test_entry_seeker_holds_when_ad_says_not_entry_level(evaluation, policy):
    ad = "Accounting analyst based in Melbourne VIC. This is not an entry-level role." + RIGHTS
    ev = job(evaluation, ad, seniority="entry", min_years=None, program=False)
    for levels in (("entry",), ("junior",), ("entry", "junior")):
        assert outcome(ev, ad, policy, stated(*levels)) == ("hold", "insufficient_evidence")
    assert outcome(ev, ad, policy, stated()) == ("draft", "eligible")           # no stated level: no level rule
    assert outcome(ev, ad, policy, stated("mid")) == ("draft", "eligible")       # the rule is for junior or lower
    positive = "Junior accounting analyst based in Melbourne VIC. Not a senior role." + RIGHTS
    assert outcome(job(evaluation, positive, program=False), positive, policy, stated("entry")) == ("draft", "eligible")


CITIZENS_AD = "Graduate accounting analyst based in Melbourne VIC. Australian citizens and permanent residents only."
CITIZEN_FACTS = {"work_rights": {"requirement": "citizen_or_pr",
                                 "quote": "Australian citizens and permanent residents only"}}


def test_citizen_or_pr_person_is_not_blocked_by_a_plain_citizenship_demand(evaluation, policy):
    ev = job(evaluation, CITIZENS_AD, **CITIZEN_FACTS)
    assert outcome(ev, CITIZENS_AD, policy, policy_of(rights(citizen_or_pr=True))) == ("draft", "eligible")
    assert outcome(ev, CITIZENS_AD, policy, policy_of(rights(citizen_or_pr=False))) == ("archive", "hard_gate")
    assert outcome(ev, CITIZENS_AD, policy, policy_of(PLAIN)) == ("archive", "hard_gate")
    assert outcome(ev, CITIZENS_AD, policy, None) == ("archive", "hard_gate")     # legacy, as today
    # The model's label alone (no regex hit in the ad) holds for everyone but a citizen.
    soft = "Graduate accounting analyst based in Melbourne VIC. Eligibility to work is required."
    label = job(evaluation, soft, work_rights={"requirement": "citizen_or_pr", "quote": "Eligibility to work is required"})
    assert outcome(label, soft, policy, policy_of(rights(citizen_or_pr=True))) == ("draft", "eligible")
    assert outcome(label, soft, policy, policy_of(rights(citizen_or_pr=False))) == ("hold", "verification_required")


@pytest.mark.parametrize("requirement", ["citizen_only", "unrestricted_work_rights"])
def test_citizen_is_not_blocked_by_other_citizenship_or_unrestricted_labels(evaluation, policy, requirement):
    ad = "Graduate accounting analyst based in Melbourne VIC. Applicants must have unrestricted work rights in Australia."
    ev = job(evaluation, ad, work_rights={"requirement": requirement,
                                          "quote": "must have unrestricted work rights in Australia"})
    assert outcome(ev, ad, policy, policy_of(rights(citizen_or_pr=True))) == ("draft", "eligible")
    assert outcome(ev, ad, policy, policy_of(rights(citizen_or_pr=False)))[0] != "draft"


@pytest.mark.parametrize("ad,facts", [
    ("Graduate accounting analyst based in Melbourne VIC. Baseline security clearance required.",
     {"requirement": "clearance", "quote": "Baseline security clearance required"}),
    ("Graduate accounting analyst based in Melbourne VIC. Baseline security clearance required.",
     {"requirement": "none_stated", "quote": ""}),                      # the model missed it; the rule did not
    ("Graduate accounting analyst based in Melbourne VIC. Australian citizens only. Baseline security clearance required.",
     {"requirement": "citizen_only", "quote": "Australian citizens only"}),   # the clearance is the second sentence
    ("Graduate accounting analyst based in Melbourne VIC. Applicants must hold an NV1 clearance.",
     {"requirement": "clearance", "quote": "hold an NV1 clearance"}),
])
def test_security_clearance_still_stops_a_citizen(evaluation, policy, ad, facts):
    ev = job(evaluation, ad, work_rights=facts)
    route, reason = outcome(ev, ad, policy, policy_of(rights(citizen_or_pr=True)))
    assert route != "draft" and reason in {"hard_gate", "verification_required"}


def test_a_clearance_label_without_a_quote_still_holds_a_citizen(evaluation, policy):
    ad = "Graduate accounting analyst based in Melbourne VIC. Some roles need further checks."
    ev = job(evaluation, ad, work_rights={"requirement": "clearance", "quote": "further checks"})
    assert outcome(ev, ad, policy, policy_of(rights(citizen_or_pr=True))) == ("hold", "verification_required")


def test_hours_and_program_exemption_come_from_the_policy_not_live_readers(evaluation, policy, monkeypatch):
    """Task 4 review (IMPORTANT): the shared section of decide must not read the profile when a policy is set."""
    def boom(name):
        def raiser(*a, **k):
            raise AssertionError(name)
        return raiser
    for name in ("hours_limit_per_fortnight", "full_time_programs_ok"):
        monkeypatch.setattr(gate, name, boom(name))
    ev = with_blocker(retarget(evaluation, AD, "Melbourne office"), "pre_check", "Pre-employment check", "accounting")
    # A non-strong blocker sends decide through the full-time exemption; a policy with no hours limit must not read a file.
    assert outcome(ev, AD, policy, policy_of(PLAIN)) == ("hold", "insufficient_evidence")

    # The exemption that makes a 'full time' blocker pure logistics comes from the policy's own values.
    ft = with_blocker(job(evaluation, GRADUATE_AD, hours="full_time_only", program=True),
                      "full_time", "Full-time position", "Full-time")
    allowed = policy_of(rights(hours_limit_per_fortnight=40, full_time_programs_ok=True))
    not_allowed = policy_of(rights(hours_limit_per_fortnight=40, full_time_programs_ok=False))
    assert outcome(ft, GRADUATE_AD, policy, allowed, title="Graduate Accountant") == ("draft", "eligible")
    assert outcome(ft, GRADUATE_AD, policy, not_allowed, title="Graduate Accountant")[0] == "archive"


def test_legacy_path_still_reads_the_live_profile_for_the_exemption(evaluation, policy):
    ft = with_blocker(job(evaluation, GRADUATE_AD, hours="full_time_only", program=True),
                      "full_time", "Full-time position", "Full-time")
    assert outcome(ft, GRADUATE_AD, policy, None, title="Graduate Accountant") == ("draft", "eligible")   # live: limit 48, ok


@pytest.mark.parametrize("title,ad,entry,senior_title,years", [
    ("", "Accounting analyst based in Melbourne. Part-time.", False, False, None),
    ("", "Accounting analyst based in Melbourne. Part-time. This is not an entry-level role.", False, False, None),
    ("", "Junior accounting analyst based in Melbourne.", True, False, None),
    ("", "Junior accounting analyst based in Melbourne. Part-time. Requires 3 years experience.", True, False, 3),
    ("", "Senior accounting analyst role based in Melbourne. Part-time.", False, True, None),
    ("", "Junior accounting analyst based in Melbourne. Part-time. 3 years experience preferred.", True, False, None),
    ("", "Accounting role in Melbourne. Prior experience is not required. Junior applicants welcome.", True, False, None),
    ("", "Accounting role in Melbourne. This is not a senior role; entry-level applicants welcome.", True, False, None),
    ("", "Accounting role in Melbourne. No previous experience is required.", True, False, None),
    ("Senior Accountant", "Accountant role in Melbourne.", False, True, None),
    ("", "Graduate accounting analyst role based in Melbourne. Part-time, 24 hours per week.", True, False, None),
    ("", "Accounting role in Melbourne. Minimum of 5-7 years of professional experience.", False, False, 5),
    ("", "Accounting role in Melbourne. 1 year of experience.", False, False, 1),
    ("", "We are hiring a senior accountant. Requires 2 years experience.", False, True, 2),
])
def test_legacy_helpers_keep_their_results(title, ad, entry, senior_title, years):
    # The old _entry_signals returned (entry, senior) with senior = senior wording or a required 2+ years.
    assert gate._level_signals(title, ad) == (entry, senior_title, years)
    assert gate.ENTRY_MAX_YEARS == 2


def test_hours_signals_take_the_limit_from_the_caller():
    assert gate._hours_signals("32 hours per week.", 48) == (False, True)
    assert gate._hours_signals("Part-time, 20 hours per week.", 48) == (True, False)
    assert gate._hours_signals("Full-time, 38 hours per week.", None) == (False, False)
    assert gate._hours_signals("Full-time role.", 40) == (False, True)


def test_a_clearance_sentence_archives_a_citizen_wherever_it_appears(evaluation, policy):
    citizen = policy_of(rights(citizen_or_pr=True))
    many = " ".join(["Australian citizens only."] * 9)
    ad = f"Graduate accounting analyst based in Melbourne VIC. {many} Baseline security clearance required."
    assert outcome(job(evaluation, ad), ad, policy, citizen) == ("archive", "hard_gate")
    # A citizenship phrase in the title does not hide a clearance in the body.
    body = "Graduate accounting analyst based in Melbourne VIC. Baseline security clearance required."
    assert outcome(job(evaluation, body), body, policy, citizen,
                   title="Australian citizens only analyst") == ("archive", "hard_gate")
    # A clearance in the title archives too.
    plain = "Graduate accounting analyst based in Melbourne VIC."
    assert outcome(job(evaluation, plain), plain, policy, citizen,
                   title="Analyst, NV1 clearance") == ("archive", "hard_gate")
    # Citizenship alone, in the title or the body, is met.
    assert outcome(job(evaluation, plain), plain, policy, citizen,
                   title="Australian citizens only analyst") == ("draft", "eligible")
    assert outcome(job(evaluation, ad.replace("Baseline security clearance required.", "")),
                   ad.replace("Baseline security clearance required.", ""), policy, citizen) == ("draft", "eligible")


def test_full_time_exempt_takes_both_values_or_neither():
    for kwargs in ({"limit": 40}, {"ft_ok": True}):
        with pytest.raises(TypeError):
            gate._full_time_exempt("Graduate Accountant", "Full-time.", **kwargs)
    assert gate._full_time_exempt("Graduate Accountant", "Full-time.", limit=40, ft_ok=True) is True


@pytest.mark.parametrize("sentence,expect", [
    ("No security clearance is required.", ("draft", "eligible")),
    ("Baseline security clearance not required.", ("draft", "eligible")),
    ("Join our solar team working on PV systems.", ("draft", "eligible")),
    ("Our team will establish baseline metrics.", ("draft", "eligible")),
    ("Customs clearance experience is useful.", ("draft", "eligible")),
    ("Vetting of vendors is part of the role.", ("draft", "eligible")),
    ("Candidates must hold a baseline clearance.", ("archive", "hard_gate")),
    ("Baseline security clearance required.", ("archive", "hard_gate")),
])
def test_a_clearance_archives_a_citizen_only_as_a_negation_free_requirement(evaluation, policy, sentence, expect):
    ad = f"Graduate accounting analyst based in Melbourne VIC. {sentence}"
    assert outcome(job(evaluation, ad), ad, policy, policy_of(rights(citizen_or_pr=True))) == expect
