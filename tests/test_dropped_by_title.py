from datetime import UTC, datetime, timedelta

from jobwatch import db as dbm
from jobwatch.dedupe import ingest as ingest_posting
from jobwatch.models import Posting
from jobwatch.web.queries import dropped_by_title
from conftest import make_config


def test_lists_metadata_skips_inside_the_window(tmp_path):
    conn = dbm.connect(make_config(tmp_path=tmp_path).db_path)
    ids = {}
    for name in ("recent", "old", "admitted"):
        ids[name], _ = ingest_posting(conn, Posting(source="ats_pageup", source_id=name, url=f"https://example.com/{name}",
                                                    title=name, company="Acme", location="Melbourne VIC", description="x"))
    def decide(pid, outcome, days):
        at = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")
        conn.execute("INSERT INTO prescreen_decisions(posting_id, at, stage, outcome, reason, rules_hash) VALUES(?,?,?,?,?,?)",
                     (pid_of[pid], at, "metadata", outcome, "title rule", "h"))
    pid_of = {"recent": ids["recent"], "old": ids["old"], "admitted": ids["admitted"]}
    decide("recent", "skip", 1); decide("old", "skip", 20); decide("admitted", "admit", 1)
    conn.commit()
    rows = dropped_by_title(conn, 7)
    assert [r["title"] for r in rows] == ["recent"] and rows[0]["reason"] == "title rule"
    assert {"posting_id", "title", "company", "reason", "decided_at"} <= set(rows[0])
