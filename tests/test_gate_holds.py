"""Synthetic regressions: corroborate blocking quotes; hold only otherwise-passing jobs."""
import pytest

from pipeline.nodes.gate import decide
from pipeline.schemas import JobFacts, MatchScore


def facts(requirement="citizen_only", quote="Unverifiable requirement", **changes):
    return JobFacts.model_validate({
        "real_job": True, "role_family": "accounts payable", "duties": ["process invoices"],
        "required_skills": [], "preferred_skills": [], "seniority": "entry", "min_years": None,
        "hours": "part_time_ok", "program": False, "screening_questions": [],
        "work_rights": {"requirement": requirement, "quote": quote}, **changes,
    })


def score(mark=5, wanted="core"):
    return MatchScore.model_validate({
        **{k: {"score": mark, "evidence": "synthetic evidence"}
           for k in ("technical_skills", "experience", "domain")},
        "wanted": wanted, "justification": "Synthetic entry-level accounts role.",
    })


def check(f, text, reason, route="archive", sc=None, title=""):
    got, decision = decide(f, sc or score(), text, title)
    assert (got, decision.reason) == (route, reason)
    assert decision.passed is (route == "draft")
    assert decision.score == (sc or score()).overall


def test_short_aps_quote_is_corroborated_by_rule():
    check(facts(quote="APS Level 5"), "APS Level 5", "work_rights:citizen_only", title="APS Level 5")


def test_without_restriction_quote_is_corroborated_by_rule():
    text = "Applicants must have the right to work without restriction or requiring visa sponsorship."
    check(facts("unrestricted_work_rights", text), text, "work_rights:unrestricted_work_rights")


def test_split_full_rights_quote_is_verified():
    text = "F ull Working Rights in Australia: sponsorship isn't available."
    check(facts("unrestricted_work_rights", text), text, "work_rights:unrestricted_work_rights")


@pytest.mark.parametrize("word,tail", [
    ("full", "Working Rights"), ("unrestricted", "work rights"), ("unlimited", "working rights"),
    ("permanent", "residency"), ("citizen", "of Australia"), ("citizens", "of Australia"),
    ("citizenship", "is required"),
])
def test_only_allowlisted_split_words_can_verify(word, tail):
    text = f"{word[0].upper()} {word[1:]} {tail}"
    check(facts("unrestricted_work_rights", text), text, "work_rights:unrestricted_work_rights")


@pytest.mark.parametrize("word,tail,requirement", [
    ("permanent", "resident of Australia", "citizen_or_pr"),
    ("citizen", "of Australia", "citizen_only"),
])
def test_split_keyword_after_single_letter_article_is_verified(word, tail, requirement):
    text = f"Applicants must be a {word[0].upper()} {word[1:]} {tail}."
    check(facts(requirement, text), text, f"work_rights:{requirement}")


@pytest.mark.parametrize("word", ["permanent", "citizen"])
def test_absent_split_keyword_quote_after_article_stays_unverified(word):
    quote = f"Applicants must be a {word[0].upper()} {word[1:]} resident of Australia."
    check(facts("citizen_only", quote), "Entry level accounts work.",
          "rights_claim_unverified", "review")


def test_non_keyword_split_letter_stays_unverified():
    text = "An a ccount role with flexible hours."
    check(facts(quote=text), text, "rights_claim_unverified", "review")


@pytest.mark.parametrize("changes,sc,reason", [
    ({}, score(wanted="not_wanted"), "not_target"),
    ({"seniority": "senior"}, score(), "too_senior"),
    ({"min_years": 4}, score(), "too_senior"),
    ({"hours": "full_time_only"}, score(), "full_time_only"),
    ({}, score(3), "low_score"),
])
@pytest.mark.parametrize("disagreement", [False, True])
def test_rights_holds_yield_to_non_rights_archives(changes, sc, reason, disagreement):
    text = "Applicants must be Australian citizens."
    f = facts("valid_work_rights", text, **changes) if disagreement else facts(**changes)
    check(f, text, reason, sc=sc)


def test_unverified_otherwise_passing_job_stays_review():
    check(facts(), "Entry level accounts work.", "rights_claim_unverified", "review")


def test_full_time_program_does_not_bypass_hold():
    check(facts(hours="full_time_only", program=True), "Graduate program.",
          "rights_claim_unverified", "review")


def test_citizen_pr_or_graduate_visa_disagreement_stays_review():
    text = ("Applicants must be a citizen of, or hold permanent residency in, Australia or New Zealand, "
            "or hold a Graduate Visa.")
    check(facts("valid_work_rights", text, program=True), text, "rights_rule_disagrees", "review")


def test_absent_quote_cannot_be_corroborated():
    check(facts(quote="APS Level 5"), "Applicants must be Australian citizens.",
          "rights_claim_unverified", "review")


def test_present_nonblocking_quote_cannot_use_rule_in_different_sentence():
    text = "Process invoices weekly. Applicants must be Australian citizens."
    check(facts(quote="Process invoices weekly."), text, "rights_claim_unverified", "review")


@pytest.mark.parametrize("requirement,quote,reason", [
    ("citizen_only", "Applicants must be Australian citizens.", "work_rights:citizen_only"),
    ("none_stated", "", "work_rights:found_by_rule"),
])
def test_verified_and_rule_only_archives_keep_precedence(requirement, quote, reason):
    check(facts(requirement, quote, seniority="senior", hours="full_time_only"),
          "Applicants must be Australian citizens.", reason, sc=score(3, "not_wanted"))


def test_non_rights_checks_keep_order():
    check(facts(seniority="senior", hours="full_time_only"), "Accounts work.",
          "not_target", sc=score(3, "not_wanted"))


def test_not_real_job_keeps_first_precedence():
    check(facts(real_job=False), "Applicants must be Australian citizens.", "not_a_real_job")
