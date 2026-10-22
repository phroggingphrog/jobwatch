"""Dedup (PLAN D6): canonical-URL hash, then normalised (company, title, city) within 30 days.

The first source seen owns the postings row; every source that sees it gets a sightings row.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import timedelta

from .db import ts
from .models import Posting, fold, now_utc, url_hash

KEY_WINDOW_DAYS = 30
_COMPANY_NOISE = re.compile(
    r"\b(pty|ltd|limited|inc|llc|plc|group|holdings|australia|australian|the|co|corporation|corp)\b")
_TITLE_NOISE = re.compile(r"\b(urgent|immediate start|new|now hiring|hiring|job|role|vacancy)\b")
_CITY_NOISE = re.compile(r"\b(vic|victoria|nsw|qld|wa|sa|tas|act|nt|australia|au|cbd|"
                         r"hybrid|remote|on-?site|all)\b|\d{4}")


def _norm(text: str, noise: re.Pattern) -> str:
    text = fold(text or "")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = noise.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def city_of(location: str) -> str:
    first = (location or "").split(",")[0]
    first = re.split(r"\s[-|(/]\s?|\(", first)[0]
    return _norm(first, _CITY_NOISE)


def dedupe_key(posting: Posting) -> str:
    company = _norm(posting.company, _COMPANY_NOISE)
    title = _norm(posting.title, _TITLE_NOISE)
    return f"{company}|{title}|{city_of(posting.location)}"


def ingest(conn: sqlite3.Connection, posting: Posting, run_id: int | None = None, *, key_merge: bool = True) -> tuple[int, bool]:
    """Store or match a posting. Returns (posting_id, is_new)."""
    now = ts()
    uhash = url_hash(posting.url) if posting.url else url_hash(f"{posting.source}:{posting.source_id}")
    key = dedupe_key(posting)

    row = conn.execute("SELECT id FROM postings WHERE url_hash=?", (uhash,)).fetchone()
    if row is None:
        row = conn.execute("SELECT posting_id AS id FROM sightings WHERE source=? AND source_id=?",
                           (posting.source, posting.source_id)).fetchone()
    if key_merge and row is None and key.split("|")[0] and key.split("|")[1]:
        cutoff = ts(now_utc() - timedelta(days=KEY_WINDOW_DAYS))
        # A source that already has a different id on that posting is listing a distinct requisition.
        row = conn.execute(
            "SELECT id FROM postings WHERE dedupe_key=? AND first_seen_at>=? AND NOT EXISTS ("
            "SELECT 1 FROM sightings s WHERE s.posting_id=postings.id AND s.source=?) ORDER BY id LIMIT 1",
            (key, cutoff, posting.source)).fetchone()

    if row is not None:
        posting_id, is_new = row["id"], False
        # A closed posting stays closed when an aggregator lists it again: the sighting only makes it due for a live
        # re-check (expiry.sweep), and only a check that finds it open reopens it.
        conn.execute("UPDATE postings SET last_seen_at=? WHERE id=?", (now, posting_id))
        primary = conn.execute('SELECT source,source_id,description FROM postings WHERE id=?', (posting_id,)).fetchone()
        if (primary['source'] == posting.source and primary['source_id'] == posting.source_id
                and not primary['description'] and posting.description):
            # Bounded collectors may store metadata before obtaining full detail.
            # Enrich that same source's empty evidence without letting another
            # source replace it, reopening closed jobs or erasing richer text.
            conn.execute('''UPDATE postings SET description=?,raw_json=?,dedupe_key=?,
                location=CASE WHEN ?<>'' THEN ? ELSE location END,
                state=COALESCE(?,state),remote=?,work_type=COALESCE(?,work_type)
                WHERE id=?''', (posting.description, posting.raw_json(), key,
                    posting.location or '', posting.location or '', posting.state,
                    int(posting.remote), posting.work_type, posting_id))
    else:
        cur = conn.execute(
            """INSERT INTO postings(source, source_id, url, url_hash, dedupe_key, title, company,
                   location, state, remote, work_type, salary_text, salary_min, salary_max,
                   salary_unit, posted_at, posted_at_source, description, raw_json, flags_json,
                   origin, first_seen_at, last_seen_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (posting.source, posting.source_id, posting.url, uhash, key, posting.title,
             posting.company, posting.location, posting.state, int(posting.remote),
             posting.work_type, posting.salary_text, posting.salary_min, posting.salary_max,
             posting.salary_unit, posting.posted_at, posting.posted_at_source,
             posting.description, posting.raw_json(), json.dumps(posting.flags),
             posting.origin, now, now))
        posting_id, is_new = cur.lastrowid, True

    conn.execute(
        """INSERT INTO sightings(posting_id, source, source_id, url, first_seen_at, last_seen_at,
               times_seen, last_run_id) VALUES(?,?,?,?,?,?,1,?)
           ON CONFLICT(posting_id, source) DO UPDATE SET last_seen_at=excluded.last_seen_at,
               times_seen=sightings.times_seen+1, last_run_id=excluded.last_run_id""",
        (posting_id, posting.source, posting.source_id, posting.url, now, now, run_id))
    return posting_id, is_new
