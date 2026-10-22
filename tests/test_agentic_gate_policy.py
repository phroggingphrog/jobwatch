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
