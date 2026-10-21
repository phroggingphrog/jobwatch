"""One `jobwatch run`: collect -> dedupe/store -> filter -> queue matches -> publish to the board -> health."""
from __future__ import annotations

import json
import logging
import time
from datetime import timedelta

from . import collectors as registry
from . import db as dbm
from .collectors.base import CollectorContext
from .config import Config
from .dedupe import ingest
from .filters import Rules
from .http import Fetcher
from .models import canonical_url, now_utc, parse_date
from .place import person_state

log = logging.getLogger("jobwatch")


def tier_collectors(config: Config, tier: str, only: str | None) -> list[str]:
    if only:
        registry.get(only)                      # validates the name
        return [only]
    tiers = config.settings["tiers"]
    names = tiers["fast"] + tiers["slow"] if tier == "all" else tiers[tier]
    return [n for n in dict.fromkeys(names) if n in registry.COLLECTORS]   # a collector may sit in both tiers


def _alert_status(conn, posting, seeded: bool, max_age_h: float, now) -> str:
    """queued if fresh enough to alert; 'stale' = stored but never alerted."""
    if posting.posted_at_source == "provider":
        dt = parse_date(posting.posted_at)
        if dt and now - dt <= timedelta(hours=max_age_h):
            return "queued"
        return "stale"
    # Observed date only: alert unless this is the first time we read this employer/feed
    # (the first read seeds the DB so a whole existing board is not alerted at once).
    return "queued" if seeded else "stale"


def run_collector(conn, config: Config, rules: Rules, http: Fetcher, name: str, run_id: int,
                  limit: int | None, tier: str = "fast") -> dict:
    module = registry.get(name)
    ctx = CollectorContext(
        config=config, http=http, limit=limit, tier=tier, title_relevant=rules.title_relevant,
        is_known=lambda source, sid: conn.execute(
            "SELECT 1 FROM sightings WHERE source=? AND (source_id=? OR url=?) LIMIT 1",
            (source, sid, canonical_url(sid) if sid.startswith("http") else "")).fetchone() is not None,
        state_get=lambda key, default=None: dbm.get_state(conn, key, default),
        state_set=lambda key, value: dbm.set_state(conn, key, value),
    )
    since = dbm.last_ok(conn, name)
    started = time.monotonic()
    postings, crash = [], None
    try:
        postings = module.collect(ctx, since)
    except Exception as exc:  # a collector must never crash the run
        crash = f"{type(exc).__name__}: {str(exc)[:200]}"
        log.exception("collector %s crashed", name)
    latency = int((time.monotonic() - started) * 1000)

    stats = {"collector": name, "fetched": ctx.raw_count, "au_kept": len(postings),
             "vic": sum(1 for p in postings if not person_state() or p.state == person_state()), "new": 0,
             "matched": 0, "queued": 0, "rejected": {}, "errors": ctx.errors + ([crash] if crash else [])}
    now = now_utc()
    max_age = float(config.settings["alerts"].get("max_age_hours", 72))
    seeded_keys = set(dbm.get_state(conn, f"seeded:{name}", []) or [])
    for p in postings:
        try:
            posting_id, is_new = ingest(conn, p, run_id)
        except Exception as exc:
            stats["errors"].append(f"store {p.source_id}: {exc}"[:200])
            continue
        if not is_new:
            continue
        stats["new"] += 1
        decision = rules.evaluate(p)
        if not decision.matched:
            stats["rejected"][decision.reason] = stats["rejected"].get(decision.reason, 0) + 1
            continue
        stats["matched"] += 1
        cur = conn.execute(
            "INSERT OR IGNORE INTO matches(posting_id, arm, arm_tier, arms_json, rules_json, flags_json, "
            "matched_at) VALUES(?,?,?,?,?,?,?)",
            (posting_id, decision.arm, decision.arm_tier, json.dumps(decision.arms),
             json.dumps(decision.rules), json.dumps(decision.flags), dbm.ts()))
        if cur.rowcount:
            status = _alert_status(conn, p, p.origin in seeded_keys, max_age, now)
            stats["queued"] += status == "queued"
            conn.execute("INSERT OR IGNORE INTO alerts(match_id, status, created_at) VALUES(?,?,?)",
                         (cur.lastrowid, status, dbm.ts()))
    seeded_keys |= {p.origin for p in postings}
    dbm.set_state(conn, f"seeded:{name}", sorted(seeded_keys))
    for row in ctx.reddit_posts:
        conn.execute(
            "INSERT OR IGNORE INTO reddit_posts(id, subreddit, stream, title, url, summary, themes_json, "
            "score, comments, published_at, seen_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (row["id"], row["subreddit"], row["stream"], row["title"], row["url"], row["summary"],
             json.dumps(row["themes"]), row["score"], row["comments"], row["published_at"], dbm.ts()))
    stats["reddit_rows"] = len(ctx.reddit_posts)
    conn.commit()

    if crash or (stats["errors"] and not postings and not ctx.origins):
        status = "error"                        # nothing at all was read successfully
    elif stats["errors"]:
        status = "partial"
    elif not postings and not ctx.origins:
        status = "skipped"                      # nothing configured for this collector
    else:
        status = "ok"
    stats["status"] = status
    stats["health"] = dbm.record_health(conn, name, status, len(postings), latency,
                                        "; ".join(stats["errors"])[:1000] or None)
    stats["latency_ms"] = latency
    return stats


def publish(conn, dry_run: bool = False) -> dict:
    """No push channel, so `alerts.status` is bookkeeping only: fresh matches go 'queued' -> 'board' ('stale'
    = old or seed postings). The web board decides NEW itself (unviewed), not from this table.
    A dry run changes nothing, so it can never consume rows that a live run should publish."""
    if dry_run:
        n = conn.execute("SELECT COUNT(*) FROM alerts WHERE status IN ('queued','held')").fetchone()[0]
        return {"would_publish": n}
    cur = conn.execute("UPDATE alerts SET status='board', sent_at=? WHERE status IN ('queued','held')",
                       (dbm.ts(),))
    conn.commit()
    return {"board": cur.rowcount}


UNIT_BUDGET_S = 780          # the whole run stays under the 900 s systemd limit: 120 s for a model call still in flight
SLOW_UNIT_BUDGET_S = 2100    # the slow unit may run 45 min; collection takes ~12-14 of them, so the AI step gets the rest, bounded
MIN_AI_S = 60                # the AI step always gets at least this long


def ai_budget(started: float, config: Config | None = None, tier: str = "fast") -> float:
    """Seconds the AI step may use: what is left of UNIT_BUDGET_S since the run started (at least MIN_AI_S), and no
    more than reader.max_seconds when the owner set one."""
    left = max(MIN_AI_S, (SLOW_UNIT_BUDGET_S if tier == "slow" else UNIT_BUDGET_S) - (time.monotonic() - started))
    own = ((config.settings.get("reader") or {}).get("max_seconds") if config else None)
    return min(left, own) if isinstance(own, (int, float)) and own > 0 else left


def run(config: Config, tier: str, dry_run: bool = False, only: str | None = None,
        limit: int | None = None, printer=print, now=None) -> dict:
    started = time.monotonic()
    conn = dbm.connect(config.db_path)
    run_id = dbm.start_run(conn, "run", only or tier, dry_run)
    results: list[dict] = []
    note: dict = {}
    pruned = 0
    ai: dict = {}
    http = None
    error = None
    try:
        rules = Rules(config.rules, config.employers)
        http_conf = config.settings.get("http") or {}
        http = Fetcher(timeout=http_conf.get("timeout", 20), min_delay=http_conf.get("min_delay", 1.5))
        for name in tier_collectors(config, tier, only):
            results.append(run_collector(conn, config, rules, http, name, run_id, limit, tier))
        note = publish(conn, dry_run)
        pruned = dbm.prune(conn, int(config.settings.get("retention_days", 90)))
        if not dry_run:
            # last on purpose: it is the only step that waits on outside services; its budget is what is left of the
            # unit's time, so a stalled model can no longer cost the publish and prune above or the run record below
            from . import reader
            try:
                import pipeline.graph as graph          # the deterministic state pipeline, when the owner switched it on
                from pipeline.agentic import service as agentic
                from .execution_mode import effective_mode
                mode = effective_mode(config)
                if mode == 'agentic':
                    ai = {"agentic": agentic.after_collect(conn, config, max_seconds=ai_budget(started, config, tier), collector_run_id=run_id)}
                elif mode == 'pipeline':
                    ai = {"pipeline": graph.after_collect(conn, config, max_seconds=ai_budget(started, config, tier))}
                elif mode == 'reader':
                    ai = reader.after_collect(conn, config, max_seconds=ai_budget(started, config, tier))
                else:
                    ai = {'status': 'deferred', 'reason': 'execution_disabled'}
                ai['execution_mode'] = mode
            except Exception as exc:  # the AI step must never fail a collection run
                log.error("reader hook failed: %s", type(exc).__name__)
                ai = {"error": type(exc).__name__}
                try:
                    from jobwatch.notify import alert
                    alert(conn, f"the AI step of the job check crashed ({type(exc).__name__}).", "ai_step_crash")
                except Exception:  # noqa: BLE001
                    pass
    except BaseException as exc:                # recorded, then raised again: a crashed run must not look like an empty one
        error = type(exc).__name__              # the class only: a message could hold anything
        raise
    finally:
        summary = {"run_id": run_id, "collectors": [{k: v for k, v in r.items() if k != "health"} for r in results],
                   "alerts": note, "ai": ai, "pruned": pruned, "requests": http.requests_made if http else 0}
        if error:
            summary["error"] = error
        try:
            dbm.finish_run(conn, run_id, summary)
        finally:
            conn.close()
    return summary
