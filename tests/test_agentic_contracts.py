"""Synthetic tests for the strict, hash-bound agentic wire contracts."""
from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from pipeline.agentic.contracts import (
    AgenticEvaluation,
    BudgetCheckpoint,
    Dimension,
    DraftProposal,
    PackageManifest,
    PublicAgenticError,
    Requirement,
    RequirementMatch,
    RequirementSet,
    Reservation,
    ReviewVerdict,
    RunKey,
    SourceCitation,
    check_frozen_requirements,
    validate_citations,
    validate_review,
    parse_budget_checkpoint_json,
)

H = "a" * 64
H2 = "b" * 64


def citation(quote: str = "Strong written communication") -> SourceCitation:
    return SourceCitation(source_id="ad", content_hash=H, quote=quote)


def key() -> RunKey:
    return RunKey(posting_id=7, ad_hash=H, evidence_hash=H2, rubric_version="career-ops-v1",
                  config_hash="c" * 64, candidate_hash="d" * 64)


def test_citation_quote_is_private_and_lookup_requires_exact_source_match():
    ref = citation()
    assert "Strong written communication" not in repr(ref)
    with pytest.raises(PublicAgenticError) as caught:
        validate_citations((ref,), {"ad": (H, "Strong communication")})
    assert caught.value.code == "invalid_citation"
    assert "Strong written communication" not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    text = "Strong written communication required"
    actual_hash = hashlib.sha256(text.encode()).hexdigest()
    valid = SourceCitation(source_id="ad", content_hash=actual_hash, quote="Strong written communication")
    assert validate_citations((valid,), {"ad": (actual_hash, text)}) is None


def test_requirement_importance_is_frozen_by_complete_requirement_identity():
    original = RequirementSet(ad_hash=H, requirements=(Requirement(
        id="r1", text="Writing", tier="stated", importance="high", jd_signal=citation()),))
    altered = RequirementSet(ad_hash=H, requirements=(Requirement(
        id="r1", text="Writing", tier="stated", importance="low_signal", jd_signal=citation()),))
    with pytest.raises(PublicAgenticError) as caught:
        check_frozen_requirements(original, altered)
    assert caught.value.code == "requirements_changed"


def test_requirement_set_rejects_duplicate_ids_and_unsupported_inference():
    item = Requirement(id="r1", text="Writing", tier="inferred", importance="meaningful")
    with pytest.raises(ValidationError):
        RequirementSet(ad_hash=H, requirements=(item, item))
    with pytest.raises(ValidationError):
        Requirement(id="r2", text="Writing", tier="inferred", importance="critical", blocker=True)


def test_citation_validation_rejects_unknown_ids_and_mutated_hashes():
    ref = citation()
    for sources in ({}, {"ad": (H2, ref.quote)}):
        with pytest.raises(PublicAgenticError) as caught:
            validate_citations((ref,), sources)
        assert caught.value.code == "invalid_citation"


def test_citation_validation_revalidates_copied_model_and_authenticates_source_hash():
    original = citation()
    copied = original.model_copy(update={"content_hash": H2})
    actual_text = "unrelated actual source text"
    actual_hash = hashlib.sha256(actual_text.encode()).hexdigest()
    copied = copied.model_copy(update={"content_hash": actual_hash})
    with pytest.raises(PublicAgenticError) as caught:
        validate_citations((copied,), {"ad": (actual_hash, actual_text)})
    assert caught.value.code == "invalid_citation"
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_run_identity_is_stable_and_binds_each_input_component():
    base = key()
    assert base.value == key().value
    changed = RunKey(posting_id=7, ad_hash=H, evidence_hash=H2, rubric_version="career-ops-v2",
                     config_hash="c" * 64, candidate_hash="d" * 64)
    assert base.value != changed.value
    assert len(base.value) == 64


def test_public_models_ignore_unknown_fields():
    value = SourceCitation(source_id="ad", content_hash=H, quote="q", unexpected="x")
    assert not hasattr(value, "unexpected")


def test_dimension_rejects_bool_nonfinite_and_out_of_range_scores():
    for score in (float("nan"), float("inf"), 0.9, 5.1):
        with pytest.raises(ValidationError):
            Dimension(score=score, reason="synthetic")


def test_evaluation_uses_separate_holistic_score_and_complete_match_coverage():
    reqs = RequirementSet(ad_hash=H, requirements=(Requirement(
        id="r1", text="Writing", tier="stated", importance="high", jd_signal=citation()),))
    base = _evaluation_base(reqs)
    with pytest.raises(ValidationError):
        AgenticEvaluation(**base, matches=())
    match = RequirementMatch(requirement_id="r1", match="partial", evidence=(), risk="gap", mitigation="address")
    value = AgenticEvaluation(**base, matches=(match,))
    assert value.global_score == 4.2


def test_evaluation_requires_gap_risk_and_mitigation_for_high_importance():
    reqs = RequirementSet(ad_hash=H, requirements=(Requirement(
        id="r1", text="Writing", tier="stated", importance="critical", jd_signal=citation()),))
    assert reqs.requirement_hash
    match = RequirementMatch(requirement_id="r1", match="missing", evidence=())
    # The owning evaluation performs this cross-object check to avoid accepting unsupported gaps.
    with pytest.raises(ValidationError):
        AgenticEvaluation(**_evaluation_base(reqs), matches=(match,))


def _evaluation_base(reqs):
    return dict(run_key=key(), requirements=reqs, archetype="analyst", global_score=4.2,
                dimensions={name: Dimension(score=4.0, reason="synthetic") for name in
                            ("cv_match", "north_star", "compensation", "culture", "red_flags")},
                facts={"real_job": True, "role_family": "analyst", "duties": ["analyze"],
                       "required_skills": [], "preferred_skills": [], "seniority": "entry", "min_years": None,
                       "hours": "unstated", "program": False,
                       "work_rights": {"requirement": "none_stated", "quote": ""},
                       "screening_questions": []},
                location_fit="unknown", legitimacy="uncertain", research_available=False,
                report={c: "synthetic" for c in "ABCDEFG"}, screening_questions=())


def test_review_must_bind_exact_draft_and_required_criteria():
    review = ReviewVerdict(run_key=key(), draft_hash=H2, reviewer_role="independent_reviewer", verdict="approve",
                           criteria={"claims": True, "tailoring": True}, feedback=())
    with pytest.raises(PublicAgenticError) as caught:
        validate_review(review, H, ("claims", "tailoring"))
    assert caught.value.code == "review_not_accepted"
    assert validate_review(review, H2, ("claims", "tailoring")) is None
    with pytest.raises(PublicAgenticError):
        validate_review(review, H2, ("claims", "tailoring", "safety"))


def test_draft_hash_covers_actual_payload_and_nested_mutation_changes_digest():
    content = {"letter": {"paragraphs": ["Synthetic text"]}}
    proposal = DraftProposal(run_key=key(), evaluation_hash=H, evidence_hash=H2, content=content)
    initial = proposal.draft_hash
    content["letter"]["paragraphs"][0] = "changed"
    assert proposal.draft_hash != initial
    assert len(initial) == 64


def test_draft_hash_error_has_no_cause_or_context_after_non_json_mutation():
    marker = "synthetic_private_marker"
    private_type = type(marker, (), {})
    proposal = DraftProposal(run_key=key(), evaluation_hash=H, evidence_hash=H2, content={"letter": {}})
    mutated = proposal.model_copy(update={"content": {"private": private_type()}})

    with pytest.raises(PublicAgenticError) as caught:
        _ = mutated.draft_hash

    assert caught.value.code == "invalid_draft"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert marker not in str(caught.value)


def test_agentic_screening_answer_requires_citations_and_hash_binds_them():
    from pipeline.agentic.contracts import AgenticScreeningAnswer, answers_content_hash
    source = citation("Synthetic verified answer")
    answer = AgenticScreeningAnswer(question="Can you write?", answer="Yes", source="evidence",
                                    citations=(source,))
    changed = AgenticScreeningAnswer(question="Can you write?", answer="Yes", source="evidence",
                                     citations=(citation("Different source quote"),))
    assert answers_content_hash((answer,)) != answers_content_hash((changed,))
    unknown = AgenticScreeningAnswer(question="Can you write?", answer="", source="owner_to_answer")
    assert unknown.answer == ""
    with pytest.raises(ValidationError):
        AgenticScreeningAnswer(question="Can you write?", answer="A specific claim", source="evidence")
    # an owner-only question the model tried to answer is blanked for the owner, not used
    assert AgenticScreeningAnswer(question="Can you write?", answer="Invented", source="owner_to_answer").answer == ""


def test_gate_decision_has_bounded_safe_route_without_permission_semantics():
    from pipeline.agentic.contracts import AgenticGateDecision
    assert AgenticGateDecision(route="hold", reason="verification_required", global_score=3.0,
                               run_key=key()).route == "hold"
    with pytest.raises(ValidationError):
        AgenticGateDecision(route="draft", reason="synthetic freeform", global_score=3.0, run_key=key())


def test_agentic_error_is_stable_alias():
    from pipeline.agentic.contracts import AgenticError
    assert AgenticError is PublicAgenticError


def test_draft_rejects_non_json_and_over_limit_content():
    with pytest.raises(ValidationError):
        DraftProposal(run_key=key(), evaluation_hash=H, evidence_hash=H2, content={"n": float("nan")})
    with pytest.raises(ValidationError):
        DraftProposal(run_key=key(), evaluation_hash=H, evidence_hash=H2, content={"x": "a" * (1024 * 1024)})


def test_manifest_is_only_verified_hash_metadata_and_has_no_paths():
    data = dict(run_key=key(), evaluation_hash=H, evidence_hash=H, answers_hash=H, draft_hash=H,
                review_hash=H, pdfs={"cv": H, "letter": H},
                verification={"cv_pdf": True, "letter_pdf": True, "claims": True, "review": True},
                owner_to_answer=0)
    assert PackageManifest(**data).owner_to_answer == 0
    with pytest.raises(ValidationError):
        PackageManifest(**{**data, "pdfs": {"cv": H, "letter": H, "path": "/tmp/x"}})


def test_reservations_charge_full_maximum_until_trusted_settlement():
    pending = Reservation(reservation_id="r1", role="evaluator", input_tokens=10,
                          requested_output_tokens=5, charged_tokens=15, state="ambiguous")
    assert pending.actual_usage is None
    settled = Reservation(reservation_id="r2", role="reviewer", input_tokens=10,
                          requested_output_tokens=5, charged_tokens=12, state="settled", actual_usage=12)
    assert settled.charged_tokens == 12
    with pytest.raises(ValidationError):
        Reservation(reservation_id="r3", role="reviewer", input_tokens=10,
                    requested_output_tokens=5, charged_tokens=15, state="settled", actual_usage=3)
    with pytest.raises(ValidationError):
        Reservation(reservation_id="r4", role="reviewer", input_tokens=True,
                    requested_output_tokens=5, charged_tokens=15, state="reserved")


def test_checkpoint_json_refuses_duplicate_keys_without_leaking_payload():
    secret = "synthetic-private-marker"
    payload = '{"schema_version":1,"run_key":"' + H + '","run_key":"' + secret + '"}'
    with pytest.raises(PublicAgenticError) as caught:
        parse_budget_checkpoint_json(payload)
    assert caught.value.code == "invalid_checkpoint"
    assert secret not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_checkpoint_rejects_boolean_version_and_evaluation_prevalidator_hides_private_keys():
    reservation = Reservation(reservation_id="r1", role="evaluator", input_tokens=10,
                              requested_output_tokens=5, charged_tokens=15, state="ambiguous")
    base = dict(schema_version=1, run_key=H, batch_id="batch-1", revision=1,
                job_token_ceiling=100, batch_token_ceiling=1000, job_charged=15,
                batch_charged=15, failed_attempts=0, role_turns={"evaluator": 1},
                research_queries=0, research_pages=0, job_deadline=1000.0,
                batch_deadline=2000.0, reservations=(reservation,))
    with pytest.raises(ValidationError):
        BudgetCheckpoint(**{**base, "schema_version": True})
    secret = "synthetic-private-marker"
    reqs = RequirementSet(ad_hash=H, requirements=())
    evaluation = _evaluation_base(reqs)
    evaluation["matches"] = ()
    evaluation["facts"] = {**evaluation["facts"], secret: "hidden"}
    with pytest.raises(ValidationError) as caught:
        AgenticEvaluation(**evaluation)
    assert secret not in str(caught.value)


def test_checkpoint_round_trip_keeps_ambiguous_charge_and_rejects_bad_totals():
    reservation = Reservation(reservation_id="r1", role="evaluator", input_tokens=10,
                              requested_output_tokens=5, charged_tokens=15, state="ambiguous")
    checkpoint = BudgetCheckpoint(schema_version=1, run_key=H, batch_id="batch-1", revision=1,
                                  job_token_ceiling=100, batch_token_ceiling=1000, job_charged=15,
                                  batch_charged=15, failed_attempts=0, role_turns={"evaluator": 1},
                                  research_queries=0, research_pages=0, job_deadline=1000.0,
                                  batch_deadline=2000.0, reservations=(reservation,))
    restored = parse_budget_checkpoint_json(checkpoint.model_dump_json())
    assert restored.job_charged == 15
    assert restored.reservations[0].charged_tokens == 15
    assert restored.model_dump_json() == checkpoint.model_dump_json()
    with pytest.raises(ValidationError):
        BudgetCheckpoint(**{**checkpoint.model_dump(), "job_charged": 14})
    with pytest.raises(ValidationError):
        BudgetCheckpoint(**{**checkpoint.model_dump(), "job_deadline": float("nan")})
