from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobwatch.candidate import (
    CandidateError,
    Mapping,
    TargetPolicy,
    analyse_candidate,
    analysis_metadata,
    default_policy,
    load_reference,
    snapshot_evidence,
    validate_mappings,
)
from candidate.fixtures import fictional_profile, fictional_reference as _write_reference, write_cv, write_profile


def fictional_reference(parent: Path) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    return _write_reference(parent)


def _confirmed(evidence, reference, *, dwa_id: str = "test.accounts", state: str = "confirmed", method: str = "fixture"):
    item = evidence.items[0]
    return Mapping(
        evidence_id=item.id,
        source_hash=item.source_hash,
        reference_hash=reference.reference_hash,
        dwa_id=dwa_id,
        method=method,
        state=state,
    )



def _filesystem_state(root: Path) -> dict[Path, tuple[bytes, int]]:
    return {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def test_callable_flow_is_read_only_and_exposes_safe_metadata(tmp_path: Path) -> None:
    first_root = fictional_profile(tmp_path / "person-a")
    second_root = write_cv(tmp_path / "person-b", "# Fictional B\n\n## Skills\n- Analysed datasets\n")
    reference_path = fictional_reference(tmp_path / "references")
    reference_data = json.loads(reference_path.read_text(encoding="utf-8"))
    reference_data["families"].append("data_analyst")
    reference_data["dwas"].append({"id": "test.analytics", "title": "Analyse datasets", "gwa_id": "test.analytics_gwa"})
    reference_data["occupations"].append({
        "code": "224114", "title": "Data Analyst", "family": "data_analyst", "excluded": False,
        "dwa_weights": {"test.analytics": 1.0}, "gwa_ratings": {"test.analytics_gwa": 4.0},
    })
    reference_path.write_text(json.dumps(reference_data), encoding="utf-8")
    before = _filesystem_state(tmp_path)
    source_state = _filesystem_state(tmp_path / "person-a")
    reference_state = _filesystem_state(tmp_path / "references")

    reference = load_reference(reference_path)
    assert reference is not None
    first = snapshot_evidence(first_root)
    second = snapshot_evidence(second_root)
    first_result = analyse_candidate(first, reference, (_confirmed(first, reference),), default_policy())
    second_result = analyse_candidate(
        second, reference, (_confirmed(second, reference, dwa_id="test.analytics"),), default_policy()
    )

    assert [fit.code for fit in first_result.recommendations] == ["221111"]
    assert [fit.code for fit in second_result.recommendations] == ["224114"]
    assert all(fit.recommendation_status == "candidate_path" for fit in first_result.recommendations)
    assert all(fit.recommendation_status == "candidate_path" for fit in second_result.recommendations)
    assert first_result.run_key != second_result.run_key
    assert first_result.evidence_hash != second_result.evidence_hash
    excluded = next(fit for fit in first_result.diagnostics if fit.code == "431111")
    assert excluded.recommendation_status == "excluded"
    metadata = analysis_metadata(first_result)
    rendered = json.dumps(metadata, sort_keys=True)
    assert "Reconciled ledgers" not in rendered
    assert all(item.id not in rendered for item in first.items)
    assert set(metadata) == {
        "status", "run_key", "evidence_hash", "reference_hash", "policy_hash",
        "mapping_hash", "recommendation_count", "diagnostic_count", "archetype_count", "unmapped_count",
    }
    assert _filesystem_state(tmp_path) == before
    assert _filesystem_state(tmp_path / "person-a") == source_state
    assert _filesystem_state(tmp_path / "references") == reference_state


@pytest.mark.parametrize("education_status", ["completed", "current"])
def test_education_only_evidence_is_diagnostic_and_never_recommends(tmp_path: Path, education_status: str) -> None:
    root = write_profile(
        tmp_path,
        f'education:\n  - degree: Bachelor of Commerce\n    status: {education_status}\n',
    )
    evidence = snapshot_evidence(root)
    reference = load_reference(fictional_reference(tmp_path / "refs"))
    assert reference is not None
    mapping = _confirmed(evidence, reference)
    result = analyse_candidate(evidence, reference, (mapping,), default_policy())
    assert result.recommendations == ()
    assert next(f for f in result.diagnostics if f.code == "221111").recommendation_status == "education_unverified"


def test_suggested_and_gwa_only_evidence_remain_diagnostic(tmp_path: Path) -> None:
    root = fictional_profile(tmp_path)
    evidence = snapshot_evidence(root)
    reference = load_reference(fictional_reference(tmp_path / "refs"))
    assert reference is not None
    suggested = analyse_candidate(evidence, reference, (_confirmed(evidence, reference, state="suggested"),), default_policy())
    assert suggested.recommendations == ()
    assert next(f for f in suggested.diagnostics if f.code == "221111").recommendation_status == "suggested_path"

    data = json.loads(fictional_reference(tmp_path / "gwa-reference").read_text(encoding="utf-8"))
    data["families"].append("finance_clerical")
    data["dwas"].append({"id": "test.billing", "title": "Prepare invoices", "gwa_id": "test.gwa"})
    data["occupations"].append({
        "code": "221112", "title": "Payments Clerk", "family": "finance_clerical", "excluded": False,
        "dwa_weights": {"test.billing": 1.0}, "gwa_ratings": {"test.gwa": 4.0},
    })
    reference_path = tmp_path / "gwa-reference.json"
    reference_path.write_text(json.dumps(data), encoding="utf-8")
    gwa_reference = load_reference(reference_path)
    assert gwa_reference is not None
    gwa_only = analyse_candidate(evidence, gwa_reference, (_confirmed(evidence, gwa_reference),), default_policy())
    assert all(fit.code != "221112" for fit in gwa_only.recommendations)
    assert next(f for f in gwa_only.diagnostics if f.code == "221112").recommendation_status == "suggested_path"


def test_unknown_declared_policy_taxonomy_and_immutable_exclusion_are_distinct(tmp_path: Path) -> None:
    root = fictional_profile(tmp_path / "profile")
    # A factual undeclared family is a taxonomy conflict; a declared but non-target family is not_target.
    path = fictional_reference(tmp_path / "refs")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["families"].append("legal")
    data["dwas"].append({"id": "test.unknown", "title": "Unclassified", "gwa_id": "test.gwa"})
    data["occupations"].extend([
        {"code": "222111", "title": "Mystery", "family": "astronomy", "excluded": False,
         "dwa_weights": {"test.accounts": 1.0}, "gwa_ratings": {"test.gwa": 4.0}},
        {"code": "541211", "title": "Relabelled customer role", "family": "finance_clerical", "excluded": False,
         "dwa_weights": {"test.accounts": 1.0}, "gwa_ratings": {"test.gwa": 4.0}},
        {"code": "222112", "title": "Declared outside policy", "family": "legal", "excluded": False,
         "dwa_weights": {"test.accounts": 1.0}, "gwa_ratings": {"test.gwa": 4.0}},
    ])
    # Remove the intentionally unused synthetic DWA from the fixture additions.
    data["dwas"].pop()
    path.write_text(json.dumps(data), encoding="utf-8")
    reference = load_reference(path)
    assert reference is not None
    evidence = snapshot_evidence(root)
    result = analyse_candidate(evidence, reference, (_confirmed(evidence, reference),), default_policy())
    statuses = {fit.code: fit.recommendation_status for fit in result.diagnostics}
    assert statuses["222111"] == "taxonomy_conflict"
    assert statuses["222112"] == "not_target"
    assert statuses["541211"] == "excluded"
    assert TargetPolicy(version="alias-v1", allowed_families=("Finance-Clerical",)).allowed_families == ("finance_clerical",)
    with pytest.raises(ValueError):
        TargetPolicy(version="bad-v1", allowed_families=("finance_clerical", "Customer Service"))


def test_changed_inputs_invalidate_run_identity_and_stale_receipts_fail(tmp_path: Path) -> None:
    root = fictional_profile(tmp_path / "profile")
    reference_path = fictional_reference(tmp_path / "refs")
    evidence = snapshot_evidence(root)
    reference = load_reference(reference_path)
    assert reference is not None
    mapping = _confirmed(evidence, reference)
    policy = default_policy()
    baseline = analyse_candidate(evidence, reference, (mapping,), policy)
    assert analyse_candidate(evidence, reference, (mapping,), policy).run_key == baseline.run_key

    (root / "cv.md").write_text("# Fictional\n\n## Skills\n- Reconciled accounts\n", encoding="utf-8")
    changed_evidence = snapshot_evidence(root)
    changed_source_result = analyse_candidate(
        changed_evidence, reference, (_confirmed(changed_evidence, reference),), policy
    )
    assert changed_source_result.run_key != baseline.run_key
    assert changed_evidence.bundle_hash != evidence.bundle_hash

    changed_mapping = Mapping(**(mapping.model_dump() | {"method": "different"}))
    assert analyse_candidate(evidence, reference, (changed_mapping,), policy).run_key != baseline.run_key
    changed_state = Mapping(**(mapping.model_dump() | {"state": "suggested"}))
    assert analyse_candidate(evidence, reference, (changed_state,), policy).run_key != baseline.run_key
    changed_policy = TargetPolicy(version="owner-v2", allowed_families=policy.allowed_families)
    assert analyse_candidate(evidence, reference, (mapping,), changed_policy).run_key != baseline.run_key

    stale_reference = load_reference(reference_path)
    reference_path.write_text(reference_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    changed_reference = load_reference(reference_path)
    assert changed_reference is not None
    assert changed_reference.reference_hash != reference.reference_hash
    with pytest.raises(CandidateError, match="mapping_invalid"):
        analyse_candidate(evidence, changed_reference, (mapping,), policy)
    rebound = _confirmed(evidence, changed_reference)
    assert analyse_candidate(evidence, changed_reference, (rebound,), policy).run_key != baseline.run_key
    assert stale_reference is not None


def test_missing_reference_and_unmapped_paths_are_explicit_empty_results(tmp_path: Path) -> None:
    root = fictional_profile(tmp_path / "profile")
    evidence = snapshot_evidence(root)
    unavailable = analyse_candidate(evidence, None, (), default_policy())
    assert unavailable.status == "reference_unavailable"
    assert unavailable.recommendations == unavailable.diagnostics == unavailable.archetypes == ()
    assert unavailable.unmapped_evidence_ids == ()

    reference = load_reference(fictional_reference(tmp_path / "refs"))
    assert reference is not None
    unmapped = analyse_candidate(evidence, reference, (), default_policy())
    assert unmapped.status == "unmapped"
    assert unmapped.recommendations == ()
    assert unmapped.unmapped_evidence_ids
    with pytest.raises(CandidateError, match="mapping_unresolved"):
        analyse_candidate(evidence, None, (_confirmed(evidence, reference),), default_policy())


def test_forged_safe_projection_is_rejected_without_echoing_private_fields(tmp_path: Path) -> None:
    evidence = snapshot_evidence(fictional_profile(tmp_path / "profile"))
    result = analyse_candidate(evidence, None, (), default_policy())
    forged = result.model_copy(update={"diagnostic_count": "PRIVATE_COUNT", "run_key": "PRIVATE_RUN_KEY"})
    with pytest.raises(CandidateError, match="analysis_invalid") as error:
        analysis_metadata(forged)
    assert "PRIVATE_COUNT" not in repr(error.value)
    assert "PRIVATE_RUN_KEY" not in repr(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
