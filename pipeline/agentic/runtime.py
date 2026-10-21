"""Explicit tool registry and conservative shared budgets for agentic roles.

Callers inject the model client and checkpoint callback; role execution delegates
to the bounded Deep Agents graph in deepagents_runtime.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from types import UnionType
from typing import Annotated, Any, Callable, Union, get_args, get_origin

from pydantic import BaseModel, TypeAdapter

from pipeline.agentic.contracts import AgenticError, BudgetCheckpoint, Reservation


# Moves one agent step may take; employer research uses several (8 ran out on real ads, 2026-10-12).
MAX_ROLE_TURNS = 16
# Model replies a job may get wrong (bad format, failed check) before it is held; 3 ran out on real drafts.
MAX_FAILED_ATTEMPTS = 6


class RuntimeErrorSafe(AgenticError):
    """Fixed-code public runtime failure."""


@dataclass(frozen=True)
class Tool:
    name: str
    arguments_model: type[BaseModel]
    handler: Callable[[BaseModel, Any], Any]

    def __post_init__(self):
        if (not self.name or type(self.name) is not str or not isinstance(self.arguments_model, type)
                or not issubclass(self.arguments_model, BaseModel)
):
            raise ValueError("invalid_tool")


@dataclass(frozen=True)
class RoleSpec:
    name: str
    model: str
    tools: tuple[Tool, ...]
    system_prompt: str
    terminal_tools: tuple[str, ...]
    validation_corrections: int = 0
    reasoning: str = ""  # "high" for roles that must think (the letter writer); sent as reasoning_effort

    def __post_init__(self):
        if type(self.validation_corrections) is not int or self.validation_corrections not in (0, 1):
            raise ValueError('invalid_validation_corrections')
        if self.name not in {"candidate_evaluator", "evaluator", "researcher", "drafter", "reviewer", "jd_requirements", "prefill_answers"}:
            raise ValueError("invalid_role")
        names = [t.name for t in self.tools]
        if not names or len(names) != len(set(names)) or not self.terminal_tools or not set(self.terminal_tools) <= set(names):
            raise ValueError("invalid_registry")


@dataclass(frozen=True)
class RoleResult:
    output: BaseModel
    tool_trace: tuple[str, ...]
    turns: int


@dataclass
class _BatchState:
    batch_id: str
    token_ceiling: int
    deadline: float
    clock: Callable[[], float]
    lock: threading.RLock = field(default_factory=threading.RLock)
    charged_tokens: int = 0
    circuit_open: bool = False
    active_jobs: int = 0
    jobs: dict[str, "JobBudget"] = field(default_factory=dict)


class BatchBudget:
    """Single process shared accounting authority; production persistence is injected."""
    def __init__(self, batch_id: str, token_ceiling: int = 2_000_000, deadline: float | None = None,
                 clock: Callable[[], float] = time.time, max_concurrency: int = 2):
        now = clock()
        self._state = _BatchState(batch_id, token_ceiling, deadline or now + 1800, clock)
        self._max_concurrency = max_concurrency

    @property
    def batch_id(self): return self._state.batch_id
    @property
    def charged_tokens(self): return self._state.charged_tokens
    @property
    def deadline(self): return self._state.deadline

    def admit(self, job: "JobBudget") -> None:
        with self._state.lock:
            existing = self._state.jobs.get(job.run_key)
            if existing is job:
                return
            if existing is not None:
                raise RuntimeErrorSafe("job_already_active")
            if self._state.active_jobs >= self._max_concurrency:
                raise RuntimeErrorSafe("concurrency_limit")
            self._state.active_jobs += 1
            self._state.jobs[job.run_key] = job

    def release(self, job: "JobBudget") -> None:
        """Release an active-job slot after the orchestrator has completed the job."""
        with self._state.lock:
            if self._state.jobs.get(job.run_key) is job:
                del self._state.jobs[job.run_key]
                self._state.active_jobs -= 1


class JobBudget:
    def __init__(self, run_key: str, batch: BatchBudget, *, checkpoint: BudgetCheckpoint | None = None,
                 persist: Callable[..., Any] | None = None, token_ceiling: int = 150_000,
                 clock: Callable[[], float] = time.time, deadline: float | None = None):
        if type(run_key) is not str or len(run_key) != 64 or any(c not in "0123456789abcdef" for c in run_key):
            raise RuntimeErrorSafe("invalid_run_key")
        self.run_key, self.batch, self._clock = run_key, batch, clock
        self._persist = persist or self._memory_persist
        self.events: list[tuple] = []
        self._revision = 0
        self._job_ceiling = token_ceiling
        self._job_deadline = deadline if deadline is not None else min(clock() + 900, batch.deadline)
        self._reservations: dict[str, Reservation] = {}
        self._role_turns = {name: 0 for name in ("candidate_evaluator", "evaluator", "researcher", "drafter", "reviewer", "prefill_answers")}
        self._failed_attempts = self._queries = self._pages = self._job_charged = 0
        self.batch.admit(self)
        if checkpoint is not None:
            try:
                self._restore(checkpoint)
            except BaseException:
                self.batch.release(self)  # an invalid checkpoint must not leak the admitted slot
                raise

    def _memory_persist(self, checkpoint, *, expected_revision, reservation_id, operation):
        self.events.append(("persist", operation, expected_revision, reservation_id))
        return checkpoint

    @classmethod
    def restore(cls, checkpoint: BudgetCheckpoint, *, batch: BatchBudget, persist=None,
                clock: Callable[[], float] = time.time) -> "JobBudget":
        return cls(checkpoint.run_key, batch, checkpoint=checkpoint, persist=persist, clock=clock)

    def _restore(self, checkpoint: BudgetCheckpoint):
        if type(checkpoint) is not BudgetCheckpoint or checkpoint.batch_id != self.batch.batch_id:
            raise RuntimeErrorSafe("invalid_checkpoint")
        if checkpoint.batch_token_ceiling != self.batch._state.token_ceiling:
            raise RuntimeErrorSafe("invalid_checkpoint")
        with self.batch._state.lock:
            if checkpoint.batch_charged > self.batch._state.token_ceiling:
                raise RuntimeErrorSafe("invalid_checkpoint")
            self.batch._state.charged_tokens = max(self.batch._state.charged_tokens, checkpoint.batch_charged)
        self._revision = checkpoint.revision
        self._job_ceiling = checkpoint.job_token_ceiling
        self._job_deadline = checkpoint.job_deadline
        self._failed_attempts = checkpoint.failed_attempts
        self._role_turns.update(checkpoint.role_turns)
        self._queries, self._pages = checkpoint.research_queries, checkpoint.research_pages
        self._reservations = {r.reservation_id: r for r in checkpoint.reservations}
        self._job_charged = checkpoint.job_charged

    @property
    def charged_tokens(self): return self._job_charged
    @property
    def failed_attempts(self): return self._failed_attempts

    def remaining_seconds(self, now: float | None = None):
        now = self._clock() if now is None else now
        remaining = min(self._job_deadline, self.batch.deadline) - now
        invocation_deadline = getattr(self, '_invocation_deadline', None)
        if invocation_deadline is not None:
            remaining = min(remaining, invocation_deadline - time.time())
        return remaining

    def ensure_live(self, now: float | None = None):
        from pipeline.agentic.execution import current
        invocation = current()
        if invocation is not None:
            invocation.check()
        now = self._clock() if now is None else now
        if self._failed_attempts >= MAX_FAILED_ATTEMPTS:
            raise RuntimeErrorSafe("failed_attempt_limit")
        if self.remaining_seconds(now) <= 0:
            raise RuntimeErrorSafe("deadline_exceeded")
        if self.batch._state.circuit_open:
            raise RuntimeErrorSafe("batch_paused")

    def _checkpoint(self, revision=None):
        state = self.batch._state
        return BudgetCheckpoint(schema_version=1, run_key=self.run_key, batch_id=self.batch.batch_id,
            revision=self._revision + 1 if revision is None else revision, job_token_ceiling=self._job_ceiling,
            batch_token_ceiling=state.token_ceiling, job_charged=self._job_charged,
            batch_charged=state.charged_tokens, failed_attempts=self._failed_attempts,
            role_turns=dict(self._role_turns), research_queries=self._queries, research_pages=self._pages,
            job_deadline=self._job_deadline, batch_deadline=self.batch.deadline,
            reservations=tuple(self._reservations.values()))

    def _commit(self, operation: str, reservation_id: str = ""):
        expected = self._revision
        cp = self._checkpoint()
        failed = False
        try:
            self._persist(cp, expected_revision=expected, reservation_id=reservation_id, operation=operation)
        except Exception:
            failed = True
        if failed:
            raise RuntimeErrorSafe("checkpoint_unavailable") from None
        self._revision = cp.revision
        self.events.append((operation, reservation_id, self._revision))

    def reserve(self, role: str, input_tokens: int, output_tokens: int) -> str:
        role = "evaluator" if role == "jd_requirements" else role
        if role not in self._role_turns or type(input_tokens) is not int or type(output_tokens) is not int or input_tokens < 0 or output_tokens < 1:
            raise RuntimeErrorSafe("invalid_reservation")
        state = self.batch._state
        with state.lock:
            self.ensure_live()
            charge = input_tokens + output_tokens
            if self._job_charged + charge > self._job_ceiling or state.charged_tokens + charge > state.token_ceiling:
                raise RuntimeErrorSafe("token_limit")
            rid = uuid.uuid4().hex
            reservation = Reservation(reservation_id=rid, role=role, input_tokens=input_tokens,
                requested_output_tokens=output_tokens, charged_tokens=charge, state="reserved")
            self._reservations[rid] = reservation
            self._job_charged += charge
            state.charged_tokens += charge
            self._role_turns[role] += 1
            try:
                self._commit("reserve", rid)
            except RuntimeErrorSafe:
                # Keep the maximum charged in local memory; dispatch is forbidden.
                raise
            return rid

    def dispatched(self, reservation_id: str):
        with self.batch._state.lock:
            old = self._reservations[reservation_id]
            self._reservations[reservation_id] = old.model_copy(update={"state": "dispatched"})
            try: self._commit("dispatched", reservation_id)
            except RuntimeErrorSafe:
                self._reservations[reservation_id] = old
                raise

    def settle(self, reservation_id: str, usage: int | None):
        with self.batch._state.lock:
            old = self._reservations[reservation_id]
            if old.state == "settled":
                return
            maximum = old.input_tokens + old.requested_output_tokens
            trusted = type(usage) is int and 0 <= usage <= maximum
            actual = usage if trusted else None
            charge = actual if actual is not None else maximum
            self._reservations[reservation_id] = old.model_copy(update={"state": "settled", "actual_usage": actual,
                                                                         "charged_tokens": charge})
            delta = old.charged_tokens - charge
            self._job_charged -= delta
            self.batch._state.charged_tokens -= delta
            try: self._commit("settle", reservation_id)
            except RuntimeErrorSafe:
                self._reservations[reservation_id] = old
                self._job_charged += delta
                self.batch._state.charged_tokens += delta
                raise

    def failed(self, code: str):
        with self.batch._state.lock:
            self._failed_attempts += 1
            if code in {"rate_limited", "auth"}: self.batch._state.circuit_open = True
            self._commit("failure")
            if self._failed_attempts >= MAX_FAILED_ATTEMPTS: raise RuntimeErrorSafe("failed_attempt_limit")

    def research(self, kind: str):
        with self.batch._state.lock:
            self.ensure_live()
            if kind == "query":
                if self._queries >= 5: raise RuntimeErrorSafe("research_limit")
                self._queries += 1
            elif kind == "page":
                if self._pages >= 3: raise RuntimeErrorSafe("research_limit")
                self._pages += 1
            else: raise RuntimeErrorSafe("invalid_research_operation")
            self._commit("research")

    def snapshot(self) -> BudgetCheckpoint:
        with self.batch._state.lock:
            return self._checkpoint(self._revision)


def _json_tuples(value: Any, annotation: Any) -> Any:
    """Decode arrays only where the declared schema requires immutable tuples.

    Pydantic before-model validators can switch nested JSON validation into
    Python mode. Normalize only the JSON/Python tuple representation gap;
    scalar types, unknown fields and all model validators remain strict.
    """
    origin, parameters = get_origin(annotation), get_args(annotation)
    if origin is Annotated:
        return _json_tuples(value, parameters[0])
    if origin in (Union, UnionType):
        for branch in parameters:
            converted = _json_tuples(value, branch)
            try:
                TypeAdapter(branch).validate_python(converted, strict=True)
            except Exception:
                continue
            return converted
        return value
    if isinstance(annotation, type) and issubclass(annotation, BaseModel) and type(value) is dict:
        return {key: _json_tuples(item, annotation.model_fields[key].annotation)
                if key in annotation.model_fields else item for key, item in value.items()}
    if origin is tuple and type(value) in (list, tuple):
        if not parameters:
            return tuple(value)
        homogeneous = len(parameters) == 2 and parameters[1] is Ellipsis
        return tuple(_json_tuples(item, parameters[0] if homogeneous else
                                  parameters[index] if index < len(parameters) else Any)
                     for index, item in enumerate(value))
    if origin is list and type(value) is list and parameters:
        return [_json_tuples(item, parameters[0]) for item in value]
    if origin is dict and type(value) is dict and len(parameters) == 2:
        return {key: _json_tuples(item, parameters[1]) for key, item in value.items()}
    return value


def validate_model_payload(model_type: type[BaseModel], payload: Any) -> BaseModel:
    """Validate a finite JSON payload against a strict model, including tuples.

    Shared by live role calls and persisted artifact readers so the same exact
    schemas apply at both boundaries. Invalid input produces a fixed safe code.
    """
    invalid = False
    try:
        if (not isinstance(model_type, type) or not issubclass(model_type, BaseModel)
                or type(payload) is not dict):
            raise ValueError
        json.dumps(payload, ensure_ascii=False, allow_nan=False)
        value = model_type.model_validate(_json_tuples(payload, model_type), strict=False)
    except Exception:
        invalid = True
    if invalid:
        raise RuntimeErrorSafe("invalid_model_payload") from None
    return value


def _json_bytes(value: Any) -> int:
    try:
        return len(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                              allow_nan=False).encode("utf-8"))
    except Exception:
        raise RuntimeErrorSafe("invalid_request") from None


def run_role(role: RoleSpec, context: Any, budget: JobBudget, llm: Any, *, max_turns: int = MAX_ROLE_TURNS,
             max_output_tokens: int = 12_000) -> RoleResult:
    """Execute the real Deep Agents graph through the counted local gateway."""
    from pipeline.agentic.deepagents_runtime import run_deepagents_role
    return run_deepagents_role(role, context, budget, llm, max_turns=max_turns,
                               max_output_tokens=max_output_tokens)


def _usage_total(usage: Any) -> int | None:
    if type(usage) is not dict: return None
    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if type(prompt) is not int or type(completion) is not int or prompt < 0 or completion < 0:
        return None
    return prompt + completion
