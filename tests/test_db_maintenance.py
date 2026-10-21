"""prune keeps referenced postings and never aborts a run; migrate is atomic and serialised."""
import sqlite3
import threading

import pytest

from jobwatch import db as dbm
from jobwatch.models import now_utc

OLD = "2020-01-01T00:00:00+00:00"


def _posting(conn, n, last_seen=OLD):
    cur = conn.execute(
        "INSERT INTO postings(source, source_id, url, url_hash, title, company, location, first_seen_at, "
        "last_seen_at, dedupe_key) VALUES('t', ?, ?, ?, 'Payroll Officer', 'Acme', 'Melbourne', ?, ?, ?)",
        (str(n), f"https://example.com/{n}", f"h{n}", last_seen, last_seen, f"k{n}"))
    return cur.lastrowid


def _application(conn, pid):
    now = dbm.ts()
    conn.execute("INSERT INTO applications(posting_id, status, created_at, updated_at) VALUES(?, 'skipped', ?, ?)",
                 (pid, now, now))


def _ids(conn):
    return {r[0] for r in conn.execute("SELECT id FROM postings")}


def test_prune_keeps_postings_with_applications_or_requirements(tmp_path):
    conn = dbm.connect(tmp_path / "p.db")
    with_app, with_req, plain = (_posting(conn, i) for i in (1, 2, 3))
    _application(conn, with_app)
    conn.execute("INSERT INTO requirements(posting_id, text, tier) VALUES(?, 'x', 'structural')", (with_req,))
    conn.commit()
    assert dbm.prune(conn, 90) == 1            # the original code raised IntegrityError here
    assert _ids(conn) == {with_app, with_req}
    assert plain not in _ids(conn)


def test_prune_never_raises_on_database_errors(tmp_path):
    conn = dbm.connect(tmp_path / "p.db")
    pid = _posting(conn, 1)
    # a restricting foreign key that prune does not know about must not abort the run
    conn.execute("CREATE TABLE extra_ref(posting_id INTEGER REFERENCES postings(id))")
    conn.execute("INSERT INTO extra_ref VALUES(?)", (pid,))
    conn.commit()
    assert dbm.prune(conn, 90) == 0
    assert pid in _ids(conn)
    assert not conn.in_transaction


def test_prune_keeps_recent_and_matched(tmp_path):
    conn = dbm.connect(tmp_path / "p.db")
    recent = _posting(conn, 1, dbm.ts(now_utc()))
    matched = _posting(conn, 2)
    conn.execute("INSERT INTO matches(posting_id, arm, matched_at) VALUES(?, 'payroll', ?)", (matched, OLD))
    old_other = _posting(conn, 3)
    conn.commit()
    assert dbm.prune(conn, 90) == 1
    assert _ids(conn) == {recent, matched}
    assert old_other not in _ids(conn)


# -- migrate ------------------------------------------------------------------------------
def _raw_at(path, version):
    """A DB migrated only up to `version`."""
    conn = sqlite3.connect(str(path), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    real = dbm.MIGRATIONS
    try:
        dbm.MIGRATIONS = real[:version]
        dbm.migrate(conn)
    finally:
        dbm.MIGRATIONS = real
    return conn


def test_migrate_crash_mid_migration_leaves_previous_version(tmp_path, monkeypatch):
    path = tmp_path / "m.db"
    _raw_at(path, 7).close()
    conn = sqlite3.connect(str(path), timeout=5)
    real = conn.execute
    calls = {"alter": 0}

    class Crashing:
        """Stand-in for a kill after two of the four v8 ALTER statements."""
        def __init__(self, c):
            self.c = c

        def __getattr__(self, name):
            return getattr(self.c, name)

        def execute(self, sql, *a):
            if sql.lstrip().upper().startswith("ALTER"):
                calls["alter"] += 1
                if calls["alter"] == 3:
                    raise KeyboardInterrupt
            return self.c.execute(sql, *a)

    with pytest.raises(KeyboardInterrupt):
        dbm.migrate(Crashing(conn))
    conn.close()
    check = sqlite3.connect(str(path))
    assert check.execute("PRAGMA user_version").fetchone()[0] == 7
    cols = {r[1] for r in check.execute("PRAGMA table_info(ad_reviews)")}
    assert "score" not in cols                       # the two finished ALTERs were rolled back
    check.close()
    again = dbm.connect(path)                        # the next start simply succeeds
    assert again.execute("PRAGMA user_version").fetchone()[0] == len(dbm.MIGRATIONS)
    assert "report_json" in {r[1] for r in again.execute("PRAGMA table_info(ad_reviews)")}


def test_migrate_two_starters_do_not_both_run_it(tmp_path):
    path = tmp_path / "m.db"
    _raw_at(path, 7).close()
    barrier = threading.Barrier(2)
    errors, versions = [], []

    def start():
        try:
            conn = sqlite3.connect(str(path), timeout=30)
            conn.execute("PRAGMA busy_timeout=30000")
            barrier.wait()
            versions.append(dbm.migrate(conn))
            conn.close()
        except Exception as exc:                      # noqa: BLE001
            errors.append(repr(exc))

    threads = [threading.Thread(target=start) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []                              # was: OperationalError duplicate column name
    assert versions == [len(dbm.MIGRATIONS)] * 2


def test_migrate_waits_for_a_lock_held_by_another_starter(tmp_path):
    path = tmp_path / "m.db"
    _raw_at(path, 7).close()
    holder = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    other = sqlite3.connect(str(path), timeout=0.2)
    with pytest.raises(sqlite3.OperationalError):    # cannot start while the other one holds the write lock
        dbm.migrate(other)
    holder.execute("ROLLBACK")
    assert dbm.migrate(other) == len(dbm.MIGRATIONS)


def test_migrate_statement_splitter_handles_comments_and_triggers():
    script = """
    -- a comment; with a semicolon
    CREATE TABLE a(x);
    CREATE TRIGGER t AFTER INSERT ON a BEGIN UPDATE a SET x=1; END;
    ALTER TABLE a ADD COLUMN y;
    """
    parts = [p.strip() for p in dbm._statements(script)]
    assert len(parts) == 3 and parts[1].endswith("END;")
