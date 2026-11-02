"""Versioned discovery suggestions, separate from personal restrictions.

The caller must bind each connection to the authenticated person's database.
Research and activation are separate so a failed refresh cannot replace a version.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Suggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    term: str = Field(min_length=1, max_length=160)
    source: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=4096)
    retrieved_at: datetime
    goal_version: int = Field(gt=0, strict=True)

    @field_validator("term", "source")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("value must not be blank")
        return value.strip()

    @field_validator("url")
    @classmethod
    def public_https(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("source URL must be HTTPS")
        return value

    @field_validator("retrieved_at")
    @classmethod
    def aware_time(cls, value):
        if value.tzinfo is None:
            raise ValueError("retrieval time must include timezone")
        return value


def ensure(conn):
    schema = """
    CREATE TABLE IF NOT EXISTS discovery_goals (
        person TEXT PRIMARY KEY, goal TEXT NOT NULL, goal_version INTEGER NOT NULL,
        active_version INTEGER, error TEXT
    );
    CREATE TABLE IF NOT EXISTS discovery_vocabulary_versions (
        person TEXT NOT NULL, version INTEGER NOT NULL, goal_version INTEGER NOT NULL,
        suggestions TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(person, version)
    );
    CREATE TABLE IF NOT EXISTS discovery_vocabulary_overrides (
        person TEXT NOT NULL, source TEXT NOT NULL, term TEXT NOT NULL,
        decision TEXT NOT NULL CHECK(decision IN ('include', 'exclude')),
        PRIMARY KEY(person, source, term)
    );
    """
    for statement in schema.split(';'):
        if statement.strip(): conn.execute(statement)


def status(conn, person):
    ensure(conn)
    row = conn.execute("SELECT goal_version, active_version, error FROM discovery_goals WHERE person=?", (person,)).fetchone()
    if row is None: return dict(goal_version=None, active_version=None, active_goal_version=None, error=None)
    active = conn.execute("SELECT goal_version FROM discovery_vocabulary_versions WHERE person=? AND version=?", (person, row[1])).fetchone()
    return dict(goal_version=row[0], active_version=row[1], active_goal_version=active[0] if active else None, error=row[2])


def record_error(conn, person, goal_version, error):
    ensure(conn)
    conn.execute("UPDATE discovery_goals SET error=? WHERE person=? AND goal_version=?", (error, person, goal_version))


def set_goal(conn, person, goal):
    if not isinstance(goal, str) or not goal.strip() or len(goal) > 4096:
        raise ValueError("invalid goal")
    ensure(conn)
    row = conn.execute("SELECT goal, goal_version FROM discovery_goals WHERE person=?", (person,)).fetchone()
    if row and row[0] == goal.strip():
        return row[1]
    version = row[1] + 1 if row else 1
    conn.execute("INSERT INTO discovery_goals(person,goal,goal_version,error) VALUES(?,?,?,NULL) "
                 "ON CONFLICT(person) DO UPDATE SET goal=excluded.goal, goal_version=excluded.goal_version, error=NULL",
                 (person, goal.strip(), version))
    conn.commit()
    return version


def activate(conn, person, goal_version, suggestions):
    ensure(conn)
    row = conn.execute("SELECT goal_version FROM discovery_goals WHERE person=?", (person,)).fetchone()
    if row is None or row[0] != goal_version:
        raise ValueError("stale goal version")
    parsed = [Suggestion.model_validate(suggestion) for suggestion in suggestions]
    if not parsed or any(item.goal_version != goal_version for item in parsed):
        raise ValueError("research must contain sourced suggestions for the current goal")
    version = conn.execute("SELECT COALESCE(MAX(version),0)+1 FROM discovery_vocabulary_versions WHERE person=?", (person,)).fetchone()[0]
    payload = json.dumps([item.model_dump(mode="json") for item in parsed])
    with conn:
        conn.execute("INSERT INTO discovery_vocabulary_versions VALUES(?,?,?,?,?)",
                     (person, version, goal_version, payload, datetime.now(UTC).isoformat()))
        conn.execute("UPDATE discovery_goals SET active_version=?, error=NULL WHERE person=? AND goal_version=?",
                     (version, person, goal_version))
    return version


def rollback(conn, person, version):
    ensure(conn)
    row = conn.execute("SELECT 1 FROM discovery_vocabulary_versions WHERE person=? AND version=?", (person, version)).fetchone()
    if not row:
        raise ValueError("unknown vocabulary version")
    with conn:
        conn.execute("UPDATE discovery_goals SET active_version=? WHERE person=?", (version, person))


def override(conn, person, source, term, decision):
    if decision not in ("include", "exclude") or not source.strip() or not term.strip():
        raise ValueError("invalid vocabulary correction")
    ensure(conn)
    with conn:
        conn.execute("INSERT OR REPLACE INTO discovery_vocabulary_overrides VALUES(?,?,?,?)", (person, source.strip(), term.strip(), decision))


def queries(conn, person, source):
    ensure(conn)
    row = conn.execute("SELECT v.suggestions FROM discovery_goals g JOIN discovery_vocabulary_versions v "
                       "ON v.person=g.person AND v.version=g.active_version WHERE g.person=?", (person,)).fetchone()
    terms = {item["term"] for item in json.loads(row[0]) if item["source"] == source} if row else set()
    for term, decision in conn.execute("SELECT term,decision FROM discovery_vocabulary_overrides WHERE person=? AND source=?", (person, source)):
        if decision == "include":
            terms.add(term)
        else:
            terms.discard(term)
    return sorted(terms)
