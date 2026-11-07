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
# min_score remains readable for old configurations; it is no longer a hard
# admission or promotion cutoff. Score orders work within category priority.
DEFAULTS = {"promote_per_run": 3, "promote_per_day": 10, "min_score": 3.0,
            "refresh_per_run": 5, "refresh_after_hours": 12}
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


def _promoted_ids(conn, hours: int = 24) -> set[int]:
    """Postings promoted in the last day. A job held by the evaluator stays SHORTLISTED; counting every attempt used the
    day's allowance on repeats of the same ~80 postings (2026-11-02: 176 attempts, 100 allowance, 0 READY)."""
    since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat(timespec="seconds")
    return {r[0] for r in conn.execute("SELECT DISTINCT posting_id FROM pipeline_events WHERE node='promote' AND at>=?",
                                       (since,))}


def promote(conn, config, *, max_seconds=None, deadline=None) -> dict:
    """Send the best SHORTLISTED jobs to the agentic evaluator: highest score first, newest id on ties."""
    cfg = screened_settings(config)
    recent = _promoted_ids(conn)
    allowance = max(0, min(cfg["promote_per_run"], cfg["promote_per_day"] - len(recent)))
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
    rows = [row for row in rows if row['posting_id'] not in recent
            and (snapshot.get(row['track']) is None or snapshot.get(row['track']).promote)]
    rows.sort(key=lambda row: (snapshot.get(row['track']).priority if snapshot.get(row['track']) else float('inf'),
                               -row['score'], -row['posting_id']))
    ids = [r["posting_id"] for r in rows[:allowance]]
    if not ids:
        return out
    from pipeline.agentic.service import agentic_batch_run
    started = set()
    def record_start(pid):
        if pid not in started:
            store.event(conn, pid, "promote", Stage.SHORTLISTED, Stage.SHORTLISTED, 1, None)
            conn.commit()
            started.add(pid)
    out["selected"] = len(ids)
    out["agentic"] = agentic_batch_run(ids, config, conn, max_seconds=max_seconds, deadline=deadline,
                                       operation='evaluate', _on_started=record_start)
    out["promoted"] = len(started)
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


def refresh_evaluated(conn, config, *, max_seconds=None, deadline=None) -> dict:
    """Keep already-evaluated postings selectable with bounded, unpaid public observations.

    EVALUATED is terminal for the cheap graph, but its liveness evidence expires after 24 h.
    Re-read a bounded number of stale public ads (no model call). An unchanged ad only renews
    liveness; a changed ad, a closed ad or a changed input run key queues the existing
    ``evaluate`` operation, never preparation.
    """
    cfg = screened_settings(config)
    out = {"checked": 0, "current": 0, "reevaluated": 0, "closed": 0, "skipped": 0, "deferred": []}
    limit = int(cfg["refresh_per_run"])
    if limit <= 0:
        return out
    started = time.monotonic()
    stop = started + max_seconds if max_seconds is not None else None
    if deadline is not None:
        stop = min(stop, deadline) if stop is not None else deadline
    if stop is not None and stop <= started:
        return out
    from jobwatch.candidate.contracts import content_hash
    from jobwatch import users
    from pipeline.agentic import service
    from pipeline.agentic.liveness import latest_observation, observe_posting, record_observation
    from pipeline.agentic.persistence import latest_result
    from pipeline.agentic.store import AgenticStore
    from pipeline.agentic.contracts import AgenticError
    rows = conn.execute("SELECT posting_id FROM pipeline_state WHERE stage=?", (str(Stage.EVALUATED),)).fetchall()
    if not rows:
        return out
    AgenticStore(conn).ensure()
    now = datetime.now(UTC)
    candidates = []
    for (posting_id,) in rows:
        observation = latest_observation(conn, posting_id)
        age = ((now - datetime.fromisoformat(observation.checked_at)).total_seconds()
               if observation is not None else None)
        captured = service._capture(conn, posting_id)
        if captured is None:
            out["skipped"] += 1
            continue
        if observation is not None and age is not None and age <= int(cfg["refresh_after_hours"]) * 3600:
            if observation.status == "unknown":
                continue
            if observation.status == "active" and observation.ad_hash == content_hash(captured[1].encode()):
                continue
        candidates.append((posting_id, observation, captured))
    candidates.sort(key=lambda item: item[1].checked_at if item[1] is not None else "")
    wants_reevaluation = []
    for posting_id, _old, captured in candidates[:limit]:
        if stop is not None and time.monotonic() >= stop:
            out["deferred"].append(posting_id)
            continue
        posting = service._posting(conn, posting_id)
        if not posting:
            out["skipped"] += 1
            continue
        try:
            observation = observe_posting(posting, deadline=stop)
        except AgenticError as exc:
            if getattr(exc, "code", None) == "deadline_exceeded":
                out["deferred"].append(posting_id)
                break
            out["skipped"] += 1
            continue
        run = conn.execute("SELECT run_key,generation FROM agentic_runs WHERE posting_id=? "
                           "ORDER BY generation DESC LIMIT 1", (posting_id,)).fetchone()
        if run is None:
            out["skipped"] += 1
            continue
        record_observation(conn, observation, run_key=run[0], generation=run[1])
        out["checked"] += 1
        if observation.status == "closed":
            out["closed"] += 1
            wants_reevaluation.append(posting_id)
            continue
        if observation.status != "active":
            out["skipped"] += 1
            continue
        if observation.ad_hash != content_hash(captured[1].encode()):
            wants_reevaluation.append(posting_id)
            continue
        try:
            agentic_cfg = service._config(config)
            bundle = service._approved_evidence(users.current())
            policy = service.default_policy()
            inputs = service.load_inputs(bundle, agentic_cfg)
            key = service._run_key(posting_id, captured, bundle, policy, agentic_cfg, inputs, conn=conn)
            previous = latest_result(conn, posting_id)
        except Exception as exc:                         # noqa: BLE001 - a bad saved artifact is not a new ad
            log.warning("screened: liveness key %s failed: %s", posting_id, type(exc).__name__)
            out["skipped"] += 1
            continue
        if previous is None or previous.get("run_key") != key.value:
            wants_reevaluation.append(posting_id)
        else:
            out["current"] += 1
    if wants_reevaluation:
        from pipeline.agentic.service import agentic_batch_run
        remaining = max(0.1, stop - time.monotonic()) if stop is not None else None
        out["agentic"] = agentic_batch_run(wants_reevaluation[:limit], config, conn, operation="evaluate",
                                           max_seconds=remaining, deadline=stop)
        out["reevaluated"] = len(wants_reevaluation[:limit])
    return out


def after_collect(conn, config, max_seconds=None, deadline=None) -> dict:
    """Timer hook (jobwatch.run.run): retry, run the screened graph, refresh liveness, then promote."""
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
        # Evaluated postings need a bounded liveness renewal before their 24 h observation
        # expires; this path is public-read only unless the ad or inputs actually changed.
        refresh_budget = min(left / 4, 120.0) if left is not None else None
        out["refresh"] = refresh_evaluated(conn, config, max_seconds=refresh_budget, deadline=deadline)
        if not waiting:                         # newly shortlisted: the agent gets whatever is left
            left = max_seconds - (time.monotonic() - started) if max_seconds else None
            out["promote"] = promote(conn, config, max_seconds=left, deadline=deadline)
        return out
