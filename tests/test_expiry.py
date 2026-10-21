from datetime import datetime, timezone
from types import SimpleNamespace

from jobwatch import db as dbm, expiry
from jobwatch.dedupe import ingest
from jobwatch.models import Posting


def _posting(conn):
    pid, _ = ingest(conn, Posting(source="s", source_id="1", url="https://x.com/1", title="Payroll Officer",
                                  company="Acme", location="Melbourne VIC"))
    return pid


def _closed_at(conn, pid):
    return conn.execute("SELECT closed_at FROM postings WHERE id=?", (pid,)).fetchone()[0]


def test_live_check_clears_closed_at(tmp_path):
    conn = dbm.connect(tmp_path / "d.db")
    pid = _posting(conn)
    expiry.record(conn, pid, SimpleNamespace(status="closed", expires_at=None))
    assert _closed_at(conn, pid)
    expiry.record(conn, pid, SimpleNamespace(status="active", expires_at=None))
    assert _closed_at(conn, pid) is None


def test_unreadable_check_keeps_closed_at(tmp_path):
    conn = dbm.connect(tmp_path / "d.db")
    pid = _posting(conn)
    expiry.record(conn, pid, SimpleNamespace(status="closed", expires_at=None))
    expiry.record(conn, pid, SimpleNamespace(status="unknown", expires_at=None))
    assert _closed_at(conn, pid)


def test_a_new_sighting_reopens_a_closed_posting_and_defers_the_recheck(tmp_path):
    conn = dbm.connect(tmp_path / "d.db")
    pid = _posting(conn)
    conn.execute("UPDATE postings SET closed_at='2026-10-01T00:00:00+00:00', expires_at='2026-10-02T00:00:00+00:00' "
                 "WHERE id=?", (pid,))
    again, new = ingest(conn, Posting(source="s", source_id="1", url="https://x.com/1", title="Payroll Officer",
                                      company="Acme", location="Melbourne VIC"))
    assert (again, new) == (pid, False) and _closed_at(conn, pid) is None
    expires = conn.execute("SELECT expires_at FROM postings WHERE id=?", (pid,)).fetchone()[0]
    assert datetime.fromisoformat(expires) > datetime.now(timezone.utc)
