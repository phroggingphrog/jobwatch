import sqlite3
from datetime import UTC, datetime

import pytest

from pipeline import discovery_vocabulary as v


def item(term, version=1, source="board"):
    return {"term": term, "source": source, "url": "https://example.org/page", "retrieved_at": datetime.now(UTC), "goal_version": version}


def test_version_isolation_overrides_and_rollback():
    conn = sqlite3.connect(":memory:")
    first = v.set_goal(conn, "a", "first goal")
    v.activate(conn, "a", first, [item("alpha")])
    v.override(conn, "a", "board", "alpha", "exclude")
    v.override(conn, "a", "board", "manual", "include")
    v.set_goal(conn, "b", "other goal")
    v.activate(conn, "b", 1, [item("beta")])
    second = v.set_goal(conn, "a", "new goal")
    assert v.queries(conn, "a", "board") == ["manual"]
    with pytest.raises(ValueError, match="stale"):
        v.activate(conn, "a", first, [item("stale")])
    v.activate(conn, "a", second, [item("new", 2)])
    assert v.queries(conn, "a", "board") == ["manual", "new"]
    assert v.queries(conn, "b", "board") == ["beta"]
    v.rollback(conn, "a", 1)
    assert v.queries(conn, "a", "board") == ["manual"]


def test_research_cannot_add_restrictions():
    conn = sqlite3.connect(":memory:")
    v.set_goal(conn, "a", "goal")
    with pytest.raises(ValueError):
        v.activate(conn, "a", 1, [{**item("x"), "hours_limit": 20}])
    assert v.queries(conn, "a", "board") == []
