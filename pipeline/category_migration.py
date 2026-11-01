"""Plan legacy policy conversion and migrate persisted category IDs safely.

These functions do not activate configuration or access a database themselves.
The caller must stop pipeline writers and coordinate configuration activation.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
import sqlite3
import uuid

from .category_snapshot import CategorySnapshot


def migrate_legacy(screened: dict, *, legacy_program_phrases: list[str],
                   legacy_policy: list[dict], program_category: str,
                   id_mapping: dict[str, str]) -> dict:
    """Convert caller-supplied legacy vocabulary and policy into explicit data."""
    old = deepcopy(screened)
    lists = old.get("tracks") or {}
    if set(id_mapping) != {item["id"] for item in legacy_policy}:
        raise ValueError("mapping must cover exactly the legacy policy IDs")
    if program_category not in id_mapping or set(lists) - set(id_mapping):
        raise ValueError("legacy tracks or program category have no mapping")
    categories = []
    for policy in legacy_policy:
        item = deepcopy(policy)
        old_id = item["id"]
        item["id"] = id_mapping[old_id]
        words = list(lists.get(old_id) or [])
        if old_id == program_category:
            words = list(legacy_program_phrases) + words
        item["phrases"] = words
        # Preservation is a reviewed migration operation, not inferred runtime
        # intent. The caller explicitly supplies the legacy action policy.
        item.setdefault("exclusion_confirmed", item.get("action") == "archive")
        categories.append(item)
    snapshot = CategorySnapshot.model_validate({"categories": categories})
    result = deepcopy(old)
    result.pop("tracks", None)
    unlisted = result.pop("unlisted", "keep")
    result["unlisted_action"] = "archive" if str(unlisted).casefold() == "drop" else "admit"
    result["category_snapshot"] = snapshot.model_dump(mode="json")
    return {"previous": old, "migrated": result, "id_mapping": deepcopy(id_mapping)}


@contextmanager
def _atomic(conn):
    # A savepoint respects an existing caller transaction and does not commit it.
    name = "category_" + uuid.uuid4().hex
    conn.execute(f"SAVEPOINT {name}")
    try:
        yield
    except BaseException:
        conn.execute(f"ROLLBACK TO {name}")
        conn.execute(f"RELEASE {name}")
        raise
    else:
        conn.execute(f"RELEASE {name}")


def _table_exists(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _mapped(value, mapping, *, neutral=False):
    if value is None or (neutral and value == "unsure"):
        return value
    if not isinstance(value, str) or value not in mapping:
        raise ValueError(f"unmapped category ID: {value!r}")
    return mapping[value]


def migrate_persisted(conn: sqlite3.Connection, mapping: dict[str, str], *,
                      target_snapshot: CategorySnapshot, source_snapshot_hash: str | None,
                      target_snapshot_hash: str) -> str:
    """Map known persisted tracks and journal exact changes for guarded rollback.

    Caller supplies hashes from title_triage.snapshot_hash. A None source hash
    permits only unversioned legacy triage rows. No commits occur inside an
    existing transaction. A standalone call commits when its savepoint releases.
    """
    from .title_triage import snapshot_hash

    if not mapping or any(not isinstance(k, str) or not k or not isinstance(v, str)
                          or target_snapshot.get(v) is None for k, v in mapping.items()):
        raise ValueError("mapping must contain valid source and target IDs")
    if target_snapshot_hash != snapshot_hash(target_snapshot):
        raise ValueError("target snapshot hash does not match snapshot")
    migration_id = uuid.uuid4().hex
    with _atomic(conn):
        conn.execute("CREATE TABLE IF NOT EXISTS category_migration_audit ("
                     "id TEXT PRIMARY KEY, mapping_json TEXT NOT NULL, changes_json TEXT NOT NULL, "
                     "source_hash TEXT, target_hash TEXT NOT NULL, rolled_back INTEGER NOT NULL DEFAULT 0)")
        # Acquire the SQLite write lock before reading rows, including in nested transactions.
        conn.execute("INSERT INTO category_migration_audit VALUES (?, ?, '[]', ?, ?, 0)",
                     (migration_id, json.dumps(mapping, sort_keys=True), source_snapshot_hash, target_snapshot_hash))
        changes = []
        if _table_exists(conn, "pipeline_state"):
            for pid, stage, raw in conn.execute("SELECT posting_id, stage, data_json FROM pipeline_state").fetchall():
                try:
                    data = json.loads(raw)
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"invalid state JSON for posting {pid}") from exc
                if not isinstance(data, dict):
                    raise ValueError(f"invalid state JSON object for posting {pid}")
                if "track" not in data:
                    continue
                old = data["track"]
                new = _mapped(old, mapping)
                if old != new:
                    data["track"] = new
                    updated = json.dumps(data, ensure_ascii=False)
                    conn.execute("UPDATE pipeline_state SET data_json=? WHERE posting_id=?", (updated, pid))
                    changes.append(["state", pid, stage, raw, updated])
        if _table_exists(conn, "title_triage"):
            if not _table_exists(conn, "title_triage_versions"):
                conn.execute("CREATE TABLE title_triage_versions(posting_id INTEGER PRIMARY KEY, snapshot_hash TEXT NOT NULL)")
            if conn.execute("SELECT 1 FROM title_triage_versions v LEFT JOIN title_triage t "
                            "ON t.posting_id=v.posting_id WHERE t.posting_id IS NULL LIMIT 1").fetchone():
                raise ValueError("orphaned title triage snapshot")
            rows = conn.execute("SELECT t.posting_id,t.track,t.at,v.snapshot_hash FROM title_triage t "
                                "LEFT JOIN title_triage_versions v ON v.posting_id=t.posting_id").fetchall()
            for pid, old, at, old_hash in rows:
                if old_hash != source_snapshot_hash:
                    raise ValueError(f"unexpected title triage snapshot for posting {pid}")
                new = _mapped(old, mapping, neutral=True)
                if old != new or old_hash != target_snapshot_hash:
                    conn.execute("UPDATE title_triage SET track=? WHERE posting_id=?", (new, pid))
                    conn.execute("INSERT INTO title_triage_versions(posting_id,snapshot_hash) VALUES (?,?) "
                                 "ON CONFLICT(posting_id) DO UPDATE SET snapshot_hash=excluded.snapshot_hash",
                                 (pid, target_snapshot_hash))
                    changes.append(["triage", pid, at, old, new, old_hash, target_snapshot_hash])
        conn.execute("UPDATE category_migration_audit SET changes_json=? WHERE id=?",
                     (json.dumps(changes, ensure_ascii=False), migration_id))
    return migration_id


def rollback_persisted(conn: sqlite3.Connection, migration_id: str) -> None:
    """Restore only journaled rows, or restore nothing if any row changed."""
    with _atomic(conn):
        # The no-op write obtains the lock before checking the journal and rows.
        conn.execute("UPDATE category_migration_audit SET rolled_back=rolled_back WHERE id=?", (migration_id,))
        row = conn.execute("SELECT changes_json,rolled_back FROM category_migration_audit WHERE id=?",
                           (migration_id,)).fetchone()
        if row is None or row[1]:
            raise ValueError("migration does not exist or was already rolled back")
        changes = json.loads(row[0])
        for change in changes:
            if change[0] == "state":
                _, pid, stage, old, new = change
                current = conn.execute("SELECT stage,data_json FROM pipeline_state WHERE posting_id=?", (pid,)).fetchone()
                if current is None or tuple(current) != (stage, new):
                    raise RuntimeError(f"pipeline state changed for posting {pid}")
            elif change[0] == "triage":
                _, pid, at, old, new, old_hash, new_hash = change
                current = conn.execute("SELECT t.track,t.at,v.snapshot_hash FROM title_triage t "
                                       "LEFT JOIN title_triage_versions v ON v.posting_id=t.posting_id "
                                       "WHERE t.posting_id=?", (pid,)).fetchone()
                if current is None or tuple(current) != (new, at, new_hash):
                    raise RuntimeError(f"title triage changed for posting {pid}")
            else:
                raise ValueError("unknown migration journal entry")
        for change in changes:
            if change[0] == "state":
                _, pid, _, old, _ = change
                conn.execute("UPDATE pipeline_state SET data_json=? WHERE posting_id=?", (old, pid))
            else:
                _, pid, _, old, _, old_hash, _ = change
                conn.execute("UPDATE title_triage SET track=? WHERE posting_id=?", (old, pid))
                if old_hash is None:
                    conn.execute("DELETE FROM title_triage_versions WHERE posting_id=?", (pid,))
                else:
                    conn.execute("UPDATE title_triage_versions SET snapshot_hash=? WHERE posting_id=?", (old_hash, pid))
        conn.execute("UPDATE category_migration_audit SET rolled_back=1 WHERE id=?", (migration_id,))
