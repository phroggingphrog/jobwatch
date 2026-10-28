"""Legacy reader kind compatibility, using scratch databases only."""
import json

import pytest

from jobwatch import db as dbm
from jobwatch.web import queries as q
from tests.web.test_ai import make_config, make_client, seed, review, titles, staged


@pytest.mark.parametrize("stage", [None, "scored", "archived"])
def test_pipeline_precedence_over_legacy_kind(tmp_path, monkeypatch, stage):
    config = make_config(tmp_path, monkeypatch)
    conn = dbm.connect(config.db_path)
    pid = seed(conn, 1, "Synthetic hidden role")
    review(conn, pid, verdict="hide", hide_reason="not_target",
           model_json='{"not_target_kind":"sales"}')
    staged(conn, pid, stage or "ingested", reason="not_target",
           sort={"not_target_kind": "reception"})
    assert q.load_rows(conn, "all")[0]["ai"]["hide_reason"] == (
        "reception" if stage == "archived" else "sales")
    conn.close()


@pytest.mark.parametrize("kind", sorted(q.NOT_TARGET_KEYS))
def test_legacy_model_kind_reaches_board_and_filter(tmp_path, monkeypatch, kind):
    config = make_config(tmp_path, monkeypatch)
    conn = dbm.connect(config.db_path)
    from pipeline import store
    store.ensure(conn)
    pid = seed(conn, 1, "Legacy hidden role")
    review(conn, pid, verdict="hide", hide_reason="not_target",
           report_json=json.dumps({"wanted": "not_wanted"}),
           model_json=json.dumps({"not_target_kind": kind}))
    rows = q.load_rows(conn, "all")
    assert rows[0]["ai"]["hide_reason"] == kind
    assert not any(k.startswith("ai_") and k != "ai_state" for k in rows[0])
    conn.close()
    client = make_client(config, tmp_path)
    response = client.get(f"/?ai=hide&why={kind}&scope=all",
                          headers={"HX-Request": "true", "HX-Target": "results"})
    assert response.status_code == 200
    assert titles(response.text) == ["Legacy hidden role"]
    assert "Not a target role (not sorted yet)" not in response.text


@pytest.mark.parametrize("raw", [None, "broken", "[]", "null", "1", '{}',
                                     '{"not_target_kind":"too_senior"}',
                                     '{"not_target_kind":"unknown"}',
                                     '{"not_target_kind":[]}', '{"not_target_kind":{}}'])
def test_invalid_legacy_kind_stays_truthfully_unsorted(raw):
    ai = q.ai_from_row({"ai_pid": 1, "ai_verdict": "hide", "ai_hide_reason": "not_target",
                        "ai_report": '{}', "ai_model_json": raw})
    assert ai["hide_reason"] == "not_target"


@pytest.mark.parametrize("reason", ["not_target", "too_senior", "low_fit"])
def test_valid_report_and_existing_hide_reason_take_precedence(reason):
    ai = q.ai_from_row({"ai_pid": 1, "ai_verdict": "hide", "ai_hide_reason": reason,
                        "ai_report": '{"not_target_kind":"sales"}',
                        "ai_model_json": '{"not_target_kind":"reception"}'})
    assert ai["hide_reason"] == ("sales" if reason == "not_target" else reason)


@pytest.mark.parametrize("report", [None, 'broken', '[]', '{"not_target_kind":[]}',
                                     '{"not_target_kind":{}}', '{"not_target_kind":"unknown"}'])
def test_missing_or_invalid_report_kind_uses_valid_legacy_kind(report):
    ai = q.ai_from_row({"ai_pid": 1, "ai_verdict": "hide", "ai_hide_reason": "not_target",
                        "ai_report": report, "ai_model_json": '{"not_target_kind":"sales"}'})
    assert ai["hide_reason"] == "sales"
