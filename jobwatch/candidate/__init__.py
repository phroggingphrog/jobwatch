"""Candidate analysis contracts, vocabulary, and primitives."""

from .evidence import snapshot_evidence, validate_annotation, verify_evidence_snapshot
from .reference import load_reference, crosswalk_codes
from .mapping import validate_mappings
from .policy import default_policy
from .analysis import analyse_candidate, analysis_metadata
from .contracts import (
    DEFAULT_ALLOWED_FAMILIES,
    EXCLUDED_FAMILIES,
    MINIMUM_EXCLUDED_CODES,
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
    StrictFrozen,
    TargetPolicy,
    canonicalize_family,
    compute_bundle_hash,
    content_hash,
    digest,
)

__all__ = [
    "DEFAULT_ALLOWED_FAMILIES",
    "EXCLUDED_FAMILIES",
    "MINIMUM_EXCLUDED_CODES",
    "AnalysisResult",
    "ArchetypeProposal",
    "CandidateError",
    "Crosswalk",
    "Dwa",
    "EducationStatusEvidence",
    "EvidenceBundle",
    "EvidenceItem",
    "Mapping",
    "Occupation",
    "OccupationFit",
    "ReferenceBundle",
    "StrictFrozen",
    "TargetPolicy",
    "canonicalize_family",
    "compute_bundle_hash",
    "content_hash",
    "digest",
    "snapshot_evidence",
    "validate_annotation",
    "verify_evidence_snapshot",
    "load_reference",
    "crosswalk_codes",
    "validate_mappings",
    "default_policy",
    "analyse_candidate",
    "analysis_metadata",
]
