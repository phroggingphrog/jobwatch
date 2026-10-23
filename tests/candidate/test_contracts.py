from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from jobwatch.candidate.contracts import (
    DEFAULT_ALLOWED_FAMILIES,
    excluded_families,
    AnalysisResult,
    ArchetypeProposal,
    CandidateError,
    Crosswalk,
    Dwa,
    EducationStatusEvidence,
    EvidenceBundle,
    EvidenceItem,
    Mapping,
    Occupation,
    OccupationFit,
    ReferenceBundle,
    TargetPolicy,
    canonicalize_family,
    compute_bundle_hash,
    content_hash,
    digest,
)
from tests.candidate.fixtures import fictional_profile, fictional_reference, fictional_reference_bundle


def test_stable_digest() -> None:
    assert digest({"b": 2, "a": 1}) == digest({"a": 1, "b": 2})
    assert digest(["alpha", "beta"]) == digest(["alpha", "beta"])
    # Non-ascii UTF-8 stability
    assert digest({"name": "René"}) == digest({"name": "René"})


def test_digest_rejects_nonfinite_floats() -> None:
    with pytest.raises(ValueError):
        digest({"val": float("nan")})
    with pytest.raises(ValueError):
        digest({"val": float("inf")})


def test_content_hash() -> None:
    data = b"raw test content"
    h1 = content_hash(data)
    h2 = content_hash(data)
    assert h1 == h2
    assert len(h1) == 64
    assert all(c in "0123456789abcdef" for c in h1)


def test_error_is_safe() -> None:
    err = CandidateError("source_escape")
    assert str(err) == "source_escape"
    assert isinstance(err, ValueError)


def test_hide_input_in_errors_on_validation_failure() -> None:
    private_marker = "SUPER_SECRET_CANDIDATE_DATA_MARKER_99"
    with pytest.raises(ValidationError) as exc_info:
        EvidenceItem(
            id="cv.L1",
            kind="skill",
            source_file="cv.md",
            source_hash=private_marker,  # Invalid hash
            line=1,
            end_line=1,
            quote="Normal skill quote",
        )
    err_str = str(exc_info.value)
    err_repr = repr(exc_info.value)
    assert private_marker not in err_str
    assert private_marker not in err_repr




def test_malformed_hashes_rejected() -> None:
    # Uppercase hex rejected
    with pytest.raises(ValueError):
        EvidenceItem(
            id="cv.L1",
            kind="skill",
            source_file="cv.md",
            source_hash="A" * 64,
            line=1,
            end_line=1,
            quote="Reconciled ledgers",
        )
    # Short hash rejected
    with pytest.raises(ValueError):
        EvidenceItem(
            id="cv.L1",
            kind="skill",
            source_file="cv.md",
            source_hash="a" * 63,
            line=1,
            end_line=1,
            quote="Reconciled ledgers",
        )
    # Long hash rejected
    with pytest.raises(ValueError):
        EvidenceItem(
            id="cv.L1",
            kind="skill",
            source_file="cv.md",
            source_hash="a" * 65,
            line=1,
            end_line=1,
            quote="Reconciled ledgers",
        )
    # Non-hex characters rejected
    with pytest.raises(ValueError):
        EvidenceItem(
            id="cv.L1",
            kind="skill",
            source_file="cv.md",
            source_hash="z" * 64,
            line=1,
            end_line=1,
            quote="Reconciled ledgers",
        )


def test_evidence_item_education_status_invariants() -> None:
    valid_hash = "b" * 64

    # Work/skill item cannot have education_status other than 'not_applicable'
    with pytest.raises(ValueError):
        EvidenceItem(
            id="cv.L1",
            kind="skill",
            source_file="cv.md",
            source_hash=valid_hash,
            line=1,
            end_line=1,
            quote="Reconciled ledgers",
            education_status="completed",
        )

    # Education item defaults to 'unknown' when not explicitly provided
    edu_item = EvidenceItem(
        id="cv.L10",
        kind="education",
        source_file="cv.md",
        source_hash=valid_hash,
        line=10,
        end_line=11,
        quote="Bachelor of Commerce",
    )
    assert edu_item.education_status == "unknown"
    assert edu_item.status_evidence is None

    # Education item cannot be 'not_applicable'
    with pytest.raises(ValueError):
        EvidenceItem(
            id="cv.L10",
            kind="education",
            source_file="cv.md",
            source_hash=valid_hash,
            line=10,
            end_line=11,
            quote="Bachelor of Commerce",
            education_status="not_applicable",
        )

    # Education item with 'completed' requires valid status_evidence
    with pytest.raises(ValueError):
        EvidenceItem(
            id="cv.L10",
            kind="education",
            source_file="profile.yaml",
            source_hash=valid_hash,
            line=10,
            end_line=11,
            quote="Bachelor of Commerce",
            education_status="completed",
            status_evidence=None,
        )

    # Valid completed education item with status_evidence
    status_ev = EducationStatusEvidence(
        source_file="profile.yaml",
        source_hash=valid_hash,
        line=12,
        quote="completed",
        education_index=0,
    )
    edu_completed = EvidenceItem(
        id="cv.L10",
        kind="education",
        source_file="profile.yaml",
        source_hash=valid_hash,
        line=10,
        end_line=11,
        quote="Bachelor of Commerce",
        education_status="completed",
        status_evidence=status_ev,
    )
    assert edu_completed.education_status == "completed"
    assert edu_completed.status_evidence is not None

    # Mismatch between status_evidence quote and education_status rejected
    with pytest.raises(ValueError):
        EvidenceItem(
            id="cv.L10",
            kind="education",
            source_file="profile.yaml",
            source_hash=valid_hash,
            line=10,
            end_line=11,
            quote="Bachelor of Commerce",
            education_status="completed",
            status_evidence=EducationStatusEvidence(
                source_file="profile.yaml",
                source_hash=valid_hash,
                line=12,
                quote="current",  # mismatch
                education_index=0,
            ),
        )


def test_quote_suppressed_in_repr() -> None:
    private_quote = "PRIVATE_CONFIDENTIAL_CV_LINE_555"
    item = EvidenceItem(
        id="cv.L1",
        kind="skill",
        source_file="cv.md",
        source_hash="c" * 64,
        line=1,
        end_line=1,
        quote=private_quote,
    )
    assert private_quote not in repr(item)

    status_ev = EducationStatusEvidence(
        source_file="profile.yaml",
        source_hash="c" * 64,
        line=2,
        quote="completed",
        education_index=0,
    )
    assert "completed" not in repr(status_ev)


def test_evidence_item_line_number_bounds() -> None:
    valid_hash = "d" * 64
    with pytest.raises(ValueError):
        EvidenceItem(
            id="cv.L0",
            kind="skill",
            source_file="cv.md",
            source_hash=valid_hash,
            line=0,  # line < 1
            end_line=1,
            quote="Accounting",
        )
    with pytest.raises(ValueError):
        EvidenceItem(
            id="cv.L5",
            kind="skill",
            source_file="cv.md",
            source_hash=valid_hash,
            line=5,
            end_line=4,  # end_line < line
            quote="Accounting",
        )
    with pytest.raises(ValueError):
        EvidenceItem(
            id="cv.L5",
            kind="skill",
            source_file="cv.md",
            source_hash=valid_hash,
            line=5,
            end_line=5,
            quote="   ",  # empty quote
        )


def test_evidence_bundle_duplicate_ids_rejected() -> None:
    h = "e" * 64
    item1 = EvidenceItem(
        id="cv.L1",
        kind="skill",
        source_file="cv.md",
        source_hash=h,
        line=1,
        end_line=1,
        quote="Skill 1",
    )
    item2 = EvidenceItem(
        id="cv.L1",  # duplicate ID
        kind="role",
        source_file="cv.md",
        source_hash=h,
        line=5,
        end_line=5,
        quote="Role 1",
    )
    sources = {"cv.md": h}
    with pytest.raises(ValueError):
        EvidenceBundle(
            schema_version=1,
            sources=sources,
            items=(item1, item2),
            bundle_hash=compute_bundle_hash(sources, (item1, item2)),
        )


def test_evidence_bundle_source_mismatch_rejected() -> None:
    h_cv = "1" * 64
    h_wrong = "2" * 64
    item = EvidenceItem(
        id="cv.L1",
        kind="skill",
        source_file="cv.md",
        source_hash=h_wrong,
        line=1,
        end_line=1,
        quote="Skill 1",
    )
    sources = {"cv.md": h_cv}
    with pytest.raises(ValueError):
        EvidenceBundle(
            schema_version=1,
            sources=sources,
            items=(item,),
            bundle_hash=compute_bundle_hash(sources, (item,)),
        )


def test_evidence_bundle_path_traversal_filenames_rejected() -> None:
    h = "3" * 64
    item = EvidenceItem(
        id="cv.L1",
        kind="skill",
        source_file="cv.md",
        source_hash=h,
        line=1,
        end_line=1,
        quote="Skill 1",
    )
    # Filepath with directory separators rejected
    with pytest.raises(ValueError):
        EvidenceBundle(
            schema_version=1,
            sources={"../cv.md": h},
            items=(item,),
            bundle_hash="f" * 64,
        )


def test_evidence_bundle_contents_excluded_from_serialization() -> None:
    h = "4" * 64
    item = EvidenceItem(
        id="cv.L1",
        kind="skill",
        source_file="cv.md",
        source_hash=h,
        line=1,
        end_line=1,
        quote="Skill 1",
    )
    sources = {"cv.md": h}
    b_hash = compute_bundle_hash(sources, (item,))
    private_bytes = b"SECRET_BYTES_HERE"
    bundle = EvidenceBundle(
        schema_version=1,
        sources=sources,
        items=(item,),
        bundle_hash=b_hash,
        contents={"cv.md": private_bytes},
    )
    dumped = bundle.model_dump(mode="json")
    assert "contents" not in dumped
    assert "SECRET_BYTES_HERE" not in repr(bundle)


def test_occupation_nonfinite_weights_and_ratings_rejected() -> None:
    # NaN in dwa_weights rejected
    with pytest.raises(ValueError):
        Occupation(
            code="221111",
            title="Accountant",
            family="accounting",
            dwa_weights={"test.accounts": float("nan")},
            gwa_ratings={"test.gwa": 4.0},
        )
    # Inf in dwa_weights rejected
    with pytest.raises(ValueError):
        Occupation(
            code="221111",
            title="Accountant",
            family="accounting",
            dwa_weights={"test.accounts": float("inf")},
            gwa_ratings={"test.gwa": 4.0},
        )
    # Weight <= 0 rejected
    with pytest.raises(ValueError):
        Occupation(
            code="221111",
            title="Accountant",
            family="accounting",
            dwa_weights={"test.accounts": 0.0},
            gwa_ratings={"test.gwa": 4.0},
        )
    # Rating > 5.0 rejected
    with pytest.raises(ValueError):
        Occupation(
            code="221111",
            title="Accountant",
            family="accounting",
            dwa_weights={"test.accounts": 1.0},
            gwa_ratings={"test.gwa": 5.1},
        )
    # Rating < 0.0 rejected
    with pytest.raises(ValueError):
        Occupation(
            code="221111",
            title="Accountant",
            family="accounting",
            dwa_weights={"test.accounts": 1.0},
            gwa_ratings={"test.gwa": -0.1},
        )


def test_occupation_code_and_family_canonicalization() -> None:
    # Invalid code length
    with pytest.raises(ValueError):
        Occupation(
            code="22111",  # 5 digits
            title="Accountant",
            family="accounting",
            dwa_weights={"test.accounts": 1.0},
            gwa_ratings={"test.gwa": 4.0},
        )
    with pytest.raises(ValueError):
        Occupation(
            code="2211111",  # 7 digits
            title="Accountant",
            family="accounting",
            dwa_weights={"test.accounts": 1.0},
            gwa_ratings={"test.gwa": 4.0},
        )
    with pytest.raises(ValueError):
        Occupation(
            code="abcdef",  # non-digits
            title="Accountant",
            family="accounting",
            dwa_weights={"test.accounts": 1.0},
            gwa_ratings={"test.gwa": 4.0},
        )

    # Family canonicalization
    occ = Occupation(
        code="221111",
        title="Accountant",
        family="  Finance - Clerical  ",
        dwa_weights={"test.accounts": 1.0},
        gwa_ratings={"test.gwa": 4.0},
    )
    assert occ.family == "finance_clerical"


def test_canonicalize_family_helper() -> None:
    assert canonicalize_family("Hospitality") == "hospitality"
    assert canonicalize_family("hospitality_") == "hospitality"
    assert canonicalize_family("customer-service") == "customer_service"
    assert canonicalize_family("  Data__Analyst  ") == "data_analyst"


def test_target_policy_neutral_defaults_and_explicit_exclusions() -> None:
    # Classification validation does not read a person's unapproved legacy interest file.
    policy = TargetPolicy(version="v1", allowed_families=("accounting", "Hospitality", "customer-service"))
    assert policy.allowed_families == ("accounting", "hospitality", "customer_service")
    assert policy.excluded_codes == ()
    explicit = TargetPolicy(version="v1", allowed_families=("accounting",), excluded_codes=("999999",))
    assert explicit.excluded_codes == ("999999",)
    with pytest.raises(ValueError):
        TargetPolicy(version="v1", excluded_codes=("bad",))


def test_reference_bundle_validation(tmp_path: Path) -> None:
    bundle = fictional_reference_bundle(tmp_path)
    assert bundle.schema_version == 1
    assert bundle.version == "fixture-v1"
    assert len(bundle.occupations) == 2
    assert bundle.occupations[0].code == "221111"
    assert bundle.occupations[1].code == "431111"
    assert bundle.occupations[1].excluded is True

    # Duplicate DWA rejected
    with pytest.raises(ValueError):
        ReferenceBundle(
            schema_version=1,
            version="v1",
            sources={"fictional": "v1"},
            licenses={"fictional": "test-only"},
            families=("accounting",),
            dwas=(
                Dwa(id="dwa.1", title="DWA 1", gwa_id="gwa.1"),
                Dwa(id="dwa.1", title="Duplicate", gwa_id="gwa.1"),
            ),
            occupations=(),
            crosswalks=(),
            reference_hash="a" * 64,
        )

    # Missing licence for source rejected
    with pytest.raises(ValueError):
        ReferenceBundle(
            schema_version=1,
            version="v1",
            sources={"source_a": "v1"},
            licenses={},  # missing
            families=("accounting",),
            dwas=(),
            occupations=(),
            crosswalks=(),
            reference_hash="a" * 64,
        )

    # Unknown DWA in occupation weights rejected
    with pytest.raises(ValueError):
        ReferenceBundle(
            schema_version=1,
            version="v1",
            sources={"fictional": "v1"},
            licenses={"fictional": "test-only"},
            families=("accounting",),
            dwas=(Dwa(id="dwa.1", title="DWA 1", gwa_id="gwa.1"),),
            occupations=(
                Occupation(
                    code="221111",
                    title="Accountant",
                    family="accounting",
                    dwa_weights={"dwa.UNKNOWN": 1.0},
                    gwa_ratings={"gwa.1": 4.0},
                ),
            ),
            crosswalks=(),
            reference_hash="a" * 64,
        )


def test_reference_bundle_receipt_is_private_and_required_for_verification(tmp_path: Path) -> None:
    from jobwatch.candidate.reference import verify_reference_snapshot

    bundle = fictional_reference_bundle(tmp_path)
    assert bundle.raw_contents is not None
    assert "raw_contents" not in repr(bundle)
    assert "raw_contents" not in bundle.model_dump(mode="json")
    without_receipt = bundle.model_copy(update={"raw_contents": None})
    with pytest.raises(CandidateError, match="reference_invalid") as exc:
        verify_reference_snapshot(without_receipt)
    assert exc.value.__cause__ is None and exc.value.__context__ is None


def test_crosswalk_validation() -> None:
    cw = Crosswalk(soc="13-2011", anzsco_codes=("221111", "221112"))
    assert cw.soc == "13-2011"
    assert cw.anzsco_codes == ("221111", "221112")

    # Invalid ANZSCO code length in crosswalk rejected
    with pytest.raises(ValueError):
        Crosswalk(soc="13-2011", anzsco_codes=("2211",))




def test_occupation_fit_and_archetype_and_analysis_result() -> None:
    fit = OccupationFit(
        code="221111",
        family="accounting",
        dwa_coverage=0.8,
        gwa_similarity=0.9,
        proximity=0.85,
        evidence_ids=("cv.L1",),
        gap_dwa_ids=(),
        mapping_states=("confirmed",),
        recommendation_status="candidate_path",
    )
    assert fit.recommendation_status == "candidate_path"

    # Nonfinite metric in fit rejected
    with pytest.raises(ValueError):
        OccupationFit(
            code="221111",
            family="accounting",
            dwa_coverage=float("nan"),
            gwa_similarity=0.9,
            proximity=0.85,
            evidence_ids=("cv.L1",),
            gap_dwa_ids=(),
            mapping_states=("confirmed",),
            recommendation_status="candidate_path",
        )

    archetype = ArchetypeProposal(
        codes=("221111",),
        evidence_ids=("cv.L1",),
        shared_gwa_ids=("test.gwa",),
        policy_status="candidate_path",
    )
    assert archetype.policy_status == "candidate_path"

    res = AnalysisResult(
        archetypes=(archetype,),
        schema_version=1,
        run_key="a" * 64,
        evidence_hash="7" * 64,
        reference_hash="8" * 64,
        policy_hash="9" * 64,
        mapping_hash="0" * 64,
        status="available",
        recommendations=(fit,),
        diagnostics=(),
        unmapped_evidence_ids=(),
    )
    assert res.status == "available"
    assert res.schema_version == 1


def test_analysis_result_rejects_non_digest_run_key() -> None:
    with pytest.raises(ValueError):
        AnalysisResult(
            archetypes=(), run_key="run-001", evidence_hash="7" * 64,
            reference_hash=None, policy_hash="9" * 64, mapping_hash="0" * 64,
            status="unmapped", recommendations=(), diagnostics=(), unmapped_evidence_ids=(),
        )


def test_fixtures_builders(tmp_path: Path) -> None:
    prof_root = fictional_profile(tmp_path)
    assert prof_root.is_dir()
    cv_file = prof_root / "cv.md"
    assert cv_file.is_file()
    assert cv_file.read_text(encoding="utf-8") == "# Fictional\n\n## Skills\n- Reconciled ledgers\n"

    ref_file = fictional_reference(tmp_path)
    assert ref_file.is_file()
    data = json.loads(ref_file.read_text(encoding="utf-8"))
    assert data["version"] == "fixture-v1"
    assert data["sources"] == {"fictional": "fixture-v1"}
    assert data["licenses"] == {"fictional": "test-only"}
    assert data["families"] == ["accounting", "hospitality"]
    assert any(occ["code"] == "431111" and occ["excluded"] is True for occ in data["occupations"])


def test_mapping_method_cap_and_validation() -> None:
    valid_kwargs = dict(
        evidence_id="cv.L1",
        source_hash="5" * 64,
        reference_hash="6" * 64,
        dwa_id="test.accounts",
        state="confirmed",
    )
    # Bounded length <= 128 accepted
    m1 = Mapping(method="a" * 128, **valid_kwargs)
    assert len(m1.method) == 128
    m2 = Mapping(method="a", **valid_kwargs)
    assert m2.method == "a"

    # Oversize method > 128 rejected (cap 128 technical ruling)
    with pytest.raises(ValidationError):
        Mapping(method="a" * 129, **valid_kwargs)
    with pytest.raises(ValidationError):
        Mapping(method="x" * 100000, **valid_kwargs)

    # Empty / whitespace method rejected
    with pytest.raises(ValidationError):
        Mapping(method="", **valid_kwargs)
    with pytest.raises(ValidationError):
        Mapping(method="   ", **valid_kwargs)

    # Non-string method rejected
    with pytest.raises(ValidationError):
        Mapping(method=123, **valid_kwargs)


def test_occupation_fit_structural_metric_bounds() -> None:
    valid_kwargs = dict(
        code="221111",
        family="accounting",
        evidence_ids=("cv.L1",),
        gap_dwa_ids=(),
        mapping_states=("confirmed",),
        recommendation_status="candidate_path",
    )
    # Valid bounds [0.0, 1.0] accepted
    fit = OccupationFit(dwa_coverage=0.0, gwa_similarity=1.0, proximity=0.5, **valid_kwargs)
    assert fit.dwa_coverage == 0.0
    assert fit.gwa_similarity == 1.0
    assert fit.proximity == 0.5

    # Controller probe impossible domain values rejected: 12.0, -3.0, 9.0
    with pytest.raises(ValidationError):
        OccupationFit(dwa_coverage=12.0, gwa_similarity=0.5, proximity=0.5, **valid_kwargs)
    with pytest.raises(ValidationError):
        OccupationFit(dwa_coverage=0.5, gwa_similarity=-3.0, proximity=0.5, **valid_kwargs)
    with pytest.raises(ValidationError):
        OccupationFit(dwa_coverage=0.5, gwa_similarity=0.5, proximity=9.0, **valid_kwargs)

    # Negative / out of bounds [0, 1] rejected
    with pytest.raises(ValidationError):
        OccupationFit(dwa_coverage=-0.01, gwa_similarity=0.5, proximity=0.5, **valid_kwargs)
    with pytest.raises(ValidationError):
        OccupationFit(dwa_coverage=1.01, gwa_similarity=0.5, proximity=0.5, **valid_kwargs)
    with pytest.raises(ValidationError):
        OccupationFit(dwa_coverage=0.5, gwa_similarity=1.5, proximity=0.5, **valid_kwargs)
    with pytest.raises(ValidationError):
        OccupationFit(dwa_coverage=0.5, gwa_similarity=0.5, proximity=-1.0, **valid_kwargs)


def test_evidence_bundle_safe_validator_messages_no_private_leak() -> None:
    private_marker = "PRIVATE_PROBE_347"

    # 1. Private marker in source filename path
    with pytest.raises(ValidationError) as exc_info:
        EvidenceBundle(
            sources={f"{private_marker}/bad": "a" * 64},
            items=(),
            bundle_hash="b" * 64,
        )
    err_str = str(exc_info.value)
    err_repr = repr(exc_info.value)
    assert private_marker not in err_str
    assert private_marker not in err_repr

    # 2. Private marker in item id duplicate
    item1 = EvidenceItem(
        id=f"cv.{private_marker}.1",
        kind="skill",
        source_file="cv.md",
        source_hash="a" * 64,
        line=1,
        end_line=1,
        quote="Skill quote",
    )
    with pytest.raises(ValidationError) as exc_info2:
        EvidenceBundle(
            sources={"cv.md": "a" * 64},
            items=(item1, item1),
            bundle_hash="b" * 64,
        )
    assert private_marker not in str(exc_info2.value)
    assert private_marker not in repr(exc_info2.value)


def test_nonstring_family_raises_controlled_validation_error() -> None:
    # OccupationFit with non-string family
    with pytest.raises(ValidationError):
        OccupationFit(
            code="221111",
            family=123,
            dwa_coverage=0.8,
            gwa_similarity=0.9,
            proximity=0.85,
            evidence_ids=("cv.L1",),
            gap_dwa_ids=(),
            mapping_states=("confirmed",),
            recommendation_status="candidate_path",
        )

    # TargetPolicy with non-string family in allowed_families
    with pytest.raises(ValidationError):
        TargetPolicy(version="v1", allowed_families=[123])

    # ReferenceBundle with non-string family in families
    with pytest.raises(ValidationError):
        ReferenceBundle(
            version="v1",
            sources={"s": "1"},
            licenses={"s": "mit"},
            families=[123],
            dwas=(),
            occupations=(),
            crosswalks=(),
            reference_hash="a" * 64,
        )

    # canonicalize_family with non-string raises ValueError, not AttributeError
    with pytest.raises(ValueError):
        canonicalize_family(123)  # type: ignore[arg-type]


def test_reference_metadata_families_validation_and_unknown_family_preservation() -> None:
    base_kwargs = dict(
        version="v1",
        sources={"s": "1"},
        licenses={"s": "mit"},
        dwas=(Dwa(id="dwa.1", title="Dwa 1", gwa_id="gwa.1"),),
        crosswalks=(),
        reference_hash="a" * 64,
    )
    # Empty families rejected
    with pytest.raises(ValidationError):
        ReferenceBundle(families=(), occupations=(), **base_kwargs)

    # Empty or whitespace family in list rejected
    with pytest.raises(ValidationError):
        ReferenceBundle(families=("accounting", "   "), occupations=(), **base_kwargs)
    with pytest.raises(ValidationError):
        ReferenceBundle(families=("",), occupations=(), **base_kwargs)

    # Duplicate canonical families rejected
    with pytest.raises(ValidationError):
        ReferenceBundle(families=("accounting", "Accounting"), occupations=(), **base_kwargs)
    with pytest.raises(ValidationError):
        ReferenceBundle(families=("accounting", "accounting_"), occupations=(), **base_kwargs)

    # Unknown occupation family is PRESERVED for diagnostic later, not rejected at schema level
    occ = Occupation(
        code="221111",
        title="Accountant",
        family="unknown_future_family",
        dwa_weights={"dwa.1": 1.0},
        gwa_ratings={"gwa.1": 4.0},
    )
    ref = ReferenceBundle(
        families=("accounting",),
        occupations=(occ,),
        **base_kwargs,
    )
    assert ref.occupations[0].family == "unknown_future_family"


@pytest.mark.parametrize(
    "factory,marker",
    [
        (
            lambda key: Occupation(
                code="221111", title="Accountant", family="accounting",
                dwa_weights={key: True}, gwa_ratings={"gwa.1": 4.0},
            ),
            "PRIVATE_DWA_KEY_PROBE",
        ),
        (
            lambda key: Occupation(
                code="221111", title="Accountant", family="accounting",
                dwa_weights={"dwa.1": 1.0}, gwa_ratings={key: True},
            ),
            "PRIVATE_GWA_KEY_PROBE",
        ),
        (
            lambda key: EvidenceBundle(
                sources={key: False}, items=(), bundle_hash="a" * 64,
            ),
            "PRIVATE_EVIDENCE_SOURCE_PROBE",
        ),
        (
            lambda key: EvidenceBundle(
                sources={}, items=(), bundle_hash="a" * 64, contents={key: "private"},
            ),
            "PRIVATE_EVIDENCE_CONTENT_PROBE",
        ),
        (
            lambda key: ReferenceBundle(
                version="v1", sources={key: ""}, licenses={key: "test"},
                families=("accounting",), dwas=(), occupations=(), crosswalks=(),
                reference_hash="a" * 64,
            ),
            "PRIVATE_REFERENCE_SOURCE_PROBE",
        ),
        (
            lambda key: ReferenceBundle(
                version="v1", sources={"source": "v1"}, licenses={key: "test"},
                families=("accounting",), dwas=(), occupations=(), crosswalks=(),
                reference_hash="a" * 64,
            ),
            "PRIVATE_REFERENCE_LICENSE_PROBE",
        ),
    ],
)
def test_arbitrary_mapping_key_never_appears_in_validation_error(factory, marker: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        factory(marker)
    assert marker not in str(exc_info.value)
    assert marker not in repr(exc_info.value)


def test_an_unknown_field_name_is_dropped_and_never_surfaces() -> None:
    """Strict schemas were removed on the owner's direction (2026-10-19), so an unknown field no longer
    raises. The privacy half of the guarantee still has to hold: the name and value must not survive."""
    marker = "PRIVATE_UNKNOWN_FIELD_PROBE"
    occupation = Occupation(
        code="221111", title="Accountant", family="accounting",
        dwa_weights={"dwa.1": 1.0}, gwa_ratings={"gwa.1": 4.0}, **{marker: "sensitive"},
    )
    assert not hasattr(occupation, marker)
    for rendered in (str(occupation), repr(occupation), str(occupation.model_dump()), occupation.model_dump_json()):
        assert marker not in rendered and "sensitive" not in rendered
    with pytest.raises(ValidationError) as exc_info:           # a real validation error still hides it
        Occupation(code="221111", title="Accountant", family="accounting",
                   dwa_weights={"dwa.1": "not-a-number"}, gwa_ratings={"gwa.1": 4.0}, **{marker: "sensitive"})
    assert marker not in str(exc_info.value) and marker not in repr(exc_info.value)


