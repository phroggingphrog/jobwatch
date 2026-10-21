"""Job expiry: no stale ads in the database (owner 2026-10-20).

Every posting has expires_at (its closing date, else 30 days after posting). When that passes, the job is
re-checked live with the same reader the AI pipeline uses: gone -> closed_at is set and the board hides it;
still open -> expires_at moves to its closing date, or 7 days on, and a closed_at set earlier is cleared;
unreadable -> tried again tomorrow. A closed job is re-checked only when a collector lists it again after it closed,
and at most every RECHECK_CLOSED_DAYS: an aggregator that keeps listing a dead ad never reopens it by itself.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)
DEFAULT_DAYS = 30
RECHECK_CLOSED_DAYS = 3


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def fill_missing(conn) -> int:
    """New postings come in without an expiry: give them posted/first-seen + 30 days."""
    cur = conn.execute("UPDATE postings SET expires_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', "
                       "COALESCE(posted_at, first_seen_at), '+30 days') WHERE expires_at IS NULL")
    conn.commit()
    return cur.rowcount


def record(conn, posting_id: int, observation, now: datetime | None = None) -> None:
    """Store what one live check found."""
    now = now or datetime.now(timezone.utc)
    if observation.status == "closed":
        conn.execute("UPDATE postings SET closed_at=?, expires_at=? WHERE id=?",       # closed_at = last confirmed
                     (_iso(now), _iso(now + timedelta(days=RECHECK_CLOSED_DAYS)), posting_id))
    elif observation.status == "active":
        until = now + timedelta(days=7)
        if observation.expires_at:
            try:
                closes = datetime.fromisoformat(observation.expires_at)
                if closes > now:
                    until = closes
            except ValueError:
                pass
        conn.execute("UPDATE postings SET expires_at=?, closed_at=NULL WHERE id=?", (_iso(until), posting_id))
    else:  # could not read it this time
        conn.execute("UPDATE postings SET expires_at=? WHERE id=?", (_iso(now + timedelta(days=1)), posting_id))
    conn.commit()


def sweep(conn, max_seconds: float = 180, limit: int = 20, observe=None, now: datetime | None = None) -> dict:
    """Re-check the jobs whose expiry has passed, oldest first."""
    if observe is None:
        from pipeline.agentic.liveness import observe_posting as observe
    now = now or datetime.now(timezone.utc)
    fill_missing(conn)
    rows = conn.execute("SELECT id, title, company, location, url, source FROM postings "
                        "WHERE (closed_at IS NULL OR last_seen_at >= closed_at) AND expires_at <= ? "
                        "ORDER BY expires_at LIMIT ?",
                        (_iso(now), limit)).fetchall()
    stop = time.monotonic() + max_seconds
    out = {"checked": 0, "closed": 0, "open": 0, "unknown": 0}
    for row in rows:
        if time.monotonic() >= stop:
            break
        posting = {k: row[k] or "" for k in ("title", "company", "location", "url", "source")}
        try:
            obs = observe({"id": row["id"], **posting}, deadline=min(stop, time.monotonic() + 45))
        except Exception as exc:  # noqa: BLE001 - one bad page never stops the sweep
            log.warning("expiry check %s failed: %s", row["id"], exc)
            continue
        record(conn, row["id"], obs, now)
        out["checked"] += 1
        out[{"closed": "closed", "active": "open"}.get(obs.status, "unknown")] += 1
    return out
