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
from .fixtures import fictional_reference
from jobwatch.candidate.analysis import _clusters
from jobwatch.candidate.contracts import Occupation, OccupationFit


def _reference(path: Path) -> object:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["families"].append("finance_clerical")
    data["dwas"].extend([
        {"id": "test.billing", "title": "Prepare invoices", "gwa_id": "test.gwa"},
        {"id": "test.service", "title": "Serve customers", "gwa_id": "test.gwa"},
    ])
    data["occupations"].extend([
        {
            "code": "221112", "title": "Finance Clerk", "family": "finance_clerical",
            "excluded": False,
            "dwa_weights": {"test.accounts": 1.0, "test.billing": 1.0},
            "gwa_ratings": {"test.gwa": 4.0},
        },
        {
            "code": "221113", "title": "Payments Clerk", "family": "finance_clerical",
            "excluded": False,
            "dwa_weights": {"test.billing": 1.0},
            "gwa_ratings": {"test.gwa": 4.0},
        },
        {
            "code": "431112", "title": "Hospitality Team Member", "family": "hospitality",
            "excluded": False,
            "dwa_weights": {"test.service": 1.0},
            "gwa_ratings": {"test.gwa": 4.0},
        },
    ])
    path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    return load_reference(path)


def _mapped(evidence, reference, *, evidence_index: int = 0, dwa_id: str = "test.accounts", state: str = "confirmed"):
    item = evidence.items[evidence_index]
    mapping = Mapping(
        evidence_id=item.id,
        source_hash=item.source_hash,
        reference_hash=reference.reference_hash,
        dwa_id=dwa_id,
        method="human-review",
        state=state,
    )
    return mapping


def test_policy_contract_does_not_read_legacy_family_preferences() -> None:
    policy = TargetPolicy(version="owner-v1", allowed_families=("accounting", "hospitality"))
    assert policy.allowed_families == ("accounting", "hospitality")


def test_confirmed_ledger_mapping_recommends_target_not_excluded_high_similarity(tmp_path: Path) -> None:
    cv = tmp_path / "cv"
    cv.mkdir()
    (cv / "cv.md").write_text(
        "# Fictional\n\n## Skills\n- Reconciled ledgers\n- Prepared invoices\n",
        encoding="utf-8",
    )
    evidence = snapshot_evidence(cv)
    reference = _reference(fictional_reference(tmp_path))
    mappings = (_mapped(evidence, reference, dwa_id="test.accounts"),)
    result = analyse_candidate(evidence, reference, validate_mappings(evidence, reference, mappings),
                               TargetPolicy(version="confirmed-accounting", allowed_families=("accounting", "finance_clerical")))
    assert [fit.code for fit in result.recommendations] == ["221111", "221112"]
    excluded = next(fit for fit in result.diagnostics if fit.code == "431111")
    assert excluded.recommendation_status == "not_target"
    assert all(fit.code != "431112" for fit in result.recommendations)
    finance = next(fit for fit in result.recommendations if fit.code == "221112")
    assert finance.dwa_coverage == 0.5
    assert finance.gwa_similarity == 1.0
    assert finance.proximity == 0.7
    assert any(
        proposal.codes == ("221111", "221112")
        and proposal.shared_gwa_ids == ("test.gwa",)
        and proposal.policy_status == "candidate_path"
        for proposal in result.archetypes
    )


def test_hospitality_evidence_does_not_become_target_path(tmp_path: Path) -> None:
    cv = tmp_path / "cv"
    cv.mkdir()
    (cv / "cv.md").write_text("# Fictional\n\n## Experience\n- Served customers\n", encoding="utf-8")
    evidence = snapshot_evidence(cv)
    reference = _reference(fictional_reference(tmp_path))
    mapping = _mapped(evidence, reference, dwa_id="test.service")
    result = analyse_candidate(evidence, reference, validate_mappings(evidence, reference, (mapping,)),
                               TargetPolicy(version="confirmed-accounting", allowed_families=("accounting",)))
    assert result.recommendations == ()
    assert all(fit.recommendation_status != "candidate_path" for fit in result.diagnostics)


def test_reference_unavailable_and_no_mappings_is_explicit_empty_result(tmp_path: Path) -> None:
    cv = tmp_path / "cv"
    cv.mkdir()
    (cv / "cv.md").write_text("# Fictional\n\n## Skills\n- Reconciled ledgers\n", encoding="utf-8")
    evidence = snapshot_evidence(cv)
    result = analyse_candidate(evidence, None, (), default_policy())
    assert result.status == "reference_unavailable"
    assert result.recommendations == result.diagnostics == result.archetypes == ()
    assert result.unmapped_evidence_ids == ()
    with pytest.raises(CandidateError, match="mapping_unresolved"):
        analyse_candidate(evidence, None, (_mapped(evidence, _reference(fictional_reference(tmp_path))),), default_policy())


def test_unrelated_confirmed_dwa_does_not_ground_candidate_path_for_occupation(tmp_path: Path) -> None:
    cv = tmp_path / "cv"
    cv.mkdir()
    (cv / "cv.md").write_text("# Fictional\n\n## Skills\n- Reconciled ledgers\n", encoding="utf-8")
    evidence = snapshot_evidence(cv)
    reference = _reference(fictional_reference(tmp_path))
    mapping = _mapped(evidence, reference, dwa_id="test.accounts")
    validated = validate_mappings(evidence, reference, (mapping,))
    result = analyse_candidate(evidence, reference, validated, default_policy())
    finance = next(fit for fit in result.diagnostics if fit.code == "221113")
    assert finance.dwa_coverage == 0.0
    assert finance.recommendation_status == "suggested_path"


def test_stale_mutated_mapping_fails_at_analysis_entry(tmp_path: Path) -> None:
    cv = tmp_path / "cv"
    cv.mkdir()
    (cv / "cv.md").write_text("# Fictional\n\n## Skills\n- Reconciled ledgers\n", encoding="utf-8")
    evidence = snapshot_evidence(cv)
    reference = _reference(fictional_reference(tmp_path))
    mapping = _mapped(evidence, reference)
    mappings = validate_mappings(evidence, reference, (mapping,))
    forged = mappings[0].model_copy(update={"dwa_id": "test.missing"})
    with pytest.raises(CandidateError, match="mapping_invalid"):
        analyse_candidate(evidence, reference, (forged,), default_policy())


def test_suggested_mapping_remains_diagnostic_and_policy_changes_run_key(tmp_path: Path) -> None:
    cv = tmp_path / "cv"
    cv.mkdir()
    (cv / "cv.md").write_text("# Fictional\n\n## Skills\n- Reconciled ledgers\n", encoding="utf-8")
    evidence = snapshot_evidence(cv)
    reference = _reference(fictional_reference(tmp_path))
    mapping = _mapped(evidence, reference, state="suggested")
    validated = validate_mappings(evidence, reference, (mapping,))
    result = analyse_candidate(evidence, reference, validated, default_policy())
    fit = next(item for item in result.diagnostics if item.code == "221111")
    assert fit.recommendation_status == "suggested_path"
    alternative_policy = TargetPolicy(version="owner-v2", allowed_families=("accounting",))
    changed = analyse_candidate(evidence, reference, validated, alternative_policy)
    assert changed.run_key != result.run_key


def test_mutated_evidence_receipt_is_rejected_at_analysis_entry(tmp_path: Path) -> None:
    cv = tmp_path / "cv"
    cv.mkdir()
    (cv / "cv.md").write_text("# Fictional\n\n## Skills\n- Reconciled ledgers\n", encoding="utf-8")
    evidence = snapshot_evidence(cv)
    reference = _reference(fictional_reference(tmp_path))
    forged = evidence.model_copy(update={"contents": {"cv.md": b"changed bytes"}})
    with pytest.raises(CandidateError, match="evidence_invalid"):
        analyse_candidate(forged, reference, (), default_policy())


def _fit(code: str, proximity: float = 0.8, status: str = "candidate_path") -> OccupationFit:
    return OccupationFit(
        code=code, family="accounting", dwa_coverage=0.5, gwa_similarity=1.0,
        proximity=proximity, evidence_ids=("cv.L1",), gap_dwa_ids=(),
        mapping_states=("confirmed",), recommendation_status=status,
    )


def test_clusters_never_retain_a_low_rated_gwa_through_a_bridge() -> None:
    occupations = {
        "100001": Occupation(code="100001", title="A", family="accounting", dwa_weights={}, gwa_ratings={"gwa.a": 4.0, "gwa.b": 4.0}),
        "100002": Occupation(code="100002", title="B", family="accounting", dwa_weights={}, gwa_ratings={"gwa.a": 4.0, "gwa.b": 1.0}),
        "100003": Occupation(code="100003", title="C", family="accounting", dwa_weights={}, gwa_ratings={"gwa.b": 4.0}),
    }
    proposals = _clusters(tuple(_fit(code) for code in occupations), occupations, {"gwa.a", "gwa.b"})
    assert all("gwa.b" not in proposal.shared_gwa_ids for proposal in proposals if "100002" in proposal.codes)
    assert not any("100003" in proposal.codes and "100002" in proposal.codes for proposal in proposals)


def test_clusters_emit_supported_singleton_proposals() -> None:
    occupations = {"100001": Occupation(code="100001", title="A", family="accounting", dwa_weights={}, gwa_ratings={"gwa.a": 4.0})}
    proposals = _clusters((_fit("100001"),), occupations, {"gwa.a"})
    assert len(proposals) == 1
    assert proposals[0].codes == ("100001",)
    assert proposals[0].shared_gwa_ids == ("gwa.a",)


def test_cluster_seed_cap_is_global_per_policy_partition() -> None:
    occupations = {}
    fits = []
    for i in range(40):
        code = f"{100 + (i // 10):03d}{i % 10:03d}"
        occupations[code] = Occupation(code=code, title="A", family="accounting", dwa_weights={}, gwa_ratings={"gwa.a": 4.0})
        fits.append(_fit(code, proximity=1.0 - i / 100))
    proposals = _clusters(tuple(fits), occupations, {"gwa.a"})
    assert sum(len(proposal.codes) for proposal in proposals) == 30
    assert all(len({code[:3] for code in proposal.codes}) == 1 for proposal in proposals)


def test_analysis_metadata_rejects_forged_private_run_key(tmp_path: Path) -> None:
    cv = tmp_path / "cv"
    cv.mkdir()
    (cv / "cv.md").write_text("# Fictional\\n\\n## Skills\\n- Reconciled ledgers\\n", encoding="utf-8")
    evidence = snapshot_evidence(cv)
    result = analyse_candidate(evidence, None, (), default_policy())
    forged = result.model_copy(update={"run_key": "PRIVATE_ID"})
    with pytest.raises(CandidateError, match="analysis_invalid"):
        analysis_metadata(forged)


def test_invalid_forged_policy_error_has_no_nested_context(tmp_path: Path) -> None:
    cv = tmp_path / "cv"
    cv.mkdir()
    (cv / "cv.md").write_text("# Fictional\\n\\n## Skills\\n- Reconciled ledgers\\n", encoding="utf-8")
    evidence = snapshot_evidence(cv)
    forged_policy = default_policy().model_copy(update={"excluded_codes": ("PRIVATE_INVALID_CODE",)})
    with pytest.raises(CandidateError) as error:
        analyse_candidate(evidence, None, (), forged_policy)
    assert error.value.args == ("candidate_invalid",)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_unmapped_has_no_recommendations_and_metadata_is_safe(tmp_path: Path) -> None:
    cv = tmp_path / "cv"
    cv.mkdir()
    (cv / "cv.md").write_text("# Fictional\n\n## Skills\n- PRIVATE_LEDGER_QUOTE\n", encoding="utf-8")
    evidence = snapshot_evidence(cv)
    reference = _reference(fictional_reference(tmp_path))
    result = analyse_candidate(evidence, reference, (), default_policy())
    assert result.status == "unmapped"
    assert result.recommendations == ()
    metadata = json.dumps(analysis_metadata(result), sort_keys=True)
    assert "PRIVATE_LEDGER_QUOTE" not in metadata
    assert all(item.id not in metadata for item in evidence.items)
    assert set(analysis_metadata(result)) == {
        "status", "run_key", "evidence_hash", "reference_hash", "policy_hash",
        "mapping_hash", "recommendation_count", "diagnostic_count", "archetype_count",
        "unmapped_count",
    }


def test_reference_desirability_annotations_do_not_exclude_careers(tmp_path, monkeypatch):
    """Same evidence/reference, only the confirmed policy projection changes desirability."""
    from jobwatch.candidate.contracts import KNOWN_FAMILIES
    cv = tmp_path / 'synthetic-profile'
    cv.mkdir()
    (cv / 'cv.md').write_text('# Fictional\n\n## Skills\n- Reconciled ledgers\n')
    # A legacy unapproved interest must not become a structural exclusion.
    (cv / 'interests_and_criteria.yaml').write_text('target_roles:\n  excluded_families: [hospitality]\n')
    monkeypatch.setenv('JOBWATCH_PROFILE_DIR', str(cv))
    evidence = snapshot_evidence(cv)
    reference = load_reference(fictional_reference(tmp_path))
    mappings = validate_mappings(evidence, reference, (_mapped(evidence, reference),))
    neutral = TargetPolicy(version='confirmed-person-a', allowed_families=KNOWN_FAMILIES,
                           excluded_codes=(), require_minimum_excluded_codes=False)
    result = analyse_candidate(evidence, reference, mappings, neutral)
    assert {f.code for f in result.recommendations} == {'221111', '431111'}
    confirmed_exclusion = neutral.model_copy(update={'version':'confirmed-person-b',
        'allowed_families':tuple(f for f in KNOWN_FAMILIES if f != 'hospitality')})
    excluded = analyse_candidate(evidence, reference, mappings, confirmed_exclusion)
    assert {f.code for f in excluded.recommendations} == {'221111'}
    assert next(f for f in excluded.diagnostics if f.code == '431111').recommendation_status == 'not_target'
    assert result.run_key != excluded.run_key
