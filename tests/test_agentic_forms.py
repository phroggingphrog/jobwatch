from __future__ import annotations

import hashlib

import pytest

from pipeline.agentic.contracts import (
    AgenticEvaluation, AgenticScreeningAnswer, Dimension, RequirementSet, RunKey,
)
from pipeline.schemas import FormMap, JobFacts, WorkRights

H = "a" * 64
E = "b" * 64


def _evaluation(questions=("Are you eligible to work in Australia?", "When can you start?"), evidence_hash=E):
    return AgenticEvaluation(
        run_key=RunKey(posting_id=71, ad_hash=H, evidence_hash=evidence_hash, rubric_version="career-ops-v1",
                       config_hash="c" * 64),
        requirements=RequirementSet(ad_hash=H, requirements=()), matches=(), archetype="graduate analyst",
        global_score=4.1,
        dimensions={name: Dimension(score=4.0, reason="verified")
                    for name in ("cv_match", "north_star", "compensation", "culture", "red_flags")},
        facts=JobFacts(real_job=True, role_family="data_analyst", duties=["Analyse data"], required_skills=[],
                       preferred_skills=[], seniority="entry", min_years=None, hours="full_time_only", program=True,
                       work_rights=WorkRights(requirement="none_stated", quote=""), screening_questions=list(questions)),
        location_fit="melbourne", location_evidence=None, legitimacy="verified", research_available=False,
        report={key: f"section {key}" for key in "ABCDEFG"}, screening_questions=tuple(questions),
    )


def test_form_map_only_uses_cited_screening_answers_and_marks_unknown_owner_fields(tmp_path):
    """Quoted, evidenced answers map verbatim; unknown questions stay blank for owner review."""
    from pipeline.agentic.forms import build_form_map

    from jobwatch.candidate.evidence import snapshot_evidence
    quote = "I have unrestricted work rights in Australia."
    (tmp_path / "cv.md").write_text("# Synthetic Candidate\n## Experience\n- Automated reporting with Python\n")
    (tmp_path / "profile.yaml").write_text("work_rights: " + quote + "\n")
    bundle = snapshot_evidence(tmp_path)
    evaluation = _evaluation(evidence_hash=bundle.bundle_hash)
    citation = {"source_id": "profile.yaml", "content_hash": bundle.sources["profile.yaml"], "quote": quote}
    answers = (
        AgenticScreeningAnswer(question=evaluation.screening_questions[0], answer=quote,
                               source="evidence", citations=(citation,)),
        AgenticScreeningAnswer(question=evaluation.screening_questions[1], answer="", source="owner_to_answer"),
    )
    result = build_form_map(evaluation, answers, evidence_bundle=bundle, application_id=101, url="https://example.org/apply")
    assert result.application_id == 101
    assert isinstance(result, FormMap)
    assert [(field.value, field.source) for field in result.fields] == [
        (quote, "evidence"), ("", "owner_to_answer")]
    assert result.owner_to_answer == 1


def test_form_map_rejects_answer_not_supported_by_its_quote():
    """A mismatched cited question or quote cannot be copied into an employer form map."""
    from pipeline.agentic.forms import build_form_map

    evaluation = _evaluation()
    bad = AgenticScreeningAnswer(
        question=evaluation.screening_questions[0], answer="I can start tomorrow.", source="evidence",
        citations=({"source_id": "profile", "content_hash": E, "quote": "I can start next month."},),
    )
    with pytest.raises(Exception):
        build_form_map(evaluation, (bad,))


def test_form_map_marks_missing_answers_as_owner_to_answer():
    """Omitting an answer never silently marks a screening field as resolved."""
    from pipeline.agentic.forms import build_form_map

    evaluation = _evaluation(("Do you hold a current driver's licence?",))
    result = build_form_map(evaluation, ())
    assert result.fields[0].value == ""
    assert result.fields[0].source == "owner_to_answer"
    assert result.owner_to_answer == 1


def test_no_questions_does_not_create_a_fake_owner_hold():
    from pipeline.agentic.forms import build_form_map
    result = build_form_map(_evaluation(()), (), application_id=92)
    assert result.fields == [] and result.owner_to_answer == 0
