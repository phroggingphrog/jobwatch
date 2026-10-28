import types
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from conftest import make_config
from jobwatch import collectors as registry
from jobwatch import db as dbm
from jobwatch import pipeline
from jobwatch.digest import gather, render
from jobwatch.models import Posting

UTC = timezone.utc
NOON = datetime(2026, 10, 6, 12, 0, tzinfo=ZoneInfo("Australia/Melbourne")).astimezone(UTC)
NIGHT = datetime(2026, 10, 6, 23, 0, tzinfo=ZoneInfo("Australia/Melbourne")).astimezone(UTC)
MORNING = datetime(2026, 10, 7, 7, 5, tzinfo=ZoneInfo("Australia/Melbourne")).astimezone(UTC)


def fresh(hours=1):
    return (datetime.now(UTC) - timedelta(hours=hours)).isoformat(timespec="seconds")


def postings():
    return [
        Posting(source="fake", source_id="1", url="https://x.com/1", title="Payroll Officer", company="Acme",
                location="Melbourne VIC", posted_at=fresh(), posted_at_source="provider", origin="Acme"),
        Posting(source="fake", source_id="2", url="https://x.com/2", title="Senior Payroll Manager",
                location="Melbourne VIC", posted_at=fresh(), posted_at_source="provider", origin="Acme"),
        Posting(source="fake", source_id="3", url="https://x.com/3", title="Receptionist", company="Old Co",
                location="Melbourne VIC", posted_at=fresh(24 * 10), posted_at_source="provider", origin="Old"),
    ]


@pytest.fixture
def fake(monkeypatch):
    state = {"postings": postings(), "fail": False}

    def collect(cfg, since=None):
        if state["fail"]:
            raise RuntimeError("boom")
        cfg.count_raw(len(state["postings"]))
        cfg.origins.add("fake:Acme")
        cfg.reddit_posts.append({"id": "t3_x", "subreddit": "melbourne", "stream": "chatter", "title": "callbacks?",
                                 "url": "https://reddit.com/x", "summary": "", "themes": ["callbacks_ghosting"],
                                 "score": None, "comments": None, "published_at": fresh()})
        return [Posting(**{**p.to_dict()}) for p in state["postings"]]

    module = types.SimpleNamespace(NAME="fake", collect=collect)
    real_get = registry.get
    monkeypatch.setattr(registry, "get", lambda name: module if name == "fake" else real_get(name))
    monkeypatch.setattr(registry, "COLLECTORS", registry.COLLECTORS + ["fake"])
    return state


def cfg(tmp_path):
    return make_config(settings={"tiers": {"fast": ["fake"], "slow": []}}, tmp_path=tmp_path)


def test_run_alerts_once_then_dedupes(tmp_path, fake):
    config = cfg(tmp_path)
    s1 = pipeline.run(config, "fast", dry_run=True, printer=lambda *_: None, now=NOON)
    c = s1["collectors"][0]
    assert (c["fetched"], c["au_kept"], c["new"], c["matched"], c["queued"]) == (3, 3, 3, 2, 1)
    assert c["rejected"] == {"seniority": 1} and c["status"] == "ok"
    assert s1["alerts"] == {"would_publish": 1}
    s2 = pipeline.run(config, "fast", dry_run=True, printer=lambda *_: None, now=NOON)
    assert s2["collectors"][0]["new"] == 0 and s2["alerts"] == {"would_publish": 1}   # a dry run consumes nothing
    conn = dbm.connect(config.db_path)
    statuses = dict(conn.execute("SELECT status, COUNT(*) FROM alerts GROUP BY status").fetchall())
    assert statuses == {"queued": 1, "stale": 1}
    assert conn.execute("SELECT COUNT(*) FROM reddit_posts").fetchone()[0] == 1


def test_run_publishes_fresh_matches_to_the_board(tmp_path, fake):
    """No push channel: a real run marks fresh matches 'board'; old ones stay 'stale'; nothing is sent."""
    config = cfg(tmp_path)
    s = pipeline.run(config, "fast", printer=lambda *_: None, now=NOON)
    assert s["alerts"] == {"board": 1}
    assert pipeline.run(config, "fast", printer=lambda *_: None, now=NOON)["alerts"] == {"board": 0}
    conn = dbm.connect(config.db_path)
    assert dict(conn.execute("SELECT status, COUNT(*) FROM alerts GROUP BY status").fetchall()) == \
        {"board": 1, "stale": 1}
    assert conn.execute("SELECT COUNT(*) FROM alerts WHERE message_id IS NOT NULL").fetchone()[0] == 0


def test_dry_run_never_consumes_rows_a_live_run_publishes(tmp_path, fake):
    config = cfg(tmp_path)
    pipeline.run(config, "fast", dry_run=True, printer=lambda *_: None, now=NOON)
    conn = dbm.connect(config.db_path)
    conn.execute("INSERT INTO alerts(match_id, status, created_at) SELECT id, 'held', 't' FROM matches "
                 "WHERE id NOT IN (SELECT match_id FROM alerts)")        # a legacy held row, if any
    conn.commit()
    assert pipeline.publish(conn, dry_run=True)["would_publish"] >= 1
    assert pipeline.publish(conn)["board"] >= 1
    assert pipeline.publish(dbm.connect(config.db_path))["board"] == 0   # a second publisher finds nothing


def test_observed_dates_seed_first_then_alert(tmp_path, fake):
    config = cfg(tmp_path)
    fake["postings"] = [Posting(source="fake", source_id="9", url="https://x.com/9", title="Bookkeeper",
                                location="Melbourne VIC", origin="Acme")]
    s = pipeline.run(config, "fast", dry_run=True, printer=lambda *_: None, now=NOON)
    assert s["collectors"][0]["matched"] == 1 and s["collectors"][0]["queued"] == 0   # first read seeds
    fake["postings"] = [Posting(source="fake", source_id="10", url="https://x.com/10", title="Bookkeeper",
                                company="Other", location="Geelong VIC", origin="Acme")]
    s = pipeline.run(config, "fast", dry_run=True, printer=lambda *_: None, now=NOON)
    assert s["collectors"][0]["queued"] == 1


def test_health_counts_consecutive_failures_and_recovers(tmp_path, fake):
    """No push: failures are only counted (shown by `jobwatch health` and the Sources page)."""
    config = cfg(tmp_path)
    fake["fail"] = True
    for i in range(4):
        s = pipeline.run(config, "fast", dry_run=True, printer=lambda *_: None, now=NOON)
        assert s["collectors"][0]["status"] == "error"
    conn = dbm.connect(config.db_path)
    assert conn.execute("SELECT consecutive_failures FROM source_health").fetchone()[0] == 4
    fake["fail"] = False
    pipeline.run(config, "fast", dry_run=True, printer=lambda *_: None, now=NOON)
    row = conn.execute("SELECT consecutive_failures, last_status FROM source_health").fetchone()
    assert tuple(row) == (0, "ok")


def test_only_and_unknown_collector(tmp_path):
    config = cfg(tmp_path)
    with pytest.raises(KeyError):
        pipeline.tier_collectors(config, "fast", "nope")
    assert pipeline.tier_collectors(make_config(), "all", None)[-1] == "jsonld_pages"


def test_skipped_when_nothing_configured(tmp_path):
    config = make_config(tmp_path=tmp_path)
    s = pipeline.run(config, "fast", only="ats_lever", dry_run=True, printer=lambda *_: None, now=NOON)
    assert s["collectors"][0]["status"] == "skipped" and s["requests"] == 0


def test_digest(tmp_path, fake):
    config = cfg(tmp_path)
    pipeline.run(config, "fast", dry_run=True, printer=lambda *_: None, now=NOON)
    conn = dbm.connect(config.db_path)
    data = gather(conn)
    assert data["chatter_total"] == 1 and data["themes"] == [("callbacks_ghosting", 1)]
    assert ("payroll_clerk", 1) in data["matches_by_arm"]
    plain, rich = render(data)
    assert "Themes: callbacks_ghosting 1" in plain and "payroll_clerk 1" in plain
    from jobwatch.digest import run_digest
    out = []
    assert run_digest(config, dry_run=True, printer=out.append)["printed"] and "weekly digest" in out[0]
    assert "Payroll" not in out[0] and "Themes: callbacks_ghosting 1" in out[0]
