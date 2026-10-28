"""Sorting deadlines, including retries and permission-key fallback; no network."""
import json
import sqlite3

import pytest

from jobwatch.llm import LLM
from pipeline.nodes import sort


@pytest.fixture
def clock(monkeypatch):
    import time
    now = [779.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    return now


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE postings(id INTEGER PRIMARY KEY, title TEXT, company TEXT);
        CREATE TABLE ad_reviews(posting_id INTEGER, model_json TEXT);
        CREATE TABLE pipeline_state(posting_id INTEGER PRIMARY KEY, stage TEXT, reason TEXT,
                                    data_json TEXT, updated_at TEXT);
        CREATE TABLE pipeline_events(node TEXT);
        CREATE TABLE pipeline_dlq(posting_id INTEGER);
        INSERT INTO postings VALUES(1, 'Cafe assistant', 'Example');
        INSERT INTO pipeline_state VALUES(1, 'archived', 'not_target', '{}', 'before');
    """)
    yield c
    c.close()


def run(conn, transport, budget):
    return sort.run(conn, LLM(transport=transport, keys=["test-one", "test-two"]),
                    "claude/sonnet", max_seconds=budget)


def unchanged(conn):
    row = conn.execute("SELECT stage, reason, data_json FROM pipeline_state").fetchone()
    assert tuple(row) == ("archived", "not_target", "{}")
    assert conn.execute("SELECT COUNT(*) FROM pipeline_events").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM pipeline_dlq").fetchone()[0] == 0


def test_nearly_expired_timeout_cannot_retry(conn, clock):
    seen = []

    def transport(url, headers, body, timeout):
        seen.append(timeout)
        clock[0] += timeout
        raise TimeoutError("fake timeout")

    stats = run(conn, transport, 1)
    assert seen == [1]
    assert clock[0] == 780
    assert stats["time_limit"] is True
    unchanged(conn)


@pytest.mark.parametrize("budget", [0, -1])
def test_exhausted_budget_never_calls(conn, clock, budget):
    def transport(*args):
        pytest.fail("expired budget must not call a model")

    assert run(conn, transport, budget)["time_limit"] is True
    unchanged(conn)


def test_retry_and_key_fallback_share_remaining_budget(conn, clock):
    seen = []

    def transport(url, headers, body, timeout):
        seen.append(timeout)
        clock[0] += 0.25
        if len(seen) == 1:
            return 403, {"error": {"code": "permission_denied"}}
        text = "bad json" if len(seen) == 2 else json.dumps({"results": [{"id": 1, "kind": "hospitality"}]})
        return 200, {"choices": [{"message": {"content": text}}]}

    stats = run(conn, transport, 1)
    assert seen == [1, 0.75, 0.5]
    assert stats["from_model"] == 1
    assert clock[0] == 779.75
    row = conn.execute("SELECT stage, reason, data_json FROM pipeline_state").fetchone()
    assert tuple(row)[:2] == ("archived", "not_target")
    assert json.loads(row["data_json"])["sort"]["source"] == "model"
    assert conn.execute("SELECT COUNT(*) FROM pipeline_events").fetchone()[0] == 0


def test_key_refusal_at_deadline_does_not_try_next_key(conn, clock):
    seen = []

    def transport(url, headers, body, timeout):
        seen.append(timeout)
        clock[0] += timeout
        return 403, {"error": {"code": "permission_denied"}}

    assert run(conn, transport, 1)["time_limit"] is True
    assert seen == [1]
    unchanged(conn)


def test_success_at_deadline_is_not_applied(conn, clock):
    def transport(url, headers, body, timeout):
        clock[0] += timeout
        return 200, {"choices": [{"message": {"content": '{"results": [{"id": 1, "kind": "hospitality"}]}'}}]}

    assert run(conn, transport, 1)["time_limit"] is True
    unchanged(conn)
