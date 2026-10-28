from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobwatch.candidate.contracts import CandidateError, Mapping
from jobwatch.candidate.evidence import snapshot_evidence
from jobwatch.candidate.mapping import validate_mappings
from jobwatch.candidate.reference import load_reference
from .fixtures import fictional_reference


def test_mapping_batch_is_bound_and_sorted_stably(tmp_path: Path) -> None:
    root = tmp_path / "profile"
    root.mkdir()
    (root / "master_resume.md").write_text("# Fictional\n\n## Skills\n- Reconciled ledgers\n", encoding="utf-8")
    evidence = snapshot_evidence(root)
    reference = load_reference(fictional_reference(tmp_path))
    assert reference is not None
    item = evidence.items[0]
    mapping = Mapping(evidence_id=item.id, source_hash=item.source_hash, reference_hash=reference.reference_hash, dwa_id="test.accounts", method="explicit", state="confirmed")
    assert validate_mappings(evidence, reference, (mapping,)) == (mapping,)


def test_duplicate_and_stale_mappings_refuse_the_whole_batch(tmp_path: Path) -> None:
    root = tmp_path / "profile"
    root.mkdir()
    (root / "master_resume.md").write_text("# Fictional\n\n## Skills\n- Reconciled ledgers\n", encoding="utf-8")
    evidence = snapshot_evidence(root)
    reference = load_reference(fictional_reference(tmp_path))
    assert reference is not None
    item = evidence.items[0]
    mapping = Mapping(evidence_id=item.id, source_hash=item.source_hash, reference_hash=reference.reference_hash, dwa_id="test.accounts", method="explicit", state="suggested")
    with pytest.raises(CandidateError, match="mapping_duplicate"):
        validate_mappings(evidence, reference, (mapping, mapping))
    forged = mapping.model_copy(update={"source_hash": "0" * 64})
    with pytest.raises(CandidateError, match="mapping_invalid"):
        validate_mappings(evidence, reference, (forged,))


def test_mapping_limit_is_three_per_evidence(tmp_path: Path) -> None:
    path = fictional_reference(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    for index in (2, 3, 4):
        dwa_id = f"test.accounts{index}"
        data["dwas"].append({"id": dwa_id, "title": f"Accounts {index}", "gwa_id": "test.gwa"})
    path.write_text(json.dumps(data), encoding="utf-8")
    root = tmp_path / "profile"
    root.mkdir()
    (root / "master_resume.md").write_text("# Fictional\n\n## Skills\n- Reconciled ledgers\n", encoding="utf-8")
    evidence = snapshot_evidence(root)
    reference = load_reference(path)
    assert reference is not None
    item = evidence.items[0]

    def mapping(dwa_id: str) -> Mapping:
        return Mapping(evidence_id=item.id, source_hash=item.source_hash, reference_hash=reference.reference_hash, dwa_id=dwa_id, method="explicit", state="suggested")

    valid_three = tuple(mapping(dwa_id) for dwa_id in ("test.accounts", "test.accounts2", "test.accounts3"))
    assert len(validate_mappings(evidence, reference, valid_three)) == 3
    valid_four = (*valid_three, mapping("test.accounts4"))
    with pytest.raises(CandidateError, match="mapping_invalid"):
        validate_mappings(evidence, reference, valid_four)


def test_mapping_output_is_stable_across_input_permutations(tmp_path: Path) -> None:
    root = tmp_path / "profile"
    root.mkdir()
    (root / "master_resume.md").write_text("# Fictional\n\n## Skills\n- Reconciled ledgers\n", encoding="utf-8")
    evidence = snapshot_evidence(root)
    path = fictional_reference(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["dwas"].append({"id": "test.billing", "title": "Billing", "gwa_id": "test.gwa"})
    path.write_text(json.dumps(data), encoding="utf-8")
    reference = load_reference(path)
    assert reference is not None
    item = evidence.items[0]
    first = Mapping(evidence_id=item.id, source_hash=item.source_hash, reference_hash=reference.reference_hash, dwa_id="test.accounts", method="explicit", state="suggested")
    second = Mapping(evidence_id=item.id, source_hash=item.source_hash, reference_hash=reference.reference_hash, dwa_id="test.billing", method="explicit", state="suggested")
    assert validate_mappings(evidence, reference, (first, second)) == validate_mappings(evidence, reference, (second, first))
