from jobwatch import db as dbm
from jobwatch.dedupe import city_of, dedupe_key, ingest
from jobwatch.models import Posting


def P(source, sid, url, title="Payroll Officer", company="Acme Pty Ltd", location="Melbourne VIC 3000"):
    return Posting(source=source, source_id=sid, url=url, title=title, company=company, location=location)


def test_url_then_key_dedupe(tmp_path):
    conn = dbm.connect(tmp_path / "d.db")
    pid, new = ingest(conn, P("seek", "1", "https://www.seek.com.au/job/1?ref=x"))
    assert new
    # same URL modulo tracking params -> same posting
    pid2, new2 = ingest(conn, P("rss", "z", "https://www.seek.com.au/job/1?utm_source=feed"))
    assert (pid2, new2) == (pid, False)
    # different URL, same company/title/city -> same posting
    pid3, new3 = ingest(conn, P("jobspy_src", "li:9", "https://www.linkedin.com/jobs/view/9",
                                company="ACME", location="Melbourne, Victoria, Australia"))
    assert (pid3, new3) == (pid, False)
    # different city -> new posting
    _, new4 = ingest(conn, P("jobspy_src", "li:10", "https://www.linkedin.com/jobs/view/10", location="Geelong VIC"))
    assert new4
    sightings = conn.execute("SELECT source, times_seen FROM sightings WHERE posting_id=? ORDER BY source",
                             (pid,)).fetchall()
    assert [tuple(r) for r in sightings] == [("jobspy_src", 1), ("rss", 1), ("seek", 1)]
    # same source again bumps times_seen; first source still owns the row
    ingest(conn, P("seek", "1", "https://www.seek.com.au/job/1"))
    assert conn.execute("SELECT times_seen FROM sightings WHERE source='seek'").fetchone()[0] == 2
    assert conn.execute("SELECT source FROM postings WHERE id=?", (pid,)).fetchone()[0] == "seek"


def test_key_window(tmp_path):
    conn = dbm.connect(tmp_path / "d.db")
    pid, _ = ingest(conn, P("a", "1", "https://a.com/1"))
    conn.execute("UPDATE postings SET first_seen_at='2026-01-01T00:00:00+00:00' WHERE id=?", (pid,))
    _, new = ingest(conn, P("b", "2", "https://b.com/2"))
    assert new                                       # older than 30 days: treated as a new posting


def test_key_normalisation():
    assert city_of("Melbourne VIC 3000") == city_of("Melbourne, Victoria, Australia") == "melbourne"
    a = dedupe_key(P("a", "1", "https://a.com", title="Payroll Officer - URGENT", company="The Acme Group"))
    b = dedupe_key(P("b", "1", "https://b.com", title="payroll officer", company="Acme"))
    assert a == b


def test_migrations_idempotent_and_wal(tmp_path):
    conn = dbm.connect(tmp_path / "m.db")
    assert dbm.migrate(conn) == len(dbm.MIGRATIONS)
    assert dbm.migrate(conn) == len(dbm.MIGRATIONS)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"postings", "sightings", "matches", "alerts", "source_health", "reddit_posts", "runs", "state"} <= tables
