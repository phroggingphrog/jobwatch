"""The deterministic state graph: typed asyncio runner over SQLite (owner spec 2026-10-08).

    INGESTED --extract--> EXTRACTED --evaluate--> SCORED --gate--> DRAFT_QUEUED --draft--> DRAFTED --form_map--> READY
                                                           \\--gate--> ARCHIVED
    any non-terminal stage --(node failed 3x, or the gate needs a person)--> DLQ

Rules the code enforces:
- EDGES is the whole control flow. A node returns its output; the runner, not the model, picks the next stage, and a
  move that is not in EDGES raises (a bug, never a silent default).
- Model nodes (extract, evaluate, form_map screening answers) go through structured.call: strict Pydantic schema,
  max 3 attempts, then the job is dead-lettered. Code nodes (draft chain, form map) get the same 3 attempts.
- Every move is persisted (pipeline_state + pipeline_events) before the next node runs, so a crash or a timer
  restart resumes where it stopped. A job is never processed by two runners: moves check the current stage.
- Nothing is ever submitted. READY means "the owner reviews the form map and presses Submit by hand".
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from jobwatch.llm import LLM

from . import store
from .nodes import draft, evaluate, extract, form_map, gate, ingest, sort
from .schemas import ApplicationPackage, JobAd, JobFacts, MatchScore, Profile, Stage
from .structured import MAX_ATTEMPTS, StructuredFailure
from jobwatch.settings import DEFAULT_MODEL

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Edge:
    node: str
    to: frozenset[Stage]


EDGES: dict[Stage, Edge] = {
    Stage.INGESTED: Edge("extract", frozenset({Stage.EXTRACTED})),
    Stage.EXTRACTED: Edge("evaluate", frozenset({Stage.SCORED})),
    Stage.SCORED: Edge("gate", frozenset({Stage.DRAFT_QUEUED, Stage.ARCHIVED})),
    Stage.DRAFT_QUEUED: Edge("draft", frozenset({Stage.DRAFTED})),
    Stage.DRAFTED: Edge("form_map", frozenset({Stage.READY})),
}
TERMINAL = frozenset({Stage.READY, Stage.ARCHIVED, Stage.DLQ})
GATE_ROUTE = {"draft": Stage.DRAFT_QUEUED, "archive": Stage.ARCHIVED, "review": Stage.DLQ}


@dataclass
class Settings:
    extract_model: str = DEFAULT_MODEL
    score_model: str = DEFAULT_MODEL
    form_model: str = DEFAULT_MODEL
    threshold: float = gate.THRESHOLD
    concurrency: int = 6
    ingest_limit: int = 200
    fetch_budget: int = 25
    drafts_per_run: int = 3
    drafts_per_day: int = 10            # cost guard across runs (an Opus-written draft costs about $1.70)
    sort_model: str = DEFAULT_MODEL
    sort_per_run: int = 200             # archived "not a target role" jobs given a named kind per run (BUI-96)

    @classmethod
    def from_config(cls, config) -> "Settings":
        own = ((config.settings or {}).get("pipeline") or {}) if config else {}
        return cls(**{k: v for k, v in own.items() if k in cls.__dataclass_fields__})


@dataclass
class Graph:
    conn: object                    # sqlite3.Connection, used only on the event-loop thread
    db_path: str
    config: object
    settings: Settings = field(default_factory=Settings)
    llm: LLM | None = None
    _profile: Profile | None = None
    _drafts_left: int = 0
    deadline: float | None = None           # time.monotonic() after which no NEW node starts
    stats: dict = field(default_factory=dict)

    def __post_init__(self):
        store.ensure(self.conn)
        self.llm = self.llm or LLM()
        self._drafts_left = max(0, min(self.settings.drafts_per_run,
                                       self.settings.drafts_per_day - store.drafted_since(self.conn, hours=24)))
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ bookkeeping
    def _count(self, key: str) -> None:
        self.stats[key] = self.stats.get(key, 0) + 1

    def _move(self, pid: int, cur: Stage, nxt: Stage, output: dict | None, reason: str | None = None,
              attempts: int = 1) -> Stage:
        edge = EDGES[cur]
        if nxt not in edge.to:
            raise RuntimeError(f"illegal move {cur} -> {nxt} by node {edge.node}")
        store.move(self.conn, pid, edge.node, cur, nxt, output=output, reason=reason, attempts=attempts)
        self.conn.commit()
        self._count(str(nxt))
        return nxt

    def _dead(self, pid: int, cur: Stage, error: str, attempts: int) -> Stage:
        store.dead_letter(self.conn, pid, EDGES[cur].node, cur, attempts, error)
        self.conn.commit()
        self._count(str(Stage.DLQ))
        return Stage.DLQ

    def profile(self) -> Profile:
        if self._profile is None:
            self._profile = extract.build_profile()
        return self._profile

    # ------------------------------------------------------------------ nodes
    async def step(self, pid: int) -> Stage:
        """Run exactly one node for the job's current stage and persist the result."""
        row = store.get(self.conn, pid)
        cur = Stage(row["stage"])
        if cur in TERMINAL:
            return cur
        data = row["data"]
        ad = JobAd.model_validate(data["ingest"])
        node = EDGES[cur].node
        try:
            if cur is Stage.INGESTED:
                text = ingest.ad_text(self.conn, pid)
                facts, n = await asyncio.to_thread(extract.run, self.llm, self.settings.extract_model, ad.title,
                                                   ad.company, ad.location, text)
                return self._move(pid, cur, Stage.EXTRACTED, facts.model_dump(), attempts=n)
            if cur is Stage.EXTRACTED:
                text = ingest.ad_text(self.conn, pid)
                facts = JobFacts.model_validate(data["extract"])
                score, n = await asyncio.to_thread(evaluate.run, self.llm, self.settings.score_model, self.profile(),
                                                   facts, ad.title, ad.company, text)
                out = {**score.model_dump(), "overall": score.overall, "profile_hash": self.profile().profile_hash}
                return self._move(pid, cur, Stage.SCORED, out, attempts=n)
            if cur is Stage.SCORED:
                text = ingest.ad_text(self.conn, pid)
                facts = JobFacts.model_validate(data["extract"])
                score = MatchScore.model_validate({k: v for k, v in data["evaluate"].items()
                                                   if k in MatchScore.model_fields})
                route, dec = gate.decide(facts, score, text, ad.title, self.settings.threshold)
                nxt = GATE_ROUTE[route]
                if nxt is Stage.DLQ:
                    return self._dead(pid, cur, f"needs review: {dec.reason}", 1)
                return self._move(pid, cur, nxt, dec.model_dump(), reason=None if dec.passed else dec.reason)
            if cur is Stage.DRAFT_QUEUED:
                if self._drafts_left <= 0:
                    return cur                              # waits for the next run (cost cap), not a failure
                self._drafts_left -= 1
                pkg, n = await self._retry(lambda: draft.run(self.db_path, pid, self.llm))
                return self._move(pid, cur, Stage.DRAFTED, pkg.model_dump(), attempts=n)
            if cur is Stage.DRAFTED:
                pkg = ApplicationPackage.model_validate(data["draft"])
                facts = JobFacts.model_validate(data["extract"])
                fmap, n = await self._retry(lambda: form_map.run(self.db_path, pid, ad.url, pkg,
                                                                 list(facts.screening_questions), self.llm,
                                                                 self.settings.form_model))
                summary = {"form_map": str(pkg.cv_pdf).rsplit("/", 1)[0] + "/form_map.json",
                           "fields": len(fmap.fields), "owner_to_answer": fmap.owner_to_answer}
                return self._move(pid, cur, Stage.READY, summary, attempts=n)
        except StructuredFailure as exc:
            return self._dead(pid, cur, str(exc), exc.attempts)
        except _GaveUp as exc:
            return self._dead(pid, cur, str(exc), MAX_ATTEMPTS)
        raise RuntimeError(f"no node for stage {cur} ({node})")

    async def _retry(self, fn):
        """Code nodes: up to MAX_ATTEMPTS tries in a worker thread; a model node inside fails straight to the DLQ."""
        errors = []
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return await asyncio.to_thread(fn), attempt
            except StructuredFailure:
                raise
            except Exception as exc:                       # noqa: BLE001 - recorded, then retried or dead-lettered
                log.warning("pipeline: attempt %d failed: %s: %s", attempt, type(exc).__name__, str(exc)[:200])
                errors.append(f"{type(exc).__name__}: {str(exc)[:300]}")
        raise _GaveUp("; ".join(errors))

    async def run_job(self, pid: int) -> Stage:
        stage = Stage(store.get(self.conn, pid)["stage"])
        while stage not in TERMINAL:
            if self.deadline is not None and time.monotonic() > self.deadline:
                self._count("time_limit")                   # a node is never cut in half: stop between nodes
                break
            nxt = await self.step(pid)
            if nxt == stage:                                # waiting (drafting cap): stop here, resume next run
                break
            stage = nxt
        return stage

    async def run(self, *, ingest_new: bool = True, limit: int | None = None, max_seconds: float | None = None,
                  posting_ids: list[int] | None = None) -> dict:
        """One timer run: admit new jobs (node 1), then move every unfinished job as far as it can go."""
        if max_seconds and max_seconds > 0:
            self.deadline = time.monotonic() + max_seconds
        if ingest_new:
            self.stats["ingest"] = ingest.run(self.conn, self.config, limit=self.settings.ingest_limit,
                                              fetch_budget=self.settings.fetch_budget, posting_ids=posting_ids)
        todo = [pid for st in EDGES for pid in store.at_stage(self.conn, st)]
        todo = sorted(set(todo))[: limit or None]
        sem = asyncio.Semaphore(max(1, self.settings.concurrency))

        async def one(pid):
            async with sem:
                try:
                    await self.run_job(pid)
                except Exception:                           # noqa: BLE001 - one bad job never stops the run
                    log.exception("pipeline: job %s crashed", pid)
                    self._count("crashed")
        await asyncio.gather(*(one(p) for p in todo))
        if self.settings.sort_per_run > 0 and (self.deadline is None or time.monotonic() < self.deadline):
            try:                                            # labels only: never moves a job, never fails the run
                left = self.deadline - time.monotonic() if self.deadline is not None else None
                self.stats["sort"] = sort.run(self.conn, self.llm, self.settings.sort_model,
                                              limit=self.settings.sort_per_run, max_seconds=left)
            except Exception as exc:                        # noqa: BLE001
                log.exception("pipeline: not-target sorting failed")
                self.stats["sort_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        self.stats["stages"] = store.counts(self.conn)
        return self.stats


class _GaveUp(RuntimeError):
    pass


def run_once(conn, db_path: str, config, *, llm: LLM | None = None, ingest_new: bool = True,
             limit: int | None = None, max_seconds: float | None = None, posting_ids: list[int] | None = None) -> dict:
    g = Graph(conn=conn, db_path=db_path, config=config, settings=Settings.from_config(config), llm=llm)
    return asyncio.run(g.run(ingest_new=ingest_new, limit=limit, max_seconds=max_seconds, posting_ids=posting_ids))


def enabled(config) -> bool:
    """pipeline.enabled in jobwatch.yaml: the timer runs call this graph instead of the old reader hook."""
    from jobwatch.execution_mode import effective_mode
    return config is not None and effective_mode(config) == 'pipeline'


def after_collect(conn, config, max_seconds: float | None = None) -> dict:
    """Timer hook (jobwatch.pipeline.run): one graph run under the shared review lock, within the unit's time."""
    from jobwatch import adtext
    with adtext.review_lock(adtext.lock_path(config)) as got:
        if not got:
            return {"skipped": "busy"}
        return run_once(conn, str(config.db_path), config, max_seconds=max_seconds)
