import json
import sqlite3
from types import SimpleNamespace

import pytest

from pipeline import tracks
from pipeline.category_migration import migrate_legacy, migrate_persisted, rollback_persisted
from pipeline.category_snapshot import CategorySnapshot
from pipeline.title_triage import snapshot_hash


POLICY = [
    {"id": "undergraduate", "label": "program", "priority": 0, "action": "admit", "promote": True, "hours": "allow_hours_only"},
    {"id": "primary", "label": "primary", "priority": 1, "action": "admit", "promote": True, "hours": "standard"},
    {"id": "secondary", "label": "secondary", "priority": 2, "action": "side", "promote": False, "hours": "standard"},
    {"id": "drop", "label": "drop", "priority": 3, "action": "archive", "promote": False, "hours": "standard"},
]
MAPPING = {p["id"]: p["id"] for p in POLICY}


def plan(previous, mapping=MAPPING):
    return migrate_legacy(previous, legacy_program_phrases=["graduate", "trainee"],
                          legacy_policy=POLICY, program_category="undergraduate", id_mapping=mapping)


def test_synthetic_legacy_migration_preserves_order_and_policy():
    previous = {"tracks": {"primary": ["clerk"], "secondary": ["chef"], "drop": ["support"]}, "unlisted": "drop"}
    migration = plan(previous)
    cfg = SimpleNamespace(settings={"pipeline": {"screened": migration["migrated"]}})
    snapshot = tracks.settings(cfg)
    assert tracks.classify("Graduate Chef", snapshot) == "undergraduate"
    assert tracks.classify("Support Trainee", snapshot) == "undergraduate"
    assert tracks.classify("Office Clerk", snapshot) == "primary"
    assert snapshot.get("secondary").action == "side"
    assert not snapshot.get("secondary").promote
    assert snapshot.get("undergraduate").hours == "allow_hours_only"
    assert tracks.unlisted_drop(cfg)
    assert migration["previous"] == previous


def database():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE pipeline_state(posting_id INTEGER PRIMARY KEY, stage TEXT, data_json TEXT)")
    conn.execute("CREATE TABLE title_triage(posting_id INTEGER PRIMARY KEY, track TEXT, at TEXT)")
    conn.execute("CREATE TABLE title_triage_versions(posting_id INTEGER PRIMARY KEY, snapshot_hash TEXT)")
    conn.execute("INSERT INTO pipeline_state VALUES (1, 'shortlisted', ?)", ('{"track":"primary","evaluate":{"overall":4}}',))
    conn.execute("INSERT INTO pipeline_state VALUES (2, 'ingested', '{}')")
    conn.execute("INSERT INTO title_triage VALUES (3, 'primary', 'yesterday')")
    conn.execute("INSERT INTO title_triage VALUES (4, 'unsure', 'today')")
    conn.commit()
    return conn


def snapshot():
    data = plan({"tracks": {"primary": ["admin"]}}, {**MAPPING, "primary": "clerical"})["migrated"]["category_snapshot"]
    return CategorySnapshot.model_validate(data)


def apply(conn):
    snap = snapshot()
    return migrate_persisted(conn, {**MAPPING, "primary": "clerical"}, target_snapshot=snap,
                             source_snapshot_hash=None, target_snapshot_hash=snapshot_hash(snap))


def test_map_and_rollback_only_changed_rows_preserving_audit():
    conn = database()
    original = conn.execute("SELECT * FROM pipeline_state ORDER BY posting_id").fetchall()
    mid = apply(conn)
    assert json.loads(conn.execute("SELECT data_json FROM pipeline_state WHERE posting_id=1").fetchone()[0])["track"] == "clerical"
    assert conn.execute("SELECT track FROM title_triage WHERE posting_id=3").fetchone()[0] == "clerical"
    assert conn.execute("SELECT COUNT(*) FROM title_triage_versions").fetchone()[0] == 2
    conn.execute("UPDATE pipeline_state SET data_json='{\"other\": 1}' WHERE posting_id=2")
    rollback_persisted(conn, mid)
    assert conn.execute("SELECT * FROM pipeline_state WHERE posting_id=1").fetchone() == original[0]
    assert conn.execute("SELECT data_json FROM pipeline_state WHERE posting_id=2").fetchone()[0] == '{"other": 1}'
    assert conn.execute("SELECT track FROM title_triage WHERE posting_id=3").fetchone()[0] == "primary"
    assert conn.execute("SELECT COUNT(*) FROM title_triage_versions").fetchone()[0] == 0
    assert conn.execute("SELECT rolled_back FROM category_migration_audit").fetchone()[0] == 1


def test_unknown_track_fails_atomically():
    conn = database()
    conn.execute("INSERT INTO pipeline_state VALUES (5, 'ingested', '{\"track\":\"unknown\"}')")
    before = conn.execute("SELECT * FROM pipeline_state").fetchall()
    with pytest.raises(ValueError, match="unmapped"):
        apply(conn)
    assert conn.execute("SELECT * FROM pipeline_state").fetchall() == before
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='category_migration_audit'").fetchone() is None


def test_rollback_conflict_is_atomic():
    conn = database()
    mid = apply(conn)
    conn.execute("UPDATE title_triage SET track='changed' WHERE posting_id=3")
    with pytest.raises(RuntimeError, match="changed"):
        rollback_persisted(conn, mid)
    assert json.loads(conn.execute("SELECT data_json FROM pipeline_state WHERE posting_id=1").fetchone()[0])["track"] == "clerical"
    assert conn.execute("SELECT rolled_back FROM category_migration_audit").fetchone()[0] == 0


def test_outer_transaction_owns_commit_and_rollback():
    conn = database()
    conn.execute("BEGIN")
    apply(conn)
    assert conn.in_transaction
    conn.rollback()
    assert conn.execute("SELECT track FROM title_triage WHERE posting_id=3").fetchone()[0] == "primary"
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='category_migration_audit'").fetchone() is None


def test_mapping_requires_complete_policy_and_distinct_targets():
    with pytest.raises(ValueError, match="mapping"):
        plan({}, {"primary": "clerical"})
    with pytest.raises(ValueError):
        plan({}, {**MAPPING, "primary": "secondary"})


def test_bad_json_and_unknown_triage_fail_without_partial_writes():
    for raw, triage in [('{', 'primary'), ('{}', 'mystery')]:
        conn = database()
        conn.execute("UPDATE pipeline_state SET data_json=? WHERE posting_id=2", (raw,))
        conn.execute("UPDATE title_triage SET track=? WHERE posting_id=3", (triage,))
        before = conn.execute("SELECT * FROM pipeline_state").fetchall()
        with pytest.raises(ValueError):
            apply(conn)
        assert conn.execute("SELECT * FROM pipeline_state").fetchall() == before
        assert conn.execute("SELECT track FROM title_triage WHERE posting_id=3").fetchone()[0] == triage


def test_unknown_triage_version_aborts():
    conn = database()
    conn.execute("INSERT INTO title_triage_versions VALUES (3, 'another-version')")
    with pytest.raises(ValueError, match="snapshot"):
        apply(conn)
    assert conn.execute("SELECT track FROM title_triage WHERE posting_id=3").fetchone()[0] == "primary"
