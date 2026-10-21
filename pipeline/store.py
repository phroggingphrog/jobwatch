"""SQLite persistence for the pipeline: one state row per job, an event per move, a dead letter queue.

Additive tables only (existing jobwatch tables are read, never altered). Created on first use.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

from .schemas import Stage

DDL = """
CREATE TABLE IF NOT EXISTS pipeline_state (
    posting_id   INTEGER PRIMARY KEY REFERENCES postings(id) ON DELETE CASCADE,
    stage        TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    data_json    TEXT NOT NULL DEFAULT '{}',   -- validated node outputs by node name (no personal data)
    reason       TEXT,                         -- why archived / why in the DLQ
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pipeline_state_stage ON pipeline_state(stage);
CREATE INDEX IF NOT EXISTS ix_pipeline_state_hash ON pipeline_state(content_hash);
CREATE TABLE IF NOT EXISTS pipeline_events (
    id          INTEGER PRIMARY KEY,
    posting_id  INTEGER NOT NULL,
    at          TEXT NOT NULL,
    node        TEXT NOT NULL,
    from_stage  TEXT,
    to_stage    TEXT NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 1,
    reason      TEXT
);
CREATE INDEX IF NOT EXISTS ix_pipeline_events_posting ON pipeline_events(posting_id);
CREATE TABLE IF NOT EXISTS pipeline_dlq (
    id          INTEGER PRIMARY KEY,
    posting_id  INTEGER NOT NULL,
    stage       TEXT NOT NULL,                 -- the stage the job was in when the node failed
    node        TEXT NOT NULL,
    attempts    INTEGER NOT NULL,
    error       TEXT NOT NULL,                 -- validation / HTTP error text only, never the prompt or ad
    created_at  TEXT NOT NULL,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_pipeline_dlq_open ON pipeline_dlq(resolved_at);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def ensure(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)


def get(conn, posting_id: int) -> dict | None:
    r = conn.execute("SELECT * FROM pipeline_state WHERE posting_id=?", (posting_id,)).fetchone()
    if r is None:
        return None
    d = dict(r)
    d["data"] = json.loads(d.pop("data_json") or "{}")
    return d


def at_stage(conn, stage: Stage, limit: int | None = None) -> list[int]:
    sql = "SELECT posting_id FROM pipeline_state WHERE stage=? ORDER BY updated_at, posting_id"
    rows = conn.execute(sql + (f" LIMIT {int(limit)}" if limit else ""), (str(stage),)).fetchall()
    return [r[0] for r in rows]


def admit(conn, posting_id: int, content_hash: str, data: dict, stage: Stage = Stage.INGESTED,
          reason: str | None = None) -> None:
    conn.execute("INSERT INTO pipeline_state(posting_id, stage, content_hash, data_json, reason, updated_at) "
                 "VALUES(?,?,?,?,?,?)", (posting_id, str(stage), content_hash, json.dumps(data), reason, now()))
    event(conn, posting_id, "ingest", None, stage, 1, reason)


def move(conn, posting_id: int, node: str, from_stage: Stage, to_stage: Stage, *, output: dict | None = None,
         reason: str | None = None, attempts: int = 1) -> None:
    """Record a node result and the move. Fails if the row is not in from_stage (no double processing)."""
    row = get(conn, posting_id)
    if row is None or row["stage"] != str(from_stage):
        raise RuntimeError(f"posting {posting_id} is not in stage {from_stage}")
    data = row["data"]
    if output is not None:
        data[node] = output
    conn.execute("UPDATE pipeline_state SET stage=?, data_json=?, reason=?, updated_at=? WHERE posting_id=?",
                 (str(to_stage), json.dumps(data), reason, now(), posting_id))
    event(conn, posting_id, node, from_stage, to_stage, attempts, reason)


def annotate(conn, posting_id: int, key: str, value: dict) -> None:
    """Add data[key] to an ARCHIVED job without moving it (labels for the board, e.g. why it is not a target).
    Never touches the stage, the reason or the content hash; a job in any other stage is left alone."""
    row = get(conn, posting_id)
    if row is None or row["stage"] != str(Stage.ARCHIVED):
        return
    data = row["data"]
    data[key] = value
    conn.execute("UPDATE pipeline_state SET data_json=? WHERE posting_id=? AND stage=?",
                 (json.dumps(data), posting_id, str(Stage.ARCHIVED)))


def event(conn, posting_id, node, from_stage, to_stage, attempts, reason) -> None:
    conn.execute("INSERT INTO pipeline_events(posting_id, at, node, from_stage, to_stage, attempts, reason) "
                 "VALUES(?,?,?,?,?,?,?)", (posting_id, now(), node, str(from_stage) if from_stage else None,
                                          str(to_stage), attempts, reason))


def dead_letter(conn, posting_id: int, node: str, stage: Stage, attempts: int, error: str) -> None:
    conn.execute("INSERT INTO pipeline_dlq(posting_id, stage, node, attempts, error, created_at) VALUES(?,?,?,?,?,?)",
                 (posting_id, str(stage), node, attempts, error[:2000], now()))
    move(conn, posting_id, node, stage, Stage.DLQ, reason=f"{node} failed {attempts}x", attempts=attempts)


def retry_dlq(conn, dlq_id: int) -> int:
    """Owner/maintainer action: put a dead-lettered job back where it failed. Returns the posting id."""
    d = conn.execute("SELECT * FROM pipeline_dlq WHERE id=? AND resolved_at IS NULL", (dlq_id,)).fetchone()
    if d is None:
        raise KeyError(f"no open DLQ entry {dlq_id}")
    move(conn, d["posting_id"], "dlq_retry", Stage.DLQ, Stage(d["stage"]), reason=f"retry of dlq {dlq_id}")
    conn.execute("UPDATE pipeline_dlq SET resolved_at=? WHERE id=?", (now(), dlq_id))
    return d["posting_id"]


def drafted_since(conn, hours: int = 24) -> int:
    """Drafts the pipeline finished in the last `hours` (the daily cost cap)."""
    since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat(timespec="seconds")
    return conn.execute("SELECT COUNT(*) FROM pipeline_events WHERE node='draft' AND to_stage=? AND at>=?",
                        (str(Stage.DRAFTED), since)).fetchone()[0]


def counts(conn) -> dict[str, int]:
    return {r[0]: r[1] for r in conn.execute("SELECT stage, COUNT(*) FROM pipeline_state GROUP BY stage")}
