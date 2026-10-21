"""Candidate-first assessment uses real Deep Agents tools and synthetic evidence only."""

from jobwatch import model_choice
import copy
import json

import pytest

from jobwatch.candidate.assessment import (
    CandidateAssessment, assessment_metadata, evaluate_candidate,
)
from jobwatch.candidate.contracts import TargetPolicy, content_hash
from jobwatch.candidate.evidence import bind_career_profile, snapshot_evidence
from pipeline.agentic.contracts import AgenticError
from pipeline.agentic.runtime import BatchBudget, JobBudget


class Model:
    base_url = model_choice.SERVER_URL
    def __init__(self, choices):
        self.choices = iter(choices)
        self.seen = []

    def chat_once(self, model, messages, **kwargs):
        self.seen.append(copy.deepcopy(messages))
        return next(self.choices)


def case(tmp_path, skill="Reconciled ledgers", framing="Target accounting"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "cv.md").write_text(f"# Synthetic\n\n## Skills\n- {skill}\n")
    bundle = bind_career_profile(snapshot_evidence(tmp_path), framing)
    item = bundle.items[0]
    cite = {"source_id": item.source_file, "content_hash": item.source_hash, "quote": item.quote}
    choices = [
        {"tool": "read_evidence", "arguments": {"evidence_ids": [item.id]}},
        {"tool": "read_structural_analysis", "arguments": {}},
        {"tool": "complete_candidate_assessment", "arguments": {
            "strengths": [{"claim": skill, "citations": [cite]}],
            "gaps": [{"gap": "Formal certification is not demonstrated in this snapshot",
                      "action": "Confirm certification status with the owner", "citations": []}],
            "target_paths": [{"family": "accounting", "rationale": "Ledger practice supports junior accounts work",
                              "citations": [cite], "next_steps": ["Seek supervised entry-level ledger work"]}],
        }},
    ]
    return bundle, choices


def budget():
    return JobBudget("a" * 64, BatchBudget("candidate"), token_ceiling=500_000)


def test_candidate_assessment_runs_before_jobs_and_reference_absence_is_honest(tmp_path):
    bundle, choices = case(tmp_path)
    model = Model(choices)
    result = evaluate_candidate(bundle, budget(), model)
    assert type(result) is CandidateAssessment
    assert result.structural_analysis.status == "reference_unavailable"
    assert not result.structural_analysis.recommendations
    assert result.strengths[0].citations[0].quote == "Reconciled ledgers"
    assert result.target_paths[0].family == "accounting"
    assert len(model.seen) == 3
    context = json.loads(model.seen[0][-1]["content"])
    assert "ad_text" not in context and "requirements" not in context
    assert context["career_profile"] == "Target accounting"
    metadata = assessment_metadata(result)
    assert metadata["strength_count"] == 1 and "Reconciled ledgers" not in json.dumps(metadata)


def test_assessment_identity_changes_for_evidence_profile_policy_or_model(tmp_path):
    results = []
    for idx, (skill, framing, policy, model_name) in enumerate([
        ("Reconciled ledgers", "Target accounting", TargetPolicy(version="v1"), "claude/haiku"),
        ("Built SQL reports", "Target accounting", TargetPolicy(version="v1"), "claude/haiku"),
        ("Reconciled ledgers", "Target finance", TargetPolicy(version="v1"), "claude/haiku"),
        ("Reconciled ledgers", "Target accounting", TargetPolicy(version="v2"), "claude/haiku"),
        ("Reconciled ledgers", "Target accounting", TargetPolicy(version="v1"), "claude/sonnet"),
    ]):
        bundle, choices = case(tmp_path / str(idx), skill, framing)
        results.append(evaluate_candidate(bundle, budget(), Model(choices), policy=policy, model=model_name))
    assert len({item.run_key for item in results}) == 5
    assert results[0].evidence_hash != results[2].evidence_hash


@pytest.mark.parametrize("source", ["ad", "career_ops_profile.md", "derived_analysis"])
def test_candidate_findings_cannot_cite_non_primary_sources(tmp_path, source):
    bundle, choices = case(tmp_path)
    choices[-1]["arguments"]["strengths"][0]["citations"][0]["source_id"] = source
    with pytest.raises(AgenticError, match="invalid_candidate_assessment"):
        evaluate_candidate(bundle, budget(), Model(choices))


def test_excluded_and_non_target_paths_are_rejected(tmp_path):
    bundle, choices = case(tmp_path)
    choices[-1]["arguments"]["target_paths"][0]["family"] = "hospitality"
    with pytest.raises(AgenticError, match="invalid_candidate_assessment"):
        evaluate_candidate(bundle, budget(), Model(choices))


def test_snapshot_hashes_career_profile_without_extracting_it_as_evidence(tmp_path):
    (tmp_path / "cv.md").write_text("# Synthetic\n\n## Skills\n- Reconciled ledgers\n")
    before = snapshot_evidence(tmp_path)
    (tmp_path / "career_ops_profile.md").write_text("I want to become a certified auditor")
    after = snapshot_evidence(tmp_path)
    assert before.bundle_hash != after.bundle_hash
    assert before.items == after.items
    assert after.sources["career_ops_profile.md"] == content_hash(b"I want to become a certified auditor")
    assert all(item.source_file != "career_ops_profile.md" for item in after.items)


def test_profile_cannot_silently_replace_bound_source(tmp_path):
    bundle, choices = case(tmp_path)
    model = Model(choices)
    with pytest.raises(Exception, match="career_profile_invalid"):
        evaluate_candidate(bundle, budget(), model, career_profile="Different framing")
    assert not model.seen


def test_authenticated_reference_and_mapping_reuse_existing_structural_analysis(tmp_path):
    from jobwatch.candidate.contracts import Mapping
    from .fixtures import fictional_reference_bundle
    bundle, choices = case(tmp_path / "candidate")
    reference = fictional_reference_bundle(tmp_path)
    item = bundle.items[0]
    mapping = Mapping(evidence_id=item.id, source_hash=item.source_hash,
                      reference_hash=reference.reference_hash, dwa_id="test.accounts",
                      method="synthetic-confirmation", state="confirmed")
    result = evaluate_candidate(bundle, budget(), Model(choices), reference=reference, mappings=(mapping,))
    assert result.structural_analysis.status == "available"
    assert result.structural_analysis.reference_hash == reference.reference_hash
    assert result.structural_analysis.recommendations[0].code == "221111"
    assert result.structural_analysis.recommendations[0].evidence_ids == (item.id,)
