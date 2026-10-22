"""Synthetic corroboration regressions against explicit confirmed rights, never donor defaults."""
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


@pytest.fixture(autouse=True)
def confirmed_restricted_rights(monkeypatch):
    from jobwatch.candidate.policy import build_policy
    approved = {'version': 1, 'facts': [{'section': 'work_rights', 'basis': 'evidence', 'value': {
        'citizen': False, 'permanent_resident': False, 'valid_work_rights': True,
        'unrestricted_work_rights': False, 'requires_sponsorship': False}}]}
    policy = build_policy(approved)
    monkeypatch.setattr('jobwatch.candidate.policy.policy_for', lambda *args, **kwargs: policy)


def check(f, text, reason, route="archive", sc=None, title=""):
    got, decision = decide(f, sc or score(), text, title)
    assert (got, decision.reason) == (route, reason)
    assert decision.passed is (route == "draft")
    assert decision.score == (sc or score()).overall


def test_aps_grade_alone_does_not_prove_a_citizenship_requirement():
    check(facts(quote="APS Level 5"), "APS Level 5", "verification_required", "review", title="APS Level 5")


def test_without_restriction_quote_is_corroborated_by_rule():
    text = "Applicants must have the right to work without restriction or requiring visa sponsorship."
    check(facts("unrestricted_work_rights", text), text, "work_rights_incompatible")


def test_split_full_rights_quote_is_verified():
    text = "F ull Working Rights in Australia: sponsorship isn't available."
    check(facts("unrestricted_work_rights", text), text, "verification_required", "review")


@pytest.mark.parametrize("word,tail", [
    ("full", "Working Rights"), ("unrestricted", "work rights"), ("unlimited", "working rights"),
    ("permanent", "residency"), ("citizen", "of Australia"), ("citizens", "of Australia"),
    ("citizenship", "is required"),
])
def test_only_allowlisted_split_words_can_verify(word, tail):
    text = f"{word[0].upper()} {word[1:]} {tail}"
    if word == "full":
        check(facts("unrestricted_work_rights", text), text, "verification_required", "review")
    else:
        check(facts("unrestricted_work_rights", text), text, "work_rights_incompatible")


@pytest.mark.parametrize("word,tail,requirement", [
    ("permanent", "resident of Australia", "citizen_or_pr"),
    ("citizen", "of Australia", "citizen_only"),
])
def test_split_keyword_after_single_letter_article_is_verified(word, tail, requirement):
    text = f"Applicants must be a {word[0].upper()} {word[1:]} {tail}."
    check(facts(requirement, text), text, "work_rights_incompatible")


@pytest.mark.parametrize("word", ["permanent", "citizen"])
def test_absent_split_keyword_quote_after_article_stays_unverified(word):
    quote = f"Applicants must be a {word[0].upper()} {word[1:]} resident of Australia."
    check(facts("citizen_only", quote), "Entry level accounts work.",
          "verification_required", "review")


def test_non_keyword_split_letter_stays_unverified():
    text = "An a ccount role with flexible hours."
    check(facts(quote=text), text, "verification_required", "review")


@pytest.mark.parametrize('changes,sc', [
    ({}, score(wanted='not_wanted')), ({'seniority': 'senior'}, score()),
    ({'min_years': 4}, score()), ({'hours': 'full_time_only'}, score()), ({}, score(3)),
])
def test_unverified_rights_are_not_hidden_by_model_taste_or_shared_caps(changes, sc):
    check(facts(**changes), 'Accounts work.', 'verification_required', 'review', sc=sc)


def test_unverified_otherwise_passing_job_stays_review():
    check(facts(), "Entry level accounts work.", "verification_required", "review")


def test_full_time_program_does_not_bypass_hold():
    check(facts(hours="full_time_only", program=True), "Graduate program.",
          "verification_required", "review")


def test_citizen_pr_or_graduate_visa_disagreement_stays_review():
    text = ("Applicants must be a citizen of, or hold permanent residency in, Australia or New Zealand, "
            "or hold a Graduate Visa.")
    check(facts("valid_work_rights", text, program=True), text, "eligibility_unknown", "review")


def test_absent_quote_cannot_be_corroborated():
    check(facts(quote="APS Level 5"), "Applicants must be Australian citizens.",
          "verification_required", "review")


def test_present_nonblocking_quote_cannot_use_rule_in_different_sentence():
    text = "Process invoices weekly. Applicants must be Australian citizens."
    check(facts(quote="Process invoices weekly."), text, "verification_required", "review")


@pytest.mark.parametrize("requirement,quote,reason", [
    ("citizen_only", "Applicants must be Australian citizens.", "work_rights_incompatible"),
    ("none_stated", "", "work_rights_incompatible"),
])
def test_verified_and_rule_only_archives_keep_precedence(requirement, quote, reason):
    check(facts(requirement, quote, seniority="senior", hours="full_time_only"),
          "Applicants must be Australian citizens.", reason, sc=score(3, "not_wanted"))


def test_unknown_rights_are_not_replaced_by_unconfirmed_personal_preferences():
    check(facts(seniority="senior", hours="full_time_only"), "Accounts work.",
          "verification_required", "review", sc=score(3, "not_wanted"))


def test_not_real_job_keeps_first_precedence():
    check(facts(real_job=False), "Applicants must be Australian citizens.", "not_a_real_job")
