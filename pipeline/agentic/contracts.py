"""Strict serialized contracts for the bounded agentic career-operations pipeline.

These schemas validate payload shape and bind supplied hashes; they do not authorize
persistence, rendering, external calls, review trust, or application submission.
SourceCitation quotes are private fields but remain present in serialized payloads;
consumers must resolve each (source_id, content_hash, quote) against exact source text.
Nested mappings remain mutable despite frozen Pydantic models: consumers must deep-snapshot
inputs and revalidate hashes at trust boundaries. BudgetCheckpoint is a wire contract only:
durable revision-CAS and atomic reservations,
plus idempotent settlement by reservation_id, are consumer responsibilities. A restart
must conservatively retain the full charge for reserved/dispatched/ambiguous work.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

from jobwatch.candidate.contracts import digest
from pipeline.schemas import JobFacts

HEX = re.compile(r"^[0-9a-f]{64}$")


class PublicAgenticError(ValueError):
    """Safe fixed-code exception. Never include private input or raw validation details."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


# Stable consumer-facing name; both identifiers refer to the same exception type.
AgenticError = PublicAgenticError


def _safe_raise(code: str) -> None:
    # Raising outside a caught exception keeps both implicit context and cause empty.
    raise PublicAgenticError(code) from None


def _finite_json(value: Any, max_bytes: int) -> Any:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                             allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        raise ValueError("content must be finite JSON") from None
    if len(encoded) > max_bytes:
        raise ValueError("content exceeds limit")
    return value


class StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=False, frozen=True, hide_input_in_errors=True)


class SourceCitation(StrictFrozen):
    source_id: str = Field(min_length=1, max_length=128)
    content_hash: str
    quote: str = Field(min_length=1, max_length=200_000, repr=False)

    @field_validator("content_hash")
    @classmethod
    def _hash(cls, value: str) -> str:
        if not HEX.fullmatch(value):
            raise ValueError("invalid hash")
        return value


def validate_citations(citations: tuple[SourceCitation, ...], sources: dict[str, tuple[str, str]]) -> None:
    valid = True
    try:
        if type(citations) is not tuple or type(sources) is not dict:
            valid = False
        else:
            for citation in citations:
                if type(citation) is not SourceCitation or type(citation.source_id) is not str:
                    valid = False
                    break
                source = sources.get(citation.source_id)
                if type(source) is not tuple or len(source) != 2:
                    valid = False
                    break
                source_hash, text = source
                if type(source_hash) is not str or type(text) is not str:
                    valid = False
                    break
                # Reinstantiate to re-run strict validators: model_copy(update=...) bypasses them.
                checked = SourceCitation.model_validate(citation.model_dump())
                actual_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                if (not HEX.fullmatch(source_hash) or source_hash != actual_hash
                        or checked.content_hash != actual_hash or checked.quote not in text):
                    valid = False
                    break
    except Exception:
        valid = False
    if not valid:
        _safe_raise("invalid_citation")


class AgenticScreeningAnswer(StrictFrozen):
    question: str = Field(min_length=3, max_length=400)
    answer: str = Field(max_length=1200, repr=False)
    source: Literal["evidence", "owner_to_answer"]
    citations: tuple[SourceCitation, ...] = Field(default=(), repr=False)

    @model_validator(mode="before")
    @classmethod
    def _blank_owner_answers(cls, data):
        # Questions only the owner may answer (work rights, salary...) are kept blank, not grounds to drop the draft.
        if isinstance(data, dict) and data.get("source") == "owner_to_answer":
            data = {**data, "answer": "", "citations": ()}
        return data

    @model_validator(mode="after")
    def _source_rules(self):
        if self.source == "evidence":
            if self.answer.strip() and not self.citations:
                raise ValueError("evidence answer needs citations")
            if not self.answer.strip():
                raise ValueError("evidence answer must be nonblank")
        elif self.answer.strip() or self.citations:
            raise ValueError("owner answer must remain unanswered")
        return self


def answers_content_hash(answers: tuple[AgenticScreeningAnswer, ...]) -> str:
    """Hash full validated answer payload including citation provenance."""
    try:
        if type(answers) is not tuple:
            raise ValueError
        checked = tuple(AgenticScreeningAnswer.model_validate(a.model_dump()) for a in answers)
        result = digest([a.model_dump(mode="json") for a in checked])
    except Exception:
        pass
    else:
        return result
    _safe_raise("invalid_answers")


class Requirement(StrictFrozen):
    id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=4000)
    tier: Literal["stated", "structural", "inferred"]
    importance: Literal["critical", "high", "meaningful", "preferred", "low_signal"]
    jd_signal: SourceCitation | None = None
    blocker: bool = Field(default=False, description=(
        "Prerequisite requiring candidate proof before applying. Explicit checks to be completed "
        "by the successful candidate are future hiring conditions, not existing proof requirements. "
        "Existing-clearance requirements and essential conditions with unclear timing remain blockers."
    ))

    @model_validator(mode="after")
    def _tier_rules(self):
        if self.tier == "inferred":
            if self.jd_signal is not None or self.importance in ("critical", "high") or self.blocker:
                raise ValueError("unsupported inferred requirement")
        elif self.jd_signal is None:
            raise ValueError("stated and structural requirements need a citation")
        return self


class RequirementSet(StrictFrozen):
    ad_hash: str
    requirements: tuple[Requirement, ...]

    @field_validator("ad_hash")
    @classmethod
    def _hash(cls, value: str) -> str:
        if not HEX.fullmatch(value):
            raise ValueError("invalid hash")
        return value

    @model_validator(mode="after")
    def _unique_ids(self):
        ids = [r.id for r in self.requirements]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate requirement id")
        return self

    @property
    def requirement_hash(self) -> str:
        return digest(self.model_dump(mode="json"))


def check_frozen_requirements(original: RequirementSet, current: RequirementSet) -> None:
    try:
        if type(original) is not RequirementSet or type(current) is not RequirementSet:
            _safe_raise("requirements_changed")
        original = RequirementSet.model_validate(original.model_dump())
        current = RequirementSet.model_validate(current.model_dump())
        if original.model_dump(mode="json") != current.model_dump(mode="json"):
            _safe_raise("requirements_changed")
    except PublicAgenticError:
        raise
    except Exception:
        pass
    else:
        return
    _safe_raise("requirements_changed")


class RunKey(StrictFrozen):
    """Identity uses full captured ad, evidence bundle, optional authenticated analysis run key,
    and a config digest over complete owner policy plus runtime/rubric configuration. Candidate
    hash is None only when candidate-analysis reference is explicitly unavailable; one service
    must create and propagate the canonical key. Hashes are identifiers, not proof or authority.
    """
    posting_id: int = Field(ge=1)
    ad_hash: str
    evidence_hash: str
    rubric_version: str = Field(min_length=1, max_length=64)
    config_hash: str
    candidate_hash: str | None = None

    @field_validator("ad_hash", "evidence_hash", "config_hash", "candidate_hash")
    @classmethod
    def _hash(cls, value):
        if value is not None and not HEX.fullmatch(value):
            raise ValueError("invalid hash")
        return value

    @property
    def value(self) -> str:
        return digest(self.model_dump(mode="json"))


class AgenticGateDecision(StrictFrozen):
    route: Literal["draft", "archive", "hold"]
    reason: Literal["eligible", "hard_gate", "insufficient_evidence", "verification_required",
                    "score_below_threshold", "policy_excluded"]
    global_score: float
    run_key: RunKey

    @field_validator("global_score")
    @classmethod
    def _score(cls, value: float) -> float:
        if type(value) not in (float, int) or not math.isfinite(value) or not 1 <= value <= 5:
            raise ValueError("invalid score")
        return float(value)


class EvidenceJudgment(StrictFrozen):
    """A model judgment, not a calibrated probability or an eligibility decision."""
    status: Literal["demonstrated", "partial", "unknown", "contradicted", "not_applicable"]
    rationale: str = Field(min_length=1, max_length=2000)
    reviewed_evidence_ids: tuple[str, ...] = Field(max_length=100)
    contradiction_evidence: tuple[SourceCitation, ...] = Field(default=(), max_length=10, repr=False)
    open_question: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def _contradiction_proof(self):
        if bool(self.contradiction_evidence) != (self.status == "contradicted"):
            raise ValueError("contradiction needs explicit primary evidence")
        if self.status in {"partial", "unknown", "contradicted"} and not self.open_question.strip():
            raise ValueError("unresolved judgment needs a question for review")
        if len(self.reviewed_evidence_ids) != len(set(self.reviewed_evidence_ids)):
            raise ValueError("duplicate reviewed evidence")
        return self


class RequirementMatch(StrictFrozen):
    requirement_id: str = Field(min_length=1, max_length=64)
    match: Literal["strong", "partial", "missing", "not_applicable"]
    evidence: tuple[SourceCitation, ...]
    risk: str = Field(default="", max_length=4000)
    mitigation: str = Field(default="", max_length=4000)
    # Absent on historical evaluations; never infer a richer judgment on read.
    judgment: EvidenceJudgment | None = None

    @model_serializer(mode="wrap")
    def _historical_payload(self, handler):
        result = handler(self)
        if self.judgment is None:
            result.pop("judgment", None)
        return result

    @model_validator(mode="after")
    def _strong_cited(self):
        if self.match == "strong" and not self.evidence:
            raise ValueError("strong match needs citation")
        if self.judgment is not None:
            expected = {"demonstrated": "strong", "partial": "partial", "unknown": "missing",
                        "contradicted": "missing", "not_applicable": "not_applicable"}
            if self.match != expected[self.judgment.status]:
                raise ValueError("judgment disagrees with compatibility match")
        return self


class Dimension(StrictFrozen):
    score: float
    reason: str = Field(min_length=1, max_length=4000, repr=False)

    @field_validator("score")
    @classmethod
    def _score(cls, value: float) -> float:
        if type(value) not in (float, int) or not math.isfinite(value) or not 1 <= value <= 5:
            raise ValueError("invalid score")
        return float(value)


REPORT_FIELDS = ("A", "B", "C", "D", "E", "F", "G")
DIMENSIONS = ("cv_match", "north_star", "compensation", "culture", "red_flags")


class AgenticEvaluation(StrictFrozen):
    run_key: RunKey
    requirements: RequirementSet = Field(repr=False)
    matches: tuple[RequirementMatch, ...] = Field(repr=False)
    archetype: str = Field(min_length=1, max_length=128)
    global_score: float
    dimensions: dict[str, Dimension] = Field(repr=False)
    facts: JobFacts = Field(repr=False)
    location_fit: Literal["melbourne", "remote_accessible", "outside", "unknown"]  # "melbourne" = in the person's own state (legacy name, stored)
    location_evidence: SourceCitation | None = None
    legitimacy: Literal["verified", "uncertain", "suspicious"]
    research_available: bool
    report: dict[str, str]
    screening_questions: tuple[str, ...] = Field(max_length=30)
    # Private retrieval/model provenance, saved in the existing evaluation artifact.
    # No default migration or new interpretation of historical evaluations.
    matching_diagnostics: dict[str, Any] | None = Field(default=None, repr=False)

    @model_serializer(mode="wrap")
    def _historical_payload(self, handler):
        result = handler(self)
        if self.matching_diagnostics is None:
            result.pop("matching_diagnostics", None)
        return result

    @model_validator(mode="before")
    @classmethod
    def _safe_embedded_shape(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("facts"), dict):
            allowed = {"real_job", "role_family", "duties", "required_skills", "preferred_skills", "seniority",
                       "min_years", "hours", "program", "work_rights", "screening_questions"}
            facts = data["facts"]
            if any(type(k) is not str or k not in allowed for k in facts):
                raise ValueError("invalid evaluation facts")
            rights = facts.get("work_rights")
            if isinstance(rights, dict) and any(type(k) is not str or k not in {"requirement", "quote"} for k in rights):
                raise ValueError("invalid work-rights facts")
        return data

    @field_validator("global_score")
    @classmethod
    def _score(cls, value: float) -> float:
        if type(value) not in (float, int) or not math.isfinite(value) or not 1 <= value <= 5:
            raise ValueError("invalid score")
        return float(value)

    @field_validator("dimensions")
    @classmethod
    def _dimensions(cls, value: dict[str, Dimension]) -> dict[str, Dimension]:
        if type(value) is not dict or set(value) != set(DIMENSIONS) or any(type(k) is not str for k in value):
            raise ValueError("invalid dimensions")
        return value

    @field_validator("report")
    @classmethod
    def _report(cls, value: dict[str, str]) -> dict[str, str]:
        if type(value) is not dict or set(value) != set(REPORT_FIELDS) or any(
            type(k) is not str or type(v) is not str or len(v) > 4000 for k, v in value.items()
        ):
            raise ValueError("invalid report")
        return value

    @model_validator(mode="after")
    def _evaluation_integrity(self):
        if self.run_key.ad_hash != self.requirements.ad_hash:
            raise ValueError("ad hash mismatch")
        ids = [r.id for r in self.requirements.requirements]
        match_ids = [m.requirement_id for m in self.matches]
        if len(match_ids) != len(set(match_ids)) or set(match_ids) != set(ids):
            raise ValueError("requirement match coverage mismatch")
        reqs = {r.id: r for r in self.requirements.requirements}
        for match in self.matches:
            requirement = reqs[match.requirement_id]
            if requirement.importance in ("critical", "high") and match.match in ("partial", "missing") \
                    and (not match.risk.strip() or not match.mitigation.strip()):
                raise ValueError("high importance gap needs risk and mitigation")
        return self


class DraftProposal(StrictFrozen):
    run_key: RunKey
    evaluation_hash: str
    evidence_hash: str
    content: dict[str, Any] = Field(repr=False)
    screening_answers: tuple[AgenticScreeningAnswer, ...] = ()

    @field_validator("evaluation_hash", "evidence_hash")
    @classmethod
    def _hash(cls, value: str) -> str:
        if not HEX.fullmatch(value):
            raise ValueError("invalid hash")
        return value

    @field_validator("content")
    @classmethod
    def _content(cls, value: dict[str, Any]) -> dict[str, Any]:
        if type(value) is not dict:
            raise ValueError("content must be an object")
        return _finite_json(value, 1024 * 1024)

    @property
    def draft_hash(self) -> str:
        # Recompute on access: frozen Pydantic models do not deep-freeze nested dicts.
        try:
            return digest(self.model_dump(mode="json"))
        except Exception:
            pass
        _safe_raise("invalid_draft")


class ReviewVerdict(StrictFrozen):
    run_key: RunKey
    draft_hash: str
    reviewer_role: Literal["independent_reviewer"]
    verdict: Literal["approve", "revise", "reject"]
    criteria: dict[str, bool]
    feedback: tuple[str, ...] = Field(max_length=30)

    @field_validator("draft_hash")
    @classmethod
    def _hash(cls, value: str) -> str:
        if not HEX.fullmatch(value):
            raise ValueError("invalid hash")
        return value

    @field_validator("criteria")
    @classmethod
    def _criteria(cls, value: dict[str, bool]) -> dict[str, bool]:
        if type(value) is not dict or any(type(k) is not str or type(v) is not bool for k, v in value.items()):
            raise ValueError("invalid review criteria")
        return value

    @field_validator("feedback")
    @classmethod
    def _feedback(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > 30 or any(type(x) is not str or len(x) > 4000 for x in value):
            raise ValueError("invalid feedback")
        return value

    @model_validator(mode="after")
    def _approve_all(self):
        if self.verdict == "approve" and not self.criteria:  # required criteria are checked in validate_review
            raise ValueError("approval needs all criteria")
        return self


def validate_review(verdict: ReviewVerdict, draft_hash: str, required_criteria: tuple[str, ...]) -> None:
    """Passes when the gate criteria hold; a "revise" with only taste notes still passes (2026-10-20)."""
    try:
        if type(verdict) is not ReviewVerdict:
            _safe_raise("review_not_accepted")
        verdict = ReviewVerdict.model_validate(verdict.model_dump())
        if (verdict.draft_hash != draft_hash or type(required_criteria) is not tuple or not required_criteria
                or not set(required_criteria) <= set(verdict.criteria)  # extra criteria from the model are fine
                or verdict.verdict not in {"approve", "revise"} or not all(verdict.criteria[k] for k in required_criteria)):
            _safe_raise("review_not_accepted")
    except PublicAgenticError:
        raise
    except Exception:
        pass
    else:
        return
    _safe_raise("review_not_accepted")


class PackageManifest(StrictFrozen):
    run_key: RunKey
    evaluation_hash: str
    evidence_hash: str
    answers_hash: str
    draft_hash: str
    review_hash: str
    pdfs: dict[str, str]
    verification: dict[str, Literal[True]]
    owner_to_answer: int = Field(ge=0)

    @field_validator("evaluation_hash", "evidence_hash", "answers_hash", "draft_hash", "review_hash")
    @classmethod
    def _hash(cls, value: str) -> str:
        if not HEX.fullmatch(value):
            raise ValueError("invalid hash")
        return value

    @field_validator("pdfs")
    @classmethod
    def _pdf_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        if type(value) is not dict or set(value) != {"cv", "letter"} or any(
            type(k) is not str or type(v) is not str or not HEX.fullmatch(v) for k, v in value.items()
        ):
            raise ValueError("invalid pdf hashes")
        return value

    @field_validator("verification")
    @classmethod
    def _verified(cls, value: dict[str, Literal[True]]) -> dict[str, Literal[True]]:
        if type(value) is not dict or set(value) != {"cv_pdf", "letter_pdf", "claims", "review"} or any(
            type(k) is not str or type(v) is not bool or v is not True for k, v in value.items()
        ):
            raise ValueError("invalid verification flags")
        return value


class Reservation(StrictFrozen):
    reservation_id: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=64)
    input_tokens: int = Field(ge=0)
    requested_output_tokens: int = Field(ge=1)
    charged_tokens: int = Field(ge=0)
    state: Literal["reserved", "dispatched", "settled", "ambiguous"]
    actual_usage: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _charge_rules(self):
        maximum = self.input_tokens + self.requested_output_tokens
        if self.state == "settled":
            expected = self.actual_usage if self.actual_usage is not None else maximum
            if self.charged_tokens != expected or expected > maximum:
                raise ValueError("invalid settled charge")
        elif self.actual_usage is not None or self.charged_tokens != maximum:
            raise ValueError("unsettled reservation must retain maximum charge")
        return self


def parse_budget_checkpoint_json(payload: str) -> "BudgetCheckpoint":
    """Parse the checkpoint wire representation emitted by model_dump_json()."""
    try:
        def reject_duplicate_keys(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate key")
                result[key] = value
            return result

        data = json.loads(payload, parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
                          object_pairs_hook=reject_duplicate_keys)
        if type(data) is not dict or type(data.get("reservations")) is not list:
            _safe_raise("invalid_checkpoint")
        data["reservations"] = tuple(data["reservations"])
        return BudgetCheckpoint.model_validate(data)
    except PublicAgenticError:
        raise
    except Exception:
        pass
    _safe_raise("invalid_checkpoint")


class BudgetCheckpoint(StrictFrozen):
    schema_version: Literal[1]
    run_key: str
    batch_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=0)
    job_token_ceiling: int = Field(ge=1)
    batch_token_ceiling: int = Field(ge=1)
    job_charged: int = Field(ge=0)
    batch_charged: int = Field(ge=0)
    failed_attempts: int = Field(ge=0, le=6)  # = runtime.MAX_FAILED_ATTEMPTS
    role_turns: dict[str, int]
    research_queries: int = Field(ge=0, le=5)
    research_pages: int = Field(ge=0, le=3)
    job_deadline: float
    batch_deadline: float
    reservations: tuple[Reservation, ...]

    @field_validator("run_key")
    @classmethod
    def _hash(cls, value: str) -> str:
        if not HEX.fullmatch(value):
            raise ValueError("invalid hash")
        return value

    @field_validator("job_deadline", "batch_deadline")
    @classmethod
    def _deadline(cls, value: float) -> float:
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError("invalid deadline")
        return float(value)

    @field_validator("role_turns")
    @classmethod
    def _turns(cls, value: dict[str, int]) -> dict[str, int]:
        allowed = {"candidate_evaluator", "evaluator", "researcher", "drafter", "reviewer", "prefill_answers"}
        if type(value) is not dict or any(type(k) is not str or k not in allowed
                                           or type(v) is not int or not v >= 0  # cumulative across drafts
                                           for k, v in value.items()):
            raise ValueError("invalid role turns")
        return value

    @model_validator(mode="before")
    @classmethod
    def _version_is_exact_integer(cls, data: Any) -> Any:
        if isinstance(data, dict) and type(data.get("schema_version")) is not int:
            raise ValueError("invalid schema version")
        return data

    @model_validator(mode="before")
    @classmethod
    def _safe_shape(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if any(type(k) is not str or k not in cls.model_fields for k in data):
                raise ValueError("invalid checkpoint fields")
            reservations = data.get("reservations")
            if isinstance(reservations, (tuple, list)):
                allowed = set(Reservation.model_fields)
                for item in reservations:
                    if isinstance(item, dict) and any(type(k) is not str or k not in allowed for k in item):
                        raise ValueError("invalid reservation fields")
        return data

    @model_validator(mode="after")
    def _accounting(self):
        ids = [r.reservation_id for r in self.reservations]
        total = sum(r.charged_tokens for r in self.reservations)
        if len(ids) != len(set(ids)) or total != self.job_charged:
            raise ValueError("invalid job accounting")
        if self.job_charged > self.job_token_ceiling or self.batch_charged < self.job_charged \
                or self.batch_charged > self.batch_token_ceiling:
            raise ValueError("invalid batch accounting")
        return self
