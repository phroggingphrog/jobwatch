from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

HEX_64_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SIX_DIGIT_PATTERN = re.compile(r"^\d{6}$")


def _validate_mapping_primitives(value: Any, value_types: type | tuple[type, ...]) -> Any:
    if not isinstance(value, dict):
        raise ValueError("mapping must contain valid primitive entries")
    for key, item in value.items():
        if type(key) is not str or type(item) not in (
            value_types if isinstance(value_types, tuple) else (value_types,)
        ):
            raise ValueError("mapping must contain valid primitive entries")
    return value


class StrictFrozen(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        frozen=True,
        strict=False,
        hide_input_in_errors=True,
    )


class CandidateError(ValueError):
    """Safe public error carrying only fixed codes and no raw private text/context."""
    pass


def digest(value: object) -> str:
    """Deterministic SHA-256 digest of arbitrary serializable object."""
    data = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def content_hash(value: bytes) -> str:
    """Direct SHA-256 hex digest of raw bytes."""
    return hashlib.sha256(value).hexdigest()


def validate_hash_64(val: str, field_name: str = "hash") -> str:
    if not isinstance(val, str) or not HEX_64_PATTERN.match(val):
        raise ValueError("hash must be a 64-character lowercase hex string")
    return val


FAMILY_ALIASES = {"accounting_analysis": "accounting"}


def canonicalize_family(family: str) -> str:
    """Normalize spelling and explicit semantic aliases; never guess an unknown family."""
    if not isinstance(family, str):
        raise ValueError("family must be a string")
    s = family.casefold()
    s = re.sub(r"[\s\-_]+", "_", s)
    normalized = s.strip("_")
    return FAMILY_ALIASES.get(normalized, normalized)


# Classification vocabulary shared by every person: a family is a kind of work, not a preference.
# Which families a person does not want comes from their own files (person.excluded_families()).
KNOWN_FAMILIES: tuple[str, ...] = (
    "accounting",
    "finance_clerical",
    "back_office_admin",
    "data_analyst",
    "business_analyst",
    "finance_analyst",
    "business_program",
    "finance_program",
    "operations_program",
    "analytics_program",
    "customer_service",
    "hospitality",
    "retail",
    "shop_floor",
    "engineering",
    "health",
    "education",
    "trades",
    "it",
    "sales_marketing",
    "other",
)

# Neutral extraction vocabulary: a classification is not a policy decision.
JOB_ROLE_FAMILIES = KNOWN_FAMILIES + ("unknown",)


def excluded_families() -> tuple[str, ...]:
    """Families this person does not want (interests_and_criteria.yaml target_roles.not_wanted)."""
    from .person import excluded_families as _ef
    return tuple(canonicalize_family(f) for f in _ef())


def default_allowed_families() -> tuple[str, ...]:
    """Every known family except the ones this person does not want."""
    no = excluded_families()
    return tuple(f for f in KNOWN_FAMILIES if f not in no)


def __getattr__(name: str):  # these stay importable, read from the person's file
    if name == "EXCLUDED_FAMILIES":
        return excluded_families()
    if name in ("DEFAULT_ALLOWED_FAMILIES", "ALLOWED_FAMILIES"):
        return default_allowed_families()
    raise AttributeError(name)


MINIMUM_EXCLUDED_CODES: tuple[str, ...] = ("431111", "541211")


class EducationStatusEvidence(StrictFrozen):
    source_file: Literal["profile.yaml"]
    source_hash: str
    line: int
    quote: Literal["completed", "current"] = Field(..., repr=False)
    education_index: int

    @field_validator("source_hash")
    @classmethod
    def _validate_source_hash(cls, v: str) -> str:
        return validate_hash_64(v, "source_hash")

    @field_validator("line")
    @classmethod
    def _validate_line(cls, v: int) -> int:
        if v < 1:
            raise ValueError("line must be >= 1")
        return v

    @field_validator("education_index")
    @classmethod
    def _validate_education_index(cls, v: int) -> int:
        if v < 0:
            raise ValueError("education_index must be >= 0")
        return v


class EvidenceItem(StrictFrozen):
    id: str
    kind: Literal["role", "education", "skill", "achievement", "cert"]
    source_file: Literal["master_resume.md", "cv.md", "profile.yaml"]
    source_hash: str
    line: int
    end_line: int
    quote: str = Field(..., repr=False)
    education_status: Literal["completed", "current", "unknown", "not_applicable"] = "not_applicable"
    status_evidence: EducationStatusEvidence | None = None

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("id must be nonempty")
        return v

    @field_validator("source_hash")
    @classmethod
    def _validate_source_hash(cls, v: str) -> str:
        return validate_hash_64(v, "source_hash")

    @field_validator("line")
    @classmethod
    def _validate_line(cls, v: int) -> int:
        if v < 1:
            raise ValueError("line must be >= 1")
        return v

    @field_validator("quote")
    @classmethod
    def _validate_quote(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("quote must be nonempty")
        return v

    @model_validator(mode="before")
    @classmethod
    def _validate_before(cls, data: Any) -> Any:
        if isinstance(data, dict):
            kind = data.get("kind")
            if kind in ("education", "cert") and "education_status" not in data:
                data = dict(data)
                data["education_status"] = "unknown"
        return data

    @model_validator(mode="after")
    def _validate_invariants(self) -> EvidenceItem:
        if self.end_line < self.line:
            raise ValueError("end_line must be >= line")

        if self.kind in ("education", "cert"):
            if self.education_status == "not_applicable":
                raise ValueError("education and cert items cannot have education_status 'not_applicable'")
            if self.education_status in ("completed", "current"):
                if self.status_evidence is None:
                    raise ValueError("status requires valid status_evidence")
                if self.status_evidence.quote != self.education_status:
                    raise ValueError("status_evidence quote must match education_status")
            elif self.education_status == "unknown":
                if self.status_evidence is not None:
                    raise ValueError("unknown status cannot have status_evidence")
        else:
            if self.education_status != "not_applicable":
                raise ValueError("non-education items must have education_status 'not_applicable'")
            if self.status_evidence is not None:
                raise ValueError("non-education items cannot have status_evidence")

        return self


def compute_bundle_hash(
    sources: dict[str, str],
    items: tuple[EvidenceItem, ...],
    dropped_contact_count: int = 0,
) -> str:
    canonical_payload = {
        "sources": sources,
        "items": [item.model_dump(mode="json") for item in items],
        "dropped_contact_count": dropped_contact_count,
    }
    return digest(canonical_payload)


class EvidenceBundle(StrictFrozen):
    schema_version: Literal[1] = 1
    sources: dict[str, str]
    items: tuple[EvidenceItem, ...]
    bundle_hash: str
    dropped_contact_count: int = 0
    contents: dict[str, bytes] = Field(default_factory=dict, repr=False, exclude=True)

    @field_validator("sources", mode="before")
    @classmethod
    def _validate_sources_shape(cls, v: Any) -> Any:
        return _validate_mapping_primitives(v, str)

    @field_validator("contents", mode="before")
    @classmethod
    def _validate_contents_shape(cls, v: Any) -> Any:
        return _validate_mapping_primitives(v, bytes)

    @field_validator("items", mode="before")
    @classmethod
    def _coerce_items_tuple(cls, v: Any) -> Any:
        if isinstance(v, list):
            return tuple(v)
        return v

    @field_validator("bundle_hash")
    @classmethod
    def _validate_bundle_hash(cls, v: str) -> str:
        return validate_hash_64(v, "bundle_hash")

    @field_validator("dropped_contact_count")
    @classmethod
    def _validate_dropped_contact_count(cls, v: int) -> int:
        if v < 0:
            raise ValueError("dropped_contact_count must be >= 0")
        return v

    @field_validator("sources")
    @classmethod
    def _validate_sources(cls, v: dict[str, str]) -> dict[str, str]:
        for filename, shash in v.items():
            if "/" in filename or "\\" in filename or ".." in filename:
                raise ValueError("source filename must be a plain name, not a path")
            validate_hash_64(shash, "source hash")
        return dict(v)

    @model_validator(mode="after")
    def _validate_bundle(self) -> EvidenceBundle:
        seen_ids: set[str] = set()
        for item in self.items:
            if item.id in seen_ids:
                raise ValueError("duplicate evidence id")
            seen_ids.add(item.id)

            if item.source_file not in self.sources:
                raise ValueError("item source file not in bundle sources")
            if item.source_hash != self.sources[item.source_file]:
                raise ValueError("item source hash mismatch")

            if item.status_evidence is not None:
                if item.status_evidence.source_file not in self.sources:
                    raise ValueError("status evidence source not in bundle sources")
                if item.status_evidence.source_hash != self.sources[item.status_evidence.source_file]:
                    raise ValueError("status evidence source hash mismatch")

        expected_hash = compute_bundle_hash(self.sources, self.items, self.dropped_contact_count)
        if self.bundle_hash != expected_hash:
            raise ValueError("bundle_hash mismatch against canonical sources and items")

        return self


class Dwa(StrictFrozen):
    id: str
    title: str
    gwa_id: str

    @field_validator("id", "title", "gwa_id")
    @classmethod
    def _validate_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("string field must be nonempty")
        return v


class Occupation(StrictFrozen):
    code: str
    title: str
    family: str
    excluded: bool = False
    dwa_weights: dict[str, float]
    gwa_ratings: dict[str, float]

    @field_validator("code")
    @classmethod
    def _validate_code(cls, v: str) -> str:
        if not SIX_DIGIT_PATTERN.match(v):
            raise ValueError("occupation code must be six digits")
        return v

    @field_validator("title")
    @classmethod
    def _validate_title(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("title must be nonempty")
        return v

    @field_validator("family", mode="before")
    @classmethod
    def _validate_family(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("family must be a string")
        canon = canonicalize_family(v)
        if not canon:
            raise ValueError("family cannot be empty after canonicalization")
        return canon

    @field_validator("dwa_weights", "gwa_ratings", mode="before")
    @classmethod
    def _validate_numeric_mapping_shape(cls, v: Any) -> Any:
        return _validate_mapping_primitives(v, (int, float))

    @field_validator("dwa_weights")
    @classmethod
    def _validate_dwa_weights(cls, v: dict[str, float]) -> dict[str, float]:
        for dwa_id, w in v.items():
            if type(w) is bool or not isinstance(w, (int, float)) or not math.isfinite(w) or w <= 0.0:
                raise ValueError("dwa weight must be finite > 0")
        return dict(v)

    @field_validator("gwa_ratings")
    @classmethod
    def _validate_gwa_ratings(cls, v: dict[str, float]) -> dict[str, float]:
        for gwa_id, r in v.items():
            if type(r) is bool or not isinstance(r, (int, float)) or not math.isfinite(r) or not (0.0 <= r <= 5.0):
                raise ValueError("gwa rating must be finite between 0 and 5")
        return dict(v)


class Crosswalk(StrictFrozen):
    soc: str
    anzsco_codes: tuple[str, ...]

    @field_validator("anzsco_codes", mode="before")
    @classmethod
    def _coerce_anzsco_tuple(cls, v: Any) -> Any:
        if isinstance(v, list):
            return tuple(v)
        return v

    @field_validator("soc")
    @classmethod
    def _validate_soc(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("soc must be nonempty")
        return v

    @field_validator("anzsco_codes")
    @classmethod
    def _validate_anzsco_codes(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not v:
            raise ValueError("anzsco_codes must be non-empty")
        for c in v:
            if not SIX_DIGIT_PATTERN.match(c):
                raise ValueError("anzsco code must be six digits")
        return tuple(v)


class ReferenceBundle(StrictFrozen):
    schema_version: Literal[1] = 1
    version: str
    sources: dict[str, str]
    licenses: dict[str, str]
    families: tuple[str, ...]
    dwas: tuple[Dwa, ...]
    occupations: tuple[Occupation, ...]
    crosswalks: tuple[Crosswalk, ...]
    reference_hash: str
    raw_contents: bytes | None = Field(default=None, repr=False, exclude=True)

    @field_validator("raw_contents", mode="before")
    @classmethod
    def _validate_raw_contents(cls, v: Any) -> bytes | None:
        if v is not None and type(v) is not bytes:
            raise ValueError("raw reference receipt must be bytes")
        return v

    @field_validator("dwas", "occupations", "crosswalks", mode="before")
    @classmethod
    def _coerce_bundle_tuples(cls, v: Any) -> Any:
        if isinstance(v, list):
            return tuple(v)
        return v

    @field_validator("reference_hash")
    @classmethod
    def _validate_reference_hash(cls, v: str) -> str:
        return validate_hash_64(v, "reference_hash")

    @field_validator("version")
    @classmethod
    def _validate_version(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("version must be nonempty")
        return v

    @field_validator("sources", "licenses", mode="before")
    @classmethod
    def _validate_metadata_mapping_shape(cls, v: Any) -> Any:
        return _validate_mapping_primitives(v, str)

    @field_validator("sources")
    @classmethod
    def _validate_sources(cls, v: dict[str, str]) -> dict[str, str]:
        if not v:
            raise ValueError("at least one source and version is required")
        for s, ver in v.items():
            if not s.strip() or not ver.strip():
                raise ValueError("source and version must be nonempty")
        return dict(v)

    @field_validator("licenses")
    @classmethod
    def _validate_licenses(cls, v: dict[str, str]) -> dict[str, str]:
        if not v:
            raise ValueError("at least one licence is required")
        for s, lic in v.items():
            if not s.strip() or not lic.strip():
                raise ValueError("licence identifier must be nonempty")
        return dict(v)

    @field_validator("families", mode="before")
    @classmethod
    def _validate_families(cls, v: Any) -> tuple[str, ...]:
        if not isinstance(v, (list, tuple)):
            raise ValueError("families must be a sequence")
        if not v:
            raise ValueError("families must be nonempty")
        for f in v:
            if not isinstance(f, str):
                raise ValueError("family must be a string")
        canon_list = [canonicalize_family(f) for f in v]
        seen: set[str] = set()
        for f in canon_list:
            if not f:
                raise ValueError("family cannot be empty")
            if f in seen:
                raise ValueError("duplicate canonical family")
            seen.add(f)
        return tuple(canon_list)

    @model_validator(mode="after")
    def _validate_bundle(self) -> ReferenceBundle:
        if set(self.sources.keys()) != set(self.licenses.keys()):
            raise ValueError("sources and licenses metadata must match exactly")

        dwa_ids: set[str] = set()
        gwa_ids: set[str] = set()
        for d in self.dwas:
            if d.id in dwa_ids:
                raise ValueError("duplicate dwa id")
            dwa_ids.add(d.id)
            gwa_ids.add(d.gwa_id)

        occ_codes: set[str] = set()
        for d in self.dwas:
            if len(d.id) > 20 or len(d.gwa_id) > 20:
                raise ValueError("occupation activity identifier is too long")
            if d.id.startswith("test."):
                if not d.gwa_id.startswith("test."):
                    raise ValueError("synthetic gwa identifier must use test namespace")
            elif len(d.id.split(".")) >= 6:
                dwa_parts = d.id.split(".")
                gwa_parts = d.gwa_id.split(".")
                if len(gwa_parts) != 5 or dwa_parts[:5] != gwa_parts:
                    raise ValueError("declared gwa must match hierarchical dwa prefix")

        for o in self.occupations:
            if o.code in occ_codes:
                raise ValueError("duplicate occupation code")
            occ_codes.add(o.code)

            for wid in o.dwa_weights:
                if wid not in dwa_ids:
                    raise ValueError("occupation references unknown dwa")
            for gid in o.gwa_ratings:
                if gid not in gwa_ids:
                    raise ValueError("occupation references unknown gwa")

        socs: set[str] = set()
        for cw in self.crosswalks:
            if cw.soc in socs:
                raise ValueError("duplicate crosswalk soc")
            socs.add(cw.soc)
            for c in cw.anzsco_codes:
                if c not in occ_codes:
                    raise ValueError("crosswalk references unknown anzsco code")

        return self


class Mapping(StrictFrozen):
    evidence_id: str
    source_hash: str
    reference_hash: str
    dwa_id: str
    method: str = Field(..., max_length=128)
    state: Literal["suggested", "confirmed"]

    @field_validator("source_hash")
    @classmethod
    def _validate_source_hash(cls, v: str) -> str:
        return validate_hash_64(v, "source_hash")

    @field_validator("reference_hash")
    @classmethod
    def _validate_reference_hash(cls, v: str) -> str:
        return validate_hash_64(v, "reference_hash")

    @field_validator("evidence_id", "dwa_id", "method")
    @classmethod
    def _validate_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("string field must be nonempty")
        return v

    @field_validator("method")
    @classmethod
    def _validate_method_bound(cls, v: str) -> str:
        if len(v) > 128:
            raise ValueError("method length must be <= 128")
        return v


class TargetPolicy(StrictFrozen):
    version: str
    allowed_families: tuple[str, ...] = Field(default_factory=default_allowed_families)
    excluded_codes: tuple[str, ...] = MINIMUM_EXCLUDED_CODES
    # True (the legacy default) demands MINIMUM_EXCLUDED_CODES in excluded_codes. It is omitted from the serialised
    # form while True so every existing policy JSON, digest and run key stays byte-identical.
    require_minimum_excluded_codes: bool = True

    @model_serializer(mode="wrap")
    def _omit_historical_default(self, handler):
        data = handler(self)
        if self.require_minimum_excluded_codes is True:
            data.pop("require_minimum_excluded_codes", None)
        return data

    @field_validator("version")
    @classmethod
    def _validate_version(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("version must be nonempty")
        return v

    @field_validator("allowed_families", mode="before")
    @classmethod
    def _validate_allowed_families(cls, v: Any) -> tuple[str, ...]:
        if not isinstance(v, (list, tuple)):
            raise ValueError("allowed_families must be a sequence")
        for f in v:
            if not isinstance(f, str):
                raise ValueError("family must be a string")
        canon = tuple(canonicalize_family(f) for f in v)
        for f in canon:
            if not f:
                raise ValueError("family cannot be empty")
        return canon

    @field_validator("excluded_codes", mode="before")
    @classmethod
    def _coerce_excluded_codes(cls, v: Any) -> Any:
        if isinstance(v, list):
            return tuple(v)
        return v

    @field_validator("excluded_codes")
    @classmethod
    def _validate_excluded_codes(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for c in v:
            if not SIX_DIGIT_PATTERN.match(c):
                raise ValueError("excluded code must be six digits")
        return tuple(dict.fromkeys(v))

    @model_validator(mode="after")
    def _validate_minimum_excluded_codes(self):
        if self.require_minimum_excluded_codes:
            # The person-file family check applies only to the legacy policy; the neutral variant reads no person file.
            banned = excluded_families()
            for f in self.allowed_families:
                if f in banned:
                    raise ValueError("family is in the person's not_wanted families")
            for min_code in MINIMUM_EXCLUDED_CODES:
                if min_code not in self.excluded_codes:
                    raise ValueError("immutable minimum excluded code cannot be removed")
        return self


class OccupationFit(StrictFrozen):
    code: str
    family: str
    dwa_coverage: float = Field(..., ge=0.0, le=1.0)
    gwa_similarity: float = Field(..., ge=0.0, le=1.0)
    proximity: float = Field(..., ge=0.0, le=1.0)
    evidence_ids: tuple[str, ...]
    gap_dwa_ids: tuple[str, ...]
    mapping_states: tuple[Literal["suggested", "confirmed"], ...]
    recommendation_status: Literal[
        "candidate_path",
        "suggested_path",
        "excluded",
        "not_target",
        "unsupported",
        "education_unverified",
        "taxonomy_conflict",
    ]

    @field_validator("evidence_ids", "gap_dwa_ids", "mapping_states", mode="before")
    @classmethod
    def _coerce_fit_tuples(cls, v: Any) -> Any:
        if isinstance(v, list):
            return tuple(v)
        return v

    @field_validator("code")
    @classmethod
    def _validate_code(cls, v: str) -> str:
        if not SIX_DIGIT_PATTERN.match(v):
            raise ValueError("code must be six digits")
        return v

    @field_validator("family", mode="before")
    @classmethod
    def _validate_family(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("family must be a string")
        canon = canonicalize_family(v)
        if not canon:
            raise ValueError("family cannot be empty")
        return canon

    @field_validator("dwa_coverage", "gwa_similarity", "proximity")
    @classmethod
    def _validate_finite(cls, v: float) -> float:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError("metric must be finite float")
        if not (0.0 <= float(v) <= 1.0):
            raise ValueError("metric must be between 0.0 and 1.0")
        return float(v)


class ArchetypeProposal(StrictFrozen):
    codes: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    shared_gwa_ids: tuple[str, ...]
    policy_status: Literal["candidate_path", "diagnostic"]

    @field_validator("codes", "evidence_ids", "shared_gwa_ids", mode="before")
    @classmethod
    def _coerce_archetype_tuples(cls, v: Any) -> Any:
        if isinstance(v, list):
            return tuple(v)
        return v

    @field_validator("codes")
    @classmethod
    def _validate_codes(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for c in v:
            if not SIX_DIGIT_PATTERN.match(c):
                raise ValueError("code must be six digits")
        return tuple(v)


class AnalysisResult(StrictFrozen):
    archetypes: tuple[ArchetypeProposal, ...]
    schema_version: Literal[1] = 1
    run_key: str
    evidence_hash: str
    reference_hash: str | None
    policy_hash: str
    mapping_hash: str
    status: Literal["available", "reference_unavailable", "unmapped"]
    recommendations: tuple[OccupationFit, ...]
    diagnostics: tuple[OccupationFit, ...]
    unmapped_evidence_ids: tuple[str, ...]

    @field_validator(
        "archetypes", "recommendations", "diagnostics", "unmapped_evidence_ids", mode="before"
    )
    @classmethod
    def _coerce_analysis_tuples(cls, v: Any) -> Any:
        if isinstance(v, list):
            return tuple(v)
        return v

    @field_validator("evidence_hash", "policy_hash", "mapping_hash")
    @classmethod
    def _validate_required_hashes(cls, v: str) -> str:
        return validate_hash_64(v)

    @field_validator("reference_hash")
    @classmethod
    def _validate_ref_hash(cls, v: str | None) -> str | None:
        if v is not None:
            return validate_hash_64(v)
        return v

    @field_validator("run_key")
    @classmethod
    def _validate_run_key(cls, v: str) -> str:
        return validate_hash_64(v, "run_key")
