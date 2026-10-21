"""Append-only JSONL ledger: the canonical system layer (PLAN-apply D2).

Files under <data>/ledger/: applications.jsonl, drafts.jsonl, outcomes.jsonl, commands.jsonl.
Every line: {"v": SCHEMA_VERSION, "at": <utc iso>, "kind": <file kind>, ...record}.
Lines are written with O_APPEND under an flock and fsync'd.

Two kinds of record:
* free log records: `append(kind, record)`; kept for audit, ignored by reindex.
* row records: `upsert(conn, kind, table, values)` writes the DB row and logs the *full*
  row as {"op": "upsert", "table": t, "row": {...}}; `reindex` replays these.

`reindex(conn)` clears the apply tables and replays every row record (last write wins per
primary key). It refuses (no change) if the DB holds a row the ledger does not know, so it
can never lose data that was written without going through the ledger.
"""
from __future__ import annotations

import fcntl
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from .apply.paths import ensure_dir, guard_write, ledger_dir

SCHEMA_VERSION = 1
KINDS = ("applications", "drafts", "outcomes", "commands")
ALIASES = {"application": "applications", "draft": "drafts", "outcome": "outcomes",
           "command": "commands"}
# replay order respects foreign keys
APPLY_TABLES = ("applications", "application_events", "drafts", "requirements", "commands",
                "outcome_proposals", "interview_inputs", "interview_runs",
                "interview_subjects", "interview_subject_runs")


class ReindexRefused(RuntimeError):
    pass


def _kind(kind: str) -> str:
    k = ALIASES.get(kind, kind)
    if k not in KINDS:
        raise ValueError(f"unknown ledger kind {kind!r} (expected one of {KINDS})")
    return k


def path_for(kind: str) -> Path:
    return ledger_dir() / f"{_kind(kind)}.jsonl"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def append(kind: str, record: dict) -> dict:
    """Append one record (fsync'd). Returns the stored record."""
    k = _kind(kind)
    rec = {"v": SCHEMA_VERSION, "at": _now(), "kind": k}
    rec.update({key: val for key, val in record.items() if key not in ("v", "kind")})
    line = json.dumps(rec, sort_keys=True, ensure_ascii=False, default=str) + "\n"
    d = ensure_dir(ledger_dir())
    p = guard_write(path_for(k))
    new = not p.exists()
    fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    if new:
        dfd = os.open(d, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    return rec


def read(kind: str) -> Iterator[dict]:
    p = path_for(kind)
    if not p.exists():
        return
    with p.open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError as exc:
                raise ValueError(f"{p.name}:{n}: corrupt ledger line") from exc


# -- row records ---------------------------------------------------------------
def _columns(conn: sqlite3.Connection, table: str) -> list[tuple[str, bool]]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if not rows:
        raise ValueError(f"unknown table {table}")
    return [(r[1], bool(r[5])) for r in rows]


def _pk(conn, table: str) -> str:
    pks = [c for c, is_pk in _columns(conn, table) if is_pk]
    if len(pks) != 1:
        raise ValueError(f"{table}: expected a single-column primary key")
    return pks[0]


def _write_row(conn, table: str, values: dict) -> dict:
    cols = [c for c, _ in _columns(conn, table)]
    vals = {k: v for k, v in values.items() if k in cols}
    pk = _pk(conn, table)
    names = ",".join(vals)
    marks = ",".join("?" for _ in vals)
    exists = pk in vals and conn.execute(f"SELECT 1 FROM {table} WHERE {pk}=?", (vals[pk],)).fetchone()
    if exists:  # partial update by primary key
        sets = [c for c in vals if c != pk]
        if sets:
            conn.execute(f"UPDATE {table} SET {','.join(f'{c}=?' for c in sets)} WHERE {pk}=?",
                         [vals[c] for c in sets] + [vals[pk]])
        key = vals[pk]
    else:
        cur = conn.execute(f"INSERT INTO {table}({names}) VALUES({marks})", list(vals.values()))
        key = vals[pk] if pk in vals else cur.lastrowid   # TEXT keys (commands.event_id)
    row = conn.execute(f"SELECT * FROM {table} WHERE {pk}=?", (key,)).fetchone()
    return {c: row[i] for i, c in enumerate(cols)}


def upsert(conn: sqlite3.Connection, kind: str, table: str, values: dict, *,
           commit: bool = True) -> dict:
    """Write a row (insert, or update by primary key) and log the full row to the ledger.
    The ledger line is fsync'd before the DB commit; on a ledger failure the DB rolls back."""
    if table not in APPLY_TABLES:
        raise ValueError(f"{table} is not an apply-layer table")
    try:
        row = _write_row(conn, table, values)
        append(kind, {"op": "upsert", "table": table, "row": row})
    except BaseException:
        conn.rollback()
        raise
    if commit:
        conn.commit()
    return row


def snapshot(conn, tables=APPLY_TABLES) -> dict[str, list[dict]]:
    out = {}
    for t in tables:
        pk = _pk(conn, t)
        cols = [c for c, _ in _columns(conn, t)]
        out[t] = [{c: r[i] for i, c in enumerate(cols)}
                  for r in conn.execute(f"SELECT * FROM {t} ORDER BY {pk}")]
    return out


def _row_records() -> dict[str, list[dict]]:
    """Row records per table, ordered by write time (stable across files)."""
    found: list[tuple[str, int, str, dict]] = []
    for kind in KINDS:
        for n, rec in enumerate(read(kind)):
            if rec.get("op") == "upsert" and rec.get("table") in APPLY_TABLES \
                    and isinstance(rec.get("row"), dict):
                found.append((rec.get("at", ""), n, rec["table"], rec["row"]))
    found.sort(key=lambda x: (x[0], x[1]))
    rows: dict[str, list[dict]] = {t: [] for t in APPLY_TABLES}
    for _, _, table, row in found:
        rows[table].append(row)
    return rows


def reindex(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    """Rebuild the apply tables from the ledger. Idempotent."""
    def require_reconciled_outbox() -> None:
        # An existing row can have a newer durable update waiting for its JSONL
        # append. The unknown-primary-key check below cannot detect that case.
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                              "AND name='agentic_ledger_outbox'").fetchone()
        if exists and conn.execute('SELECT 1 FROM agentic_ledger_outbox WHERE sent=0 LIMIT 1').fetchone():
            raise ReindexRefused('pending agentic ledger records; reconcile before rebuilding '
                                 '(nothing changed)')

    require_reconciled_outbox()
    recs = _row_records()
    final: dict[str, dict] = {}
    for t in APPLY_TABLES:
        pk = _pk(conn, t)
        latest: dict = {}
        for row in recs[t]:
            latest[row[pk]] = row
        final[t] = latest
        db_keys = {r[0] for r in conn.execute(f"SELECT {pk} FROM {t}")}
        unknown = db_keys - set(latest)
        if unknown:
            raise ReindexRefused(f"{t}: {len(unknown)} DB row(s) are not in the ledger; "
                                 "refusing to rebuild (nothing changed)")
    counts = {t: len(final[t]) for t in APPLY_TABLES}
    if dry_run:
        return counts
    if conn.in_transaction:
        conn.commit()
    try:
        conn.execute("BEGIN IMMEDIATE")
        require_reconciled_outbox()
        conn.execute("PRAGMA defer_foreign_keys=ON")
        for t in reversed(APPLY_TABLES):
            conn.execute(f"DELETE FROM {t}")
        for t in APPLY_TABLES:
            cols = [c for c, _ in _columns(conn, t)]
            for row in final[t].values():
                vals = [row.get(c) for c in cols]
                conn.execute(f"INSERT INTO {t}({','.join(cols)}) VALUES({','.join('?' for _ in cols)})",
                             vals)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return counts
