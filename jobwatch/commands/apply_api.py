"""Lazy bindings to Agent A's API (PLAN-apply "Ownership").

  jobwatch.apply.chain.start_draft(conn, match_id: int, actor_event: str) -> int
  jobwatch.apply.chain.draft_status(conn, application_id) -> dict
  jobwatch.ledger.append(kind: str, record: dict) / upsert(conn, kind, table, values)

Imported on first use so the commands/outcomes layer works (and is testable) before or without
the apply chain. Tests replace these with stubs of the same signature.
"""
from __future__ import annotations

import importlib


class DraftUnavailable(RuntimeError):
    """The apply chain (jobwatch.apply.chain) is not installed."""


def _chain():
    try:
        return importlib.import_module("jobwatch.apply.chain")
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("jobwatch.apply"):
            raise DraftUnavailable("the apply chain (jobwatch.apply.chain) is not installed yet") from exc
        raise


def start_draft(conn, match_id: int, actor_event: str) -> int:
    return _chain().start_draft(conn, match_id, actor_event)


def draft_status(conn, application_id) -> dict:
    return _chain().draft_status(conn, application_id)


def ledger():
    """The ledger module (append/upsert). Row writes to apply tables must go through
    ledger.upsert so `jobwatch reindex` can rebuild them."""
    return importlib.import_module("jobwatch.ledger")


def upsert(conn, kind: str, table: str, values: dict, *, commit: bool = True) -> dict:
    if table == "commands" and "event_id" in values:
        # commands has a TEXT primary key: create the row first so the ledger's update-by-key path
        # is used (an insert there looks the row up by rowid). Same transaction; rolled back with it.
        cols = [k for k in values if k in ("event_id", "room_id", "sender", "received_at", "status")]
        conn.execute(f"INSERT OR IGNORE INTO commands({','.join(cols)}) VALUES({','.join('?' for _ in cols)})",
                     [values[k] for k in cols])
    return ledger().upsert(conn, kind, table, values, commit=commit)


def append(kind: str, record: dict) -> dict:
    return ledger().append(kind, record)
