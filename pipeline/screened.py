"""The `screened` execution mode: cheap steps first, the agentic evaluator last and only for the best few.

    prescreen -> fetch (closed ads archived) -> extract -> evaluate -> gate -> SHORTLISTED --promote--> agentic

The state graph is pipeline.graph.Graph with a different edge table: a gate pass stops at SHORTLISTED instead of
queueing a draft. promote() then hands the top-scored SHORTLISTED jobs to the unchanged agentic batch.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

from . import graph, store
from .schemas import Stage

log = logging.getLogger(__name__)

SCREENED_EDGES = {st: e for st, e in graph.EDGES.items() if st not in (Stage.DRAFT_QUEUED, Stage.DRAFTED)}
SCREENED_EDGES[Stage.SCORED] = graph.Edge("gate", frozenset({Stage.SHORTLISTED, Stage.ARCHIVED}))
GATE_ROUTE = {"draft": Stage.SHORTLISTED, "archive": Stage.ARCHIVED, "review": Stage.DLQ}
TERMINAL = graph.TERMINAL | {Stage.SHORTLISTED, Stage.SIDE}
DEFAULTS = {"promote_per_run": 3, "promote_per_day": 10, "min_score": 3.0}
TRANSPORT_ERRORS = ("Connection", "Timeout", "timed out", "502", "503", "504")


class ScreenedGraph(graph.Graph):
    EDGES = SCREENED_EDGES
    TERMINAL = TERMINAL
    GATE_ROUTE = GATE_ROUTE

    def _move(self, pid, cur, nxt, output, reason=None, attempts=1):
        # A gate pass is only a shortlist when the one-read score reaches min_score; below it the job is a weak fit.
        if cur is Stage.SCORED and nxt is Stage.SHORTLISTED:
            score = (output or {}).get("score")
            if score is not None and float(score) < screened_settings(self.config)["min_score"]:
                nxt, reason = Stage.ARCHIVED, "low_fit"
        return super()._move(pid, cur, nxt, output, reason=reason, attempts=attempts)


def screened_settings(config) -> dict:
    own = (((config.settings or {}).get("pipeline") or {}).get("screened") or {}) if config else {}
    return {k: type(v)(own.get(k, v)) for k, v in DEFAULTS.items()}


def retry_transport(conn, limit: int = 50) -> int:
    """Put back unresolved dead letters that failed on transport (not on validation), once they are 6 h old."""
    cutoff = (datetime.now(UTC) - timedelta(hours=6)).isoformat(timespec="seconds")
    like = " OR ".join("error LIKE ?" for _ in TRANSPORT_ERRORS)
    rows = conn.execute("SELECT id FROM pipeline_dlq WHERE resolved_at IS NULL AND attempts < 4 AND created_at <= ? "
                        f"AND ({like}) ORDER BY id LIMIT ?",
                        (cutoff, *[f"%{t}%" for t in TRANSPORT_ERRORS], int(limit))).fetchall()
    done = 0
    for r in rows:
        try:
            store.retry_dlq(conn, r["id"])
            done += 1
        except Exception as exc:                            # noqa: BLE001 - one stuck row never blocks the rest
            log.warning("screened: dlq retry %s failed: %s", r["id"], type(exc).__name__)
    conn.commit()
    return done


def _promoted_since(conn, hours: int = 24) -> int:
    since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat(timespec="seconds")
    return conn.execute("SELECT COUNT(*) FROM pipeline_events WHERE node='promote' AND at>=?", (since,)).fetchone()[0]


def promote(conn, config, *, max_seconds=None, deadline=None) -> dict:
    """Send the best SHORTLISTED jobs to the agentic evaluator: highest score first, newest id on ties."""
    cfg = screened_settings(config)
    allowance = max(0, min(cfg["promote_per_run"], cfg["promote_per_day"] - _promoted_since(conn)))
    out = {"promoted": 0, "allowance": allowance}
    if allowance <= 0:
        return out
    rows = conn.execute(
        "SELECT posting_id, CAST(json_extract(data_json, '$.evaluate.overall') AS REAL) AS score FROM pipeline_state "
        "WHERE stage=? AND json_extract(data_json, '$.evaluate.overall') IS NOT NULL "
        "AND CAST(json_extract(data_json, '$.evaluate.overall') AS REAL) >= ? "
        "AND COALESCE(json_extract(data_json, '$.track'), '') <> 'secondary' "
        "ORDER BY CASE json_extract(data_json, '$.track') WHEN 'undergraduate' THEN 0 WHEN 'primary' THEN 1 ELSE 2 END, "
        "score DESC, posting_id DESC LIMIT ?", (str(Stage.SHORTLISTED), cfg["min_score"], allowance)).fetchall()
    ids = [r["posting_id"] for r in rows]
    if not ids:
        return out
    from pipeline.agentic.service import agentic_batch_run
    for pid in ids:                                         # logged before the call: a crash must not allow a re-promotion
        store.event(conn, pid, "promote", Stage.SHORTLISTED, Stage.SHORTLISTED, 1, None)
    conn.commit()
    out["promoted"] = len(ids)
    out["agentic"] = agentic_batch_run(ids, config, conn, max_seconds=max_seconds, deadline=deadline)
    return out


def after_collect(conn, config, max_seconds=None, deadline=None) -> dict:
    """Timer hook (jobwatch.run.run): retry transport failures, run the screened graph, then promote."""
    from jobwatch.util import adtext
    started = time.monotonic()
    with adtext.review_lock(adtext.lock_path(config)) as got:
        if not got:
            return {"skipped": "busy"}
        store.ensure(conn)
        out = {"retried": retry_transport(conn)}
        half = max_seconds / 2 if max_seconds else None
        g = ScreenedGraph(conn=conn, db_path=str(config.db_path), config=config,
                          settings=graph.Settings.from_config(config))
        out["graph"] = asyncio.run(g.run(max_seconds=half))
        left = max_seconds - (time.monotonic() - started) if max_seconds else None
        out["promote"] = promote(conn, config, max_seconds=left, deadline=deadline)
        return out
