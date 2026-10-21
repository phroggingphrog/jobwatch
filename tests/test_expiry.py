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


def _relist(conn):
    return ingest(conn, Posting(source="s", source_id="1", url="https://x.com/1", title="Payroll Officer",
                                company="Acme", location="Melbourne VIC"))


def _due(conn, now):
    rows = []
    expiry.sweep(conn, now=now, observe=lambda posting, deadline: rows.append(posting["id"]) or SimpleNamespace(
        status="closed", expires_at=None))
    return rows


def test_a_relisted_closed_ad_stays_closed_until_a_live_check_finds_it_open(tmp_path):
    from datetime import timedelta
    conn = dbm.connect(tmp_path / "d.db")
    pid = _posting(conn)
    now = datetime.now(timezone.utc)
    expiry.record(conn, pid, SimpleNamespace(status="closed", expires_at=None), now - timedelta(days=4))
    again, new = _relist(conn)                         # an aggregator still lists the dead ad
    assert (again, new) == (pid, False) and _closed_at(conn, pid)       # not back on the board on its say-so
    assert _due(conn, now) == [pid]                    # but a live check is due (closed 4 days ago, seen since)
    assert _closed_at(conn, pid) and _due(conn, now) == []   # confirmed closed: no re-check until it is listed again
    _relist(conn)
    assert _due(conn, now) == []                       # listed again, but checked just now: waits 3 days
    assert _due(conn, now + timedelta(days=3, minutes=1)) == [pid]
    expiry.record(conn, pid, SimpleNamespace(status="active", expires_at=None), now)
    assert _closed_at(conn, pid) is None               # only a live check that finds it open reopens it
