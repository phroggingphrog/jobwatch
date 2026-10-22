"""Which policy decided a run: one row per run and policy hash, so a later pass can tell whether a held job
needs a new decision. Written only when the profile path is active; the legacy gate writes nothing.

The table is created on first use (the `AgenticStore.ensure` pattern), not by a `db.py` migration."""
from __future__ import annotations

import sqlite3
import time
from typing import Any


def ensure(conn: sqlite3.Connection) -> None:
    conn.execute('CREATE TABLE IF NOT EXISTS gate_decisions('
                 'run_key TEXT NOT NULL, policy_hash TEXT NOT NULL, profile_version INTEGER NOT NULL, '
                 'route TEXT NOT NULL, reason TEXT NOT NULL, decided_at REAL NOT NULL, '
                 'PRIMARY KEY(run_key, policy_hash))')


def record(conn: sqlite3.Connection, run_key: str, dp: Any, decision: Any) -> None:
    ensure(conn)
    conn.execute('INSERT OR REPLACE INTO gate_decisions(run_key,policy_hash,profile_version,route,reason,decided_at) '
                 'VALUES(?,?,?,?,?,?)',
                 (run_key, dp.policy_hash, dp.profile_version, decision.route, decision.reason, time.time()))
    conn.commit()


def latest(conn: sqlite3.Connection, run_key: str) -> dict | None:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gate_decisions'").fetchone() is None:
        return None
    row = conn.execute('SELECT run_key,policy_hash,profile_version,route,reason,decided_at FROM gate_decisions '
                       'WHERE run_key=? ORDER BY decided_at DESC, rowid DESC LIMIT 1', (run_key,)).fetchone()
    if row is None:
        return None
    return dict(zip(('run_key', 'policy_hash', 'profile_version', 'route', 'reason', 'decided_at'), row))
