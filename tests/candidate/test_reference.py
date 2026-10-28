from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobwatch.candidate.contracts import CandidateError, content_hash
from jobwatch.candidate.reference import load_reference, verify_reference_snapshot, crosswalk_codes
from .fixtures import fictional_reference


def test_missing_reference_is_unavailable(tmp_path: Path) -> None:
    assert load_reference(tmp_path / "absent.json") is None


def test_root_reference_rejects_without_private_context() -> None:
    with pytest.raises(CandidateError) as exc:
        load_reference(Path("/"))
    assert str(exc.value) == "reference_invalid"
    assert exc.value.__cause__ is None and exc.value.__context__ is None


def test_duplicate_json_keys_reject_without_private_context(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"version":"a","version":"b"}', encoding="utf-8")
    with pytest.raises(CandidateError) as exc:
        load_reference(path)
    assert str(exc.value) == "reference_invalid"
    assert exc.value.__cause__ is None and exc.value.__context__ is None


def test_loader_binds_raw_bytes_and_crosswalk_returns_all_candidates(tmp_path: Path) -> None:
    path = fictional_reference(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["crosswalks"] = [{"soc": "S1", "anzsco_codes": ["221111", "431111"]}]
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    path.write_bytes(raw)
    bundle = load_reference(path)
    assert bundle is not None
    assert bundle.reference_hash == content_hash(raw)
    assert bundle.raw_contents == raw
    assert verify_reference_snapshot(bundle) is None
    assert crosswalk_codes(bundle, "S1") == ("221111", "431111")
    assert crosswalk_codes(bundle, "unknown") == ()


def test_reference_revalidation_rejects_nested_mutation_even_with_stale_hash(tmp_path: Path) -> None:
    bundle = load_reference(fictional_reference(tmp_path))
    assert bundle is not None
    changed = bundle.model_copy(update={"occupations": (bundle.occupations[0].model_copy(update={"dwa_weights": {"test.accounts": 99.0}}), *bundle.occupations[1:])})
    with pytest.raises(CandidateError, match="reference_invalid"):
        verify_reference_snapshot(changed)


@pytest.mark.parametrize("metadata", ["version", "licenses"])
def test_required_metadata_must_be_present_and_nonempty(tmp_path: Path, metadata: str) -> None:
    path = fictional_reference(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data[metadata] = " " if metadata == "version" else {"fictional": "  "}
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CandidateError, match="reference_invalid"):
        load_reference(path)


def test_reference_rejects_both_source_and_license_maps_empty(tmp_path: Path) -> None:
    path = fictional_reference(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["sources"] = {}
    data["licenses"] = {}
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CandidateError, match="reference_invalid"):
        load_reference(path)


@pytest.mark.parametrize("metadata", ["sources", "licenses"])
def test_reference_requires_nonempty_source_and_license_maps(tmp_path: Path, metadata: str) -> None:
    path = fictional_reference(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data[metadata] = {}
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CandidateError, match="reference_invalid"):
        load_reference(path)


def test_declared_excluded_family_remains_available_for_diagnostics(tmp_path: Path) -> None:
    bundle = load_reference(fictional_reference(tmp_path))
    assert bundle is not None
    assert "hospitality" in bundle.families
    hospitality = next(item for item in bundle.occupations if item.code == "431111")
    assert hospitality.family in bundle.families
    assert hospitality.excluded is True


def test_reference_export_rejects_nonfinite_weights_and_dangling_ids(tmp_path: Path) -> None:
    path = fictional_reference(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["occupations"][0]["dwa_weights"] = {"test.unknown": float("nan")}
    path.write_text(json.dumps(data, allow_nan=True), encoding="utf-8")
    with pytest.raises(CandidateError, match="reference_invalid"):
        load_reference(path)


def test_ancestor_replacement_at_final_open_never_reads_outside(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    import jobwatch.candidate.reference as reference

    approved_parent = tmp_path / "approved"
    approved_parent.mkdir()
    path = approved_parent / "reference.json"
    path.write_text("{}", encoding="utf-8")
    outside_parent = tmp_path / "outside"
    outside_parent.mkdir()
    outside = outside_parent / "reference.json"
    outside.write_text('{"synthetic":"SYNTHETIC_OUTSIDE_PAYLOAD"}', encoding="utf-8")
    parked = tmp_path / "approved-parked"
    root_abs = os.path.abspath(path)
    assert os.path.realpath(root_abs) == str(path.resolve(strict=True))
    assert os.path.commonpath((str(tmp_path.resolve()), str(path.resolve(strict=True)))) == str(tmp_path.resolve())
    original_open = os.open
    original_read = os.read
    outside_reads: list[bytes] = []
    swapped = False

    def record_read(fd: int, size: int) -> bytes:
        data = original_read(fd, size)
        if b"SYNTHETIC_OUTSIDE_PAYLOAD" in data:
            outside_reads.append(data)
        return data

    def swap_then_open(target, flags, *args, **kwargs):
        nonlocal swapped
        component_open = kwargs.get("dir_fd") is not None and os.fspath(target) == path.name
        legacy_final_open = kwargs.get("dir_fd") is None and os.fspath(target) == root_abs
        if not swapped and (component_open or legacy_final_open):
            swapped = True
            approved_parent.rename(parked)
            approved_parent.symlink_to(outside_parent, target_is_directory=True)
        return original_open(target, flags, *args, **kwargs)

    monkeypatch.setattr(reference.os, "open", swap_then_open)
    monkeypatch.setattr(reference.os, "read", record_read)
    with pytest.raises(CandidateError, match="reference_invalid") as exc:
        load_reference(path)
    assert swapped
    assert not outside_reads
    assert exc.value.__cause__ is None and exc.value.__context__ is None
    assert "SYNTHETIC_OUTSIDE_PAYLOAD" not in repr(exc.value)


def test_reference_loader_rejects_symlink_components_nonregular_and_oversize(tmp_path: Path) -> None:
    path = fictional_reference(tmp_path)
    link = tmp_path / "linked.json"
    link.symlink_to(path)
    with pytest.raises(CandidateError, match="reference_invalid"):
        load_reference(link)
    with pytest.raises(CandidateError, match="reference_invalid"):
        load_reference(tmp_path)
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "reference.json").write_bytes(path.read_bytes())
    parent_link = tmp_path / "parent-link"
    parent_link.symlink_to(real_dir, target_is_directory=True)
    with pytest.raises(CandidateError, match="reference_invalid"):
        load_reference(parent_link / "reference.json")
    pipe = tmp_path / "fifo.json"
    import os
    os.mkfifo(pipe)
    with pytest.raises(CandidateError, match="reference_invalid"):
        load_reference(pipe)
    path.write_bytes(b" " * (32 * 1024 * 1024 + 1))
    with pytest.raises(CandidateError, match="reference_invalid"):
        load_reference(path)


def test_real_hierarchical_dwa_requires_declared_five_segment_gwa_prefix(tmp_path: Path) -> None:
    path = fictional_reference(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["dwas"] = [{"id": "4.A.1.a.1.a.1", "title": "Example DWA", "gwa_id": "4.A.1.a.2"}]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CandidateError, match="reference_invalid"):
        load_reference(path)


def test_reference_bundle_raw_receipt_is_private_and_excluded_from_serialization(tmp_path: Path) -> None:
    bundle = load_reference(fictional_reference(tmp_path))
    assert bundle is not None
    assert "raw_contents" not in repr(bundle)
    assert "raw_contents" not in bundle.model_dump(mode="json")
