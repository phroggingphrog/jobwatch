from __future__ import annotations

import os
from pathlib import Path

import pytest

from jobwatch.candidate.contracts import CandidateError
from jobwatch.candidate.evidence import (
    bundle_from_contents,
    snapshot_evidence,
    validate_annotation,
    verify_evidence_snapshot,
)
from .fixtures import write_cv, write_profile


def test_cv_quote_binds_exact_primary_line_and_bytes(tmp_path: Path) -> None:
    root = write_cv(tmp_path, "# Fictional\n\n## Skills\n- Reconciled ledgers\n")
    bundle = snapshot_evidence(root)
    item = next(item for item in bundle.items if item.quote == "Reconciled ledgers")
    assert item.source_file == "master_resume.md"
    assert item.line == item.end_line == 4
    assert item.source_hash == bundle.sources["master_resume.md"]
    assert verify_evidence_snapshot(bundle) is None


def test_exact_relative_cv_alias_reuses_canonical_primary_identity(tmp_path: Path) -> None:
    root = write_cv(tmp_path, "# Fictional\n\n## Skills\n- Reconciled ledgers\n")
    expected = snapshot_evidence(root)
    (root / "cv.md").symlink_to("master_resume.md")
    actual = snapshot_evidence(root)
    assert actual == expected
    assert "cv.md" not in actual.sources
    assert all(item.source_file == "master_resume.md" for item in actual.items)
    verify_evidence_snapshot(actual)


@pytest.mark.parametrize("target", ["../outside.md", "./master_resume.md", "other.md"])
def test_cv_alias_accepts_no_other_relative_target(tmp_path: Path, target: str) -> None:
    root = write_cv(tmp_path, "# Fictional\n\n## Skills\n- Reconciled ledgers\n")
    (root / "cv.md").symlink_to(target)
    with pytest.raises(CandidateError, match="source_escape"):
        snapshot_evidence(root)


def test_cv_alias_never_follows_a_second_symlink(tmp_path: Path) -> None:
    root = tmp_path / "profile"
    root.mkdir()
    (root / "cv.md").symlink_to("master_resume.md")
    (root / "master_resume.md").symlink_to("../outside.md")
    with pytest.raises(CandidateError, match="source_escape"):
        snapshot_evidence(root)


def test_preferred_cv_alias_does_not_fallback_after_parse_failure(tmp_path: Path) -> None:
    root = write_cv(tmp_path, "# Preferred\n\n## Skills\n- Primary ledger skill\n")
    (root / "cv.md").write_bytes(b"\xff")
    with pytest.raises(CandidateError) as exc:
        snapshot_evidence(root)
    assert str(exc.value) == "source_invalid"
    assert "Primary ledger skill" not in repr(exc.value)


def test_symlink_primary_is_refused_without_private_error_context(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.write_text("SECRET_OUTSIDE", encoding="utf-8")
    root = tmp_path / "profile"
    root.mkdir()
    (root / "master_resume.md").symlink_to(outside)
    with pytest.raises(CandidateError) as exc:
        snapshot_evidence(root)
    assert str(exc.value) == "source_escape"
    assert exc.value.__cause__ is None and exc.value.__context__ is None
    assert "SECRET_OUTSIDE" not in repr(exc.value)


def test_symlink_root_is_refused(tmp_path: Path) -> None:
    real = write_cv(tmp_path, "# Fictional\n\n## Skills\n- Safe claim\n")
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(CandidateError, match="source_escape"):
        snapshot_evidence(linked)


def test_intermediate_symlink_component_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real" / "profile"
    real.mkdir(parents=True)
    (real / "master_resume.md").write_text("# Fictional\n\n## Skills\n- Safe claim\n", encoding="utf-8")
    parent = tmp_path / "parent"
    parent.mkdir()
    (parent / "linked").symlink_to(tmp_path / "real", target_is_directory=True)
    with pytest.raises(CandidateError, match="source_escape"):
        snapshot_evidence(parent / "linked" / "profile")


def test_ancestor_replacement_at_root_open_never_reads_outside(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import jobwatch.candidate.evidence as evidence

    approved_parent = tmp_path / "approved"
    approved_parent.mkdir()
    approved = approved_parent / "profile"
    approved.mkdir()
    (approved / "master_resume.md").write_text("# Fictional\n\n## Skills\n- Approved claim\n", encoding="utf-8")
    outside_parent = tmp_path / "outside"
    outside = outside_parent / "profile"
    outside.mkdir(parents=True)
    (outside / "master_resume.md").write_text("# Fictional\n\n## Skills\n- SYNTHETIC_OUTSIDE_PAYLOAD\n", encoding="utf-8")
    parked = tmp_path / "approved-parked"
    root_abs = os.path.abspath(approved)
    assert os.path.realpath(root_abs) == str(approved.resolve(strict=True))
    assert os.path.commonpath((str(tmp_path.resolve()), str(approved.resolve(strict=True)))) == str(tmp_path.resolve())
    original_open = os.open
    original_read = os.read
    outside_reads: list[bytes] = []
    swapped = False

    def record_read(fd: int, size: int) -> bytes:
        data = original_read(fd, size)
        if b"SYNTHETIC_OUTSIDE_PAYLOAD" in data:
            outside_reads.append(data)
        return data

    def swap_then_open(path, flags, *args, **kwargs):
        nonlocal swapped
        component_open = kwargs.get("dir_fd") is not None and os.fspath(path) == approved.name
        legacy_root_open = kwargs.get("dir_fd") is None and os.fspath(path) == root_abs
        if not swapped and (component_open or legacy_root_open):
            swapped = True
            approved_parent.rename(parked)
            approved_parent.symlink_to(outside_parent, target_is_directory=True)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(evidence.os, "open", swap_then_open)
    monkeypatch.setattr(evidence.os, "read", record_read)
    with pytest.raises(CandidateError, match="source_escape") as exc:
        snapshot_evidence(approved)
    assert swapped
    assert not outside_reads
    assert exc.value.__cause__ is None and exc.value.__context__ is None


def test_absent_primary_sources_reject(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    with pytest.raises(CandidateError, match="source_missing"):
        snapshot_evidence(root)


@pytest.mark.parametrize(("scalar", "expected"), [
    ('"Data\\u0020analysis"', "Data analysis"),
    ('|\n      Reconciled\n      ledgers\n', "Reconciled\nledgers"),
    ('>\n      Reconciled\n      ledgers\n', "Reconciled ledgers"),
])
def test_profile_yaml_literal_folded_and_escaped_quoted_scalars_are_decoded(
    tmp_path: Path, scalar: str, expected: str,
) -> None:
    root = write_profile(tmp_path, f"skills:\n  accounting:\n    - {scalar}\n")
    bundle = snapshot_evidence(root)
    assert any(item.quote == expected for item in bundle.items)
    assert verify_evidence_snapshot(bundle) is None


def test_profile_yaml_quotes_are_decoded_and_have_exact_node_spans(tmp_path: Path) -> None:
    root = write_profile(tmp_path, '''education:\n  - degree: "Bachelor of\n      Commerce"\n    status: 'completed'\nskills:\n  accounting:\n    - Reconciled ledgers\n''')
    bundle = snapshot_evidence(root)
    skill = next(i for i in bundle.items if i.quote == "Reconciled ledgers")
    education = next(i for i in bundle.items if i.quote == "Bachelor of Commerce")
    assert skill.line == skill.end_line == 7
    assert education.education_status == "completed"
    assert education.status_evidence is not None
    assert education.status_evidence.education_index == 0
    assert education.status_evidence.line == 4
    assert verify_evidence_snapshot(bundle) is None


@pytest.mark.parametrize("bad_yaml", [
    "skills: &x { accounting: [Ledgers] }\n",
    "skills: !custom [Ledgers]\n",
    "skills: *missing\n",
    "skills: {accounting: [Ledgers]}\nskills: {accounting: [Other]}\n",
    "skills: [One]\n---\nskills: [Two]\n",
])
def test_yaml_unsafe_or_ambiguous_syntax_rejected(tmp_path: Path, bad_yaml: str) -> None:
    root = write_profile(tmp_path, bad_yaml)
    with pytest.raises(CandidateError, match="source_invalid"):
        snapshot_evidence(root)


def test_contacts_are_dropped_without_rewriting_quotes(tmp_path: Path) -> None:
    root = write_cv(tmp_path, "# Fictional\n\n## Skills\n- Email me at fiction@example.test\n- Reconciled ledgers\n")
    bundle = snapshot_evidence(root)
    assert bundle.dropped_contact_count == 1
    assert all("fiction@example.test" not in item.quote for item in bundle.items)
    assert bundle.bundle_hash != snapshot_evidence(write_cv(tmp_path / "other", "# Fictional\n\n## Skills\n- Reconciled ledgers\n")).bundle_hash


def test_genuine_annotation_accepts_only_with_primary_bytes(tmp_path: Path) -> None:
    root = write_cv(tmp_path, "# Fictional\n\n## Skills\n- Reconciled ledgers\n")
    bundle = snapshot_evidence(root)
    item = bundle.items[0]
    assert validate_annotation(item, bundle.sources, contents=bundle.contents) is None
    with pytest.raises(CandidateError, match="annotation_invalid"):
        validate_annotation(item, bundle.sources)


def _legacy_catalogue(root):
    import yaml
    from jobwatch.apply.evidence import build_evidence
    (root / "transferable_skills_taxonomy.yaml").write_text(
        'version: "1"\nacademic_evidence:\n  synthetic_area:\n'
        '    - id: synthetic-derived\n      verbatim_fact: Derived taxonomy claim only.\n')
    catalogue = {"version": 1, "generator": "synthetic fixture", "generated_at": "2026-10-10",
                 "items": build_evidence(root)}
    (root / "evidence.yaml").write_text(yaml.safe_dump(catalogue))
    return catalogue


def test_legacy_generated_catalogue_validates_without_promoting_taxonomy_proof(tmp_path):
    root = write_cv(tmp_path, "# Fictional\n\n## Skills\n- Reconciled ledgers\n")
    primary = snapshot_evidence(root)
    catalogue = _legacy_catalogue(root)
    (root / "cv.md").symlink_to("master_resume.md")
    result = snapshot_evidence(root)
    assert len(catalogue["items"]) == len(primary.items) + 1
    assert result.items == primary.items
    assert result.bundle_hash != primary.bundle_hash
    assert not any("Derived taxonomy" in item.quote for item in result.items)
    verify_evidence_snapshot(result)


@pytest.mark.parametrize("source", ["master_resume.md", "transferable_skills_taxonomy.yaml"])
def test_legacy_import_cannot_change_a_primary_or_derived_record(tmp_path, source):
    import yaml
    root = write_cv(tmp_path, "# Fictional\n\n## Skills\n- Reconciled ledgers\n")
    catalogue = _legacy_catalogue(root)
    record = next(row for row in catalogue["items"] if row["source_file"] == source)
    record["text"] = "Invented qualification"
    (root / "evidence.yaml").write_text(yaml.safe_dump(catalogue))
    with pytest.raises(CandidateError, match="annotation_invalid"):
        snapshot_evidence(root)


def test_annotation_cannot_forge_primary_quote_or_relabel_kind(tmp_path: Path) -> None:
    root = write_cv(tmp_path, "# Fictional\n\n## Skills\n- Reconciled ledgers\n")
    bundle = snapshot_evidence(root)
    item = bundle.items[0]
    with pytest.raises(CandidateError, match="annotation_invalid"):
        validate_annotation(item.model_copy(update={"quote": "Fabricated credential"}), bundle.sources, contents=bundle.contents)
    with pytest.raises(CandidateError, match="annotation_invalid"):
        validate_annotation(item.model_copy(update={"kind": "cert"}), bundle.sources, contents=bundle.contents)
    with pytest.raises(CandidateError, match="annotation_invalid"):
        validate_annotation(item.model_copy(update={"line": item.line + 1}), bundle.sources, contents=bundle.contents)


def test_snapshot_verifier_rejects_caller_rehashed_fabrication(tmp_path: Path) -> None:
    root = write_cv(tmp_path, "# Fictional\n\n## Skills\n- Reconciled ledgers\n")
    bundle = snapshot_evidence(root)
    item = bundle.items[0].model_copy(update={"quote": "Fabricated claim"})
    from jobwatch.candidate.contracts import EvidenceBundle, compute_bundle_hash
    items = (item,)
    forged = EvidenceBundle(
        sources=bundle.sources, items=items,
        bundle_hash=compute_bundle_hash(bundle.sources, items, bundle.dropped_contact_count),
        dropped_contact_count=bundle.dropped_contact_count, contents=bundle.contents,
    )
    with pytest.raises(CandidateError, match="evidence_invalid"):
        verify_evidence_snapshot(forged)


def test_snapshot_verifier_rejects_rehashed_dropped_contact_count(tmp_path: Path) -> None:
    from jobwatch.candidate.contracts import EvidenceBundle, compute_bundle_hash
    root = write_cv(tmp_path, "# Fictional\n\n## Skills\n- Reconciled ledgers\n")
    bundle = snapshot_evidence(root)
    forged = EvidenceBundle(
        sources=bundle.sources, items=bundle.items,
        bundle_hash=compute_bundle_hash(bundle.sources, bundle.items, 999),
        dropped_contact_count=999, contents=bundle.contents,
    )
    with pytest.raises(CandidateError, match="evidence_invalid"):
        verify_evidence_snapshot(forged)


def test_snapshot_verifier_rejects_rehashed_malformed_annotation_yaml(tmp_path: Path) -> None:
    from jobwatch.candidate.contracts import EvidenceBundle, compute_bundle_hash, content_hash
    root = write_cv(tmp_path, "# Fictional\n\n## Skills\n- Reconciled ledgers\n")
    bundle = snapshot_evidence(root)
    contents = {**bundle.contents, "evidence.yaml": b"items: [malformed annotation]\n"}
    sources = {**bundle.sources, "evidence.yaml": content_hash(contents["evidence.yaml"])}
    forged = EvidenceBundle(
        sources=sources, items=bundle.items,
        bundle_hash=compute_bundle_hash(sources, bundle.items, bundle.dropped_contact_count),
        dropped_contact_count=bundle.dropped_contact_count, contents=contents,
    )
    with pytest.raises(CandidateError, match="evidence_invalid"):
        verify_evidence_snapshot(forged)


def test_verify_error_exposes_no_private_validation_context(tmp_path: Path) -> None:
    root = write_cv(tmp_path, "# Fictional\n\n## Skills\n- Reconciled ledgers\n")
    bundle = snapshot_evidence(root)
    forged_item = bundle.items[0].model_copy(update={"quote": "PRIVATE_INVALID_93"})
    from jobwatch.candidate.contracts import EvidenceBundle, compute_bundle_hash
    forged = EvidenceBundle(
        sources=bundle.sources, items=(forged_item,),
        bundle_hash=compute_bundle_hash(bundle.sources, (forged_item,), bundle.dropped_contact_count),
        dropped_contact_count=bundle.dropped_contact_count, contents=bundle.contents,
    )
    with pytest.raises(CandidateError, match="evidence_invalid") as exc:
        verify_evidence_snapshot(forged)
    assert exc.value.__cause__ is None and exc.value.__context__ is None
    assert "PRIVATE_INVALID_93" not in repr(exc.value)


def test_mutated_source_contents_are_rejected(tmp_path: Path) -> None:
    root = write_cv(tmp_path, "# Fictional\n\n## Skills\n- Reconciled ledgers\n")
    bundle = snapshot_evidence(root)
    altered = dict(bundle.contents)
    altered["master_resume.md"] = altered["master_resume.md"].replace(b"Reconciled", b"Fabricated")
    from jobwatch.candidate.contracts import EvidenceBundle
    forged = EvidenceBundle.model_construct(**{**bundle.__dict__, "contents": altered})
    with pytest.raises(CandidateError, match="evidence_invalid"):
        verify_evidence_snapshot(forged)


def test_source_size_is_bounded_and_nonregular_files_rejected(tmp_path: Path) -> None:
    root = write_cv(tmp_path, "#" + "x" * (2 * 1024 * 1024 + 1))
    with pytest.raises(CandidateError, match="source_invalid"):
        snapshot_evidence(root)


def test_source_bytes_remain_unchanged(tmp_path: Path) -> None:
    root = write_cv(tmp_path, "# Fictional\n\n## Skills\n- Reconciled ledgers\n")
    path = root / "master_resume.md"
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    snapshot_evidence(root)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_year_ranges_and_dates_are_not_phone_numbers(tmp_path: Path) -> None:
    keep = ["Analyst, Acme Pty Ltd 2019 - 2021", "Reconciled ledgers 2019-2021", "Policy updated 2026-09-24",
            "Sep 2019 - Jun 2021 at Acme", "Moved 12/03/2019 to Acme"]
    drop = ["Call 0412 345 678 for ledgers", "Phone +61 3 9123 4567 anytime", "Ring (03) 9123-4567 today"]
    root = write_cv(tmp_path, "# Fictional\n\n## Skills\n" + "".join(f"- {t}\n" for t in keep + drop))
    bundle = snapshot_evidence(root)
    quotes = " | ".join(i.quote for i in bundle.items)
    for t in keep:
        assert t in quotes, t
    for t in ("0412", "9123"):
        assert t not in quotes, t
    assert bundle.dropped_contact_count == len(drop)


def test_a_phone_number_with_year_like_digit_groups_is_still_contact_data():
    from jobwatch.candidate.evidence import _contact
    assert _contact({"text": "Phone +44 20 1999 2010 anytime"})
    assert not _contact({"text": "Analyst, Acme Pty Ltd 2019 - 2021"}) and not _contact({"text": "2019-2021"})


def test_bundle_from_contents_equals_snapshot_evidence(tmp_path: Path) -> None:
    expected = snapshot_evidence(write_cv(tmp_path, "# Fictional\n\n## Skills\n- Reconciled ledgers\n"))
    assert bundle_from_contents(dict(expected.contents)) == expected
    verify_evidence_snapshot(bundle_from_contents(dict(expected.contents)))


def test_bundle_from_contents_refuses_unknown_names_and_empty_contents() -> None:
    with pytest.raises(CandidateError, match="source_invalid"):
        bundle_from_contents({"notes.txt": b"x"})
    with pytest.raises(CandidateError):
        bundle_from_contents({})
