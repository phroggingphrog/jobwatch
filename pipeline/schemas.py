"""Typed contracts for the deterministic pipeline (owner spec 2026-10-08).

Every model output is parsed into one of these with Pydantic in strict mode (no type coercion, unknown keys
rejected). A reply that does not validate is never "fixed up" by guessing: the node retries (max 3) and then the
job goes to the dead letter queue. The overall score is computed by code from the rubric, never by the model.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=False, frozen=True)


class Stage(StrEnum):
    """Where a job is. The only legal moves are graph.EDGES; the model never picks one."""
    INGESTED = "ingested"          # node 1 admitted it (full ad text, in area, not a duplicate)
    EXTRACTED = "extracted"        # node 2 produced JobFacts
    SCORED = "scored"              # node 3 produced MatchScore
    SHORTLISTED = "shortlisted"    # screened mode: passed the gate, waits for promotion to the agentic evaluator
    DRAFT_QUEUED = "draft_queued"  # node 4 passed it (score >= threshold, no hard rule hit)
    DRAFTED = "drafted"            # node 5 produced a verified ApplicationPackage
    READY = "ready"                # node 6 produced the form map; waiting for the owner to submit by hand
    ARCHIVED = "archived"          # node 1 or node 4 stopped it (reason recorded)
    DLQ = "dlq"                    # a node failed 3 times; waiting for review


# ---------------------------------------------------------------- node 1 (no model)
class JobAd(Strict):
    posting_id: int = Field(ge=1)
    source: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=300)
    company: str = Field(max_length=200)
    location: str = Field(max_length=200)
    url: str = Field(max_length=2000)
    location_rule: str = Field(min_length=1, max_length=40)
    text_kind: Literal["full"]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------- node 2 (model: what the ad says)
RIGHTS = Literal["none_stated", "valid_work_rights", "unrestricted_work_rights", "citizen_or_pr", "citizen_only",
                 "clearance"]
BLOCKING_RIGHTS = frozenset({"unrestricted_work_rights", "citizen_or_pr", "citizen_only", "clearance"})


class WorkRights(Strict):
    requirement: RIGHTS
    quote: str = Field(max_length=400)          # exact words from the ad, "" when none_stated


class JobFacts(Strict):
    real_job: bool
    role_family: str = Field(min_length=2, max_length=80)
    duties: list[str] = Field(min_length=1, max_length=8)
    required_skills: list[str] = Field(max_length=12)
    preferred_skills: list[str] = Field(max_length=12)
    seniority: Literal["entry", "junior", "mid", "senior"]
    min_years: int | None = Field(default=None, ge=0, le=30)
    hours: Literal["full_time_only", "part_time_ok", "casual", "unstated"]
    program: bool                               # graduate / intern / vacation / cadet program
    work_rights: WorkRights
    screening_questions: list[str] = Field(max_length=10)


class Profile(Strict):
    """The candidate, built by code from the evidence file and the owner's interest model (no model call, no
    contact details)."""
    skills: list[str] = Field(min_length=1, max_length=60)
    roles: list[str] = Field(max_length=30)
    education: list[str] = Field(max_length=20)
    pursues: str = Field(min_length=20, max_length=8000)
    profile_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------- node 3 (model: rubric marks only)
class RubricMark(Strict):
    score: int = Field(ge=1, le=5)
    evidence: str = Field(min_length=3, max_length=400)


WEIGHTS = {"technical_skills": 0.40, "experience": 0.30, "domain": 0.30}


class MatchScore(Strict):
    technical_skills: RubricMark                # the ad's required skills vs the candidate's skills
    experience: RubricMark                      # level and years asked vs what the candidate has
    domain: RubricMark                          # the job family vs what the candidate pursues
    wanted: Literal["core", "good", "adjacent", "not_wanted"]
    justification: str = Field(min_length=10, max_length=600)

    @property
    def overall(self) -> float:
        """1.0-5.0, by code from the rubric (the model never does arithmetic or picks the route)."""
        return round(sum(getattr(self, k).score * w for k, w in WEIGHTS.items()), 2)


# ---------------------------------------------------------------- node 4 (code only)
class GateDecision(Strict):
    passed: bool
    reason: str = Field(min_length=2, max_length=60)
    score: float | None = None


# ---------------------------------------------------------------- node 5 (drafting chain output, checked by code)
class ApplicationPackage(Strict):
    application_id: int = Field(ge=1)
    draft_version: int = Field(ge=1)
    cv_pdf: str = Field(min_length=1)
    letter_pdf: str = Field(min_length=1)
    verify_ok: Literal[True]
    pages_cv: int = Field(ge=1, le=2)
    pages_letter: int = Field(ge=1, le=1)


# ---------------------------------------------------------------- node 6 (model: screening answers only)
class ScreeningAnswer(Strict):
    question: str = Field(min_length=3, max_length=400)
    answer: str = Field(max_length=1200)        # "" when the owner must answer
    source: Literal["evidence", "owner_to_answer"]


class ScreeningAnswers(Strict):
    answers: list[ScreeningAnswer] = Field(max_length=10)


class FormField(Strict):
    field: str = Field(min_length=1, max_length=120)
    value: str = Field(max_length=4000)
    source: Literal["answers_file", "draft", "evidence", "owner_to_answer"]


class FormMap(Strict):
    """What to type into the employer's form. Stored next to the draft (data dir, never git or logs).
    The owner reviews it and presses Submit; nothing here is ever sent."""
    posting_id: int
    application_id: int
    url: str
    fields: list[FormField] = Field(default_factory=list)
    owner_to_answer: int = Field(ge=0)
