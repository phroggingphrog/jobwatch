"""Promotion: top SHORTLISTED by score go to the agentic batch, within the run and day limits."""
from jobwatch import db as dbm
from jobwatch.dedupe import ingest as ingest_posting
from jobwatch.models import Posting
from pipeline import screened, store
from pipeline.schemas import Stage
from conftest import make_config


def shortlist(conn, title, score):
    pid, _ = ingest_posting(conn, Posting(source="ats_pageup", source_id=title, url=f"https://example.com/{title}",
                                          title=title, company="Acme", location="Melbourne VIC", description="x"))
    store.admit(conn, pid, f"h{pid}", {"evaluate": {"overall": score}}, Stage.SHORTLISTED)
    conn.commit()
    return pid


def test_top_three_by_score_are_promoted(tmp_path, monkeypatch):
    config = make_config(tmp_path=tmp_path)
    conn = dbm.connect(config.db_path)
    store.ensure(conn)
    ids = [shortlist(conn, f"job{i}", s) for i, s in enumerate([4.5, 4.2, 4.0, 3.5, 2.9])]
    calls = []

    def stub(snapshot_ids, cfg, c, **kw):
        calls.append(list(snapshot_ids))
        return {"processed": len(snapshot_ids)}
    monkeypatch.setattr("pipeline.agentic.service.agentic_batch_run", stub)
    out = screened.promote(conn, config, max_seconds=60, deadline=None)
    assert calls == [ids[:3]] and out["promoted"] == 3
    assert conn.execute("SELECT COUNT(*) FROM pipeline_events WHERE node='promote'").fetchone()[0] == 3
    assert screened.screened_settings(config) == {"promote_per_run": 3, "promote_per_day": 10, "min_score": 3.0}


def test_promotion_prioritizes_category_then_score_without_minimum(tmp_path, monkeypatch):
    categories = [
        {"id": "first", "label": "First", "priority": 0, "phrases": ["first"],
         "action": "admit", "promote": True, "hours": "standard"},
        {"id": "second", "label": "Second", "priority": 1, "phrases": ["second"],
         "action": "admit", "promote": True, "hours": "standard"},
        {"id": "blocked", "label": "Blocked", "priority": 2, "phrases": ["blocked"],
         "action": "admit", "promote": False, "hours": "standard"},
    ]
    config = make_config(tmp_path=tmp_path, settings={"pipeline": {"screened": {
        "promote_per_run": 3, "min_score": 3.0, "category_snapshot": {"categories": categories}}}})
    conn = dbm.connect(config.db_path)
    store.ensure(conn)
    low = shortlist(conn, "low", 2.9)
    high = shortlist(conn, "high", 4.5)
    second = shortlist(conn, "second", 5.0)
    blocked = shortlist(conn, "blocked", 5.0)
    for pid, track in [(low, "first"), (high, "first"), (second, "second"), (blocked, "blocked")]:
        conn.execute("UPDATE pipeline_state SET data_json=json_set(data_json, '$.track', ?) WHERE posting_id=?",
                     (track, pid))
    conn.commit()
    calls = []
    monkeypatch.setattr("pipeline.agentic.service.agentic_batch_run",
                        lambda ids, cfg, c, **kw: calls.append(list(ids)) or {"processed": len(ids)})
    result = screened.promote(conn, config, max_seconds=60, deadline=None)
    assert calls == [[high, low, second]]
    assert result["promoted"] == 3
    events = conn.execute("SELECT posting_id FROM pipeline_events WHERE node='promote' ORDER BY id").fetchall()
    assert [event[0] for event in events] == [high, low, second]
