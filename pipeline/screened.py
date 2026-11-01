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
GATE_ROUTE = {"draft": Stage.SHORTLISTED, "archive": Stage.ARCHIVED, "review": Stage.SHORTLISTED}
TERMINAL = graph.TERMINAL | {Stage.SHORTLISTED, Stage.SIDE}
DEFAULTS = {"promote_per_run": 3, "promote_per_day": 10, "min_score": 3.0}
TRANSPORT_ERRORS = ("Connection", "Timeout", "timed out", "502", "503", "504")


class ScreenedGraph(graph.Graph):
    EDGES = SCREENED_EDGES
    TERMINAL = TERMINAL
    GATE_ROUTE = GATE_ROUTE


def screened_settings(config) -> dict:
    own = (((config.settings or {}).get("pipeline") or {}).get("screened") or {}) if config else {}
    return {k: type(v)(own.get(k, v)) for k, v in DEFAULTS.items()}


ACTIVE = (Stage.INGESTED, Stage.EXTRACTED, Stage.SCORED, Stage.SHORTLISTED)


def sort_untracked(conn, config) -> dict:
    """Give a title track to in-flight jobs that have none (admitted before tracks existed) before any step runs.
    Run 337 (2026-11-01): 46 untracked retail and crew jobs scored 4.6-5.0 and were next in line for the agent."""
    from . import tracks
    cfg = tracks.settings(config)
    marks = ",".join("?" * len(ACTIVE))
    rows = conn.execute(f"SELECT s.posting_id, s.stage, p.title FROM pipeline_state s JOIN postings p ON p.id = s.posting_id "
                        f"WHERE s.stage IN ({marks}) AND json_extract(s.data_json, '$.track') IS NULL",
                        [str(s) for s in ACTIVE]).fetchall()
    out = {}
    for r in rows:
        track = tracks.classify(r["title"] or "", cfg)
        category = cfg.get(track)
        action = category.action if category else "admit"
        if action == "archive" and not getattr(category, "exclusion_confirmed", False):
            action = "admit"
        if track is None and action == "admit":
            continue
        cur = Stage(r["stage"])
        if action == "archive":
            store.move(conn, r["posting_id"], "track", cur, Stage.ARCHIVED, output=track, reason="title_not_target")
        elif action == "side":
            store.move(conn, r["posting_id"], "track", cur, Stage.SIDE, output=track)
        else:
            conn.execute("UPDATE pipeline_state SET data_json=json_set(data_json, '$.track', ?) WHERE posting_id=?",
                         (track, r["posting_id"]))
        key = track if track is not None else "unassigned"
        out[key] = out.get(key, 0) + 1
    conn.commit()
    return out


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
    from . import tracks
    snapshot = tracks.settings(config)
    rows = conn.execute(
        "SELECT posting_id, json_extract(data_json, '$.track') AS track, "
        "CAST(json_extract(data_json, '$.evaluate.overall') AS REAL) AS score FROM pipeline_state "
        "WHERE stage=? AND json_extract(data_json, '$.evaluate.overall') IS NOT NULL",
        (str(Stage.SHORTLISTED),)).fetchall()
    rows = [row for row in rows if snapshot.get(row['track']) is None or snapshot.get(row['track']).promote]
    rows.sort(key=lambda row: (snapshot.get(row['track']).priority if snapshot.get(row['track']) else float('inf'),
                               -row['score'], -row['posting_id']))
    ids = [r["posting_id"] for r in rows[:allowance]]
    if not ids:
        return out
    from pipeline.agentic.service import agentic_batch_run
    for pid in ids:                                         # logged before the call: a crash must not allow a re-promotion
        store.event(conn, pid, "promote", Stage.SHORTLISTED, Stage.SHORTLISTED, 1, None)
    conn.commit()
    out["promoted"] = len(ids)
    out["agentic"] = agentic_batch_run(ids, config, conn, max_seconds=max_seconds, deadline=deadline)
    return out


def _title_triage(conn, config, started, max_seconds) -> dict:
    """Sort unlisted titles by AI before ingest reads ads; at most a quarter of what is left."""
    from . import title_triage, tracks
    if tracks.unlisted_drop(config):                # the keyword step drops them all: nothing left to ask about
        return {"skipped": "unlisted_drop"}
    left = max_seconds - (time.monotonic() - started) if max_seconds else None
    settings = graph.Settings.from_config(config)
    try:
        from jobwatch.util.llm import LLM
        return title_triage.run(conn, config, LLM(), settings.sort_model,
                                deadline=time.monotonic() + left / 4 if left else None)
    except Exception as exc:                        # noqa: BLE001 - never blocks the run: titles stay unlisted
        log.warning("screened: title triage failed: %s", type(exc).__name__)
        return {"error": type(exc).__name__}


def after_collect(conn, config, max_seconds=None, deadline=None) -> dict:
    """Timer hook (jobwatch.run.run): retry transport failures, run the screened graph, then promote."""
    from jobwatch.util import adtext
    started = time.monotonic()
    with adtext.review_lock(adtext.lock_path(config)) as got:
        if not got:
            return {"skipped": "busy"}
        store.ensure(conn)
        from . import category_refresh
        refreshed = category_refresh.refresh(conn, config)
        out = {"category_refreshed": refreshed, "retried": retry_transport(conn),
               "sorted_untracked": sort_untracked(conn, config)}
        # Shortlisted jobs already waiting go to the agent FIRST, with at most half the time; scoring gets the rest.
        # (Run 327, 2026-11-01: promoted after scoring, the agent had under its 120 s start margin left and skipped.)
        waiting = conn.execute("SELECT 1 FROM pipeline_state WHERE stage=? LIMIT 1", (str(Stage.SHORTLISTED),)).fetchone()
        if waiting:
            out["promote"] = promote(conn, config, max_seconds=max_seconds / 2 if max_seconds else None,
                                     deadline=deadline)
        out["title_triage"] = _title_triage(conn, config, started, max_seconds)
        left = max_seconds - (time.monotonic() - started) if max_seconds else None
        g = ScreenedGraph(conn=conn, db_path=str(config.db_path), config=config,
                          settings=graph.Settings.from_config(config))
        out["graph"] = asyncio.run(g.run(max_seconds=left))
        if not waiting:                         # newly shortlisted: the agent gets whatever is left
            left = max_seconds - (time.monotonic() - started) if max_seconds else None
            out["promote"] = promote(conn, config, max_seconds=left, deadline=deadline)
        return out
