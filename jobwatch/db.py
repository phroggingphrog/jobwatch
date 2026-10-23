"""SQLite store (WAL). Migrations are idempotent and tracked with PRAGMA user_version.

They are not all purely additive: v12 backfills postings.expires_at for every row that has none,
so opening an older database through connect() can change data as well as schema.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import timedelta
from pathlib import Path

from .models import now_utc

log = logging.getLogger(__name__)

MIGRATIONS: list[str] = [
    # v1
    """
    CREATE TABLE IF NOT EXISTS postings (
        id INTEGER PRIMARY KEY,
        source TEXT NOT NULL,
        source_id TEXT NOT NULL,
        url TEXT NOT NULL,
        url_hash TEXT NOT NULL UNIQUE,
        dedupe_key TEXT NOT NULL,
        title TEXT NOT NULL,
        company TEXT,
        location TEXT,
        state TEXT,
        remote INTEGER NOT NULL DEFAULT 0,
        work_type TEXT,
        salary_text TEXT,
        salary_min REAL,
        salary_max REAL,
        salary_unit TEXT,
        posted_at TEXT,
        posted_at_source TEXT,
        description TEXT,
        raw_json TEXT,
        flags_json TEXT,
        origin TEXT,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_postings_key ON postings(dedupe_key, first_seen_at);
    CREATE INDEX IF NOT EXISTS ix_postings_src ON postings(source, source_id);
    CREATE TABLE IF NOT EXISTS sightings (
        id INTEGER PRIMARY KEY,
        posting_id INTEGER NOT NULL REFERENCES postings(id) ON DELETE CASCADE,
        source TEXT NOT NULL,
        source_id TEXT,
        url TEXT,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        times_seen INTEGER NOT NULL DEFAULT 1,
        last_run_id INTEGER,
        UNIQUE(posting_id, source)
    );
    CREATE INDEX IF NOT EXISTS ix_sightings_src ON sightings(source, source_id);
    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY,
        posting_id INTEGER NOT NULL UNIQUE REFERENCES postings(id) ON DELETE CASCADE,
        arm TEXT NOT NULL,
        arm_tier TEXT,
        arms_json TEXT,
        rules_json TEXT,
        flags_json TEXT,
        matched_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY,
        match_id INTEGER NOT NULL UNIQUE REFERENCES matches(id) ON DELETE CASCADE,
        status TEXT NOT NULL,          -- queued | held | sent | dry_run | stale | failed
        message_id TEXT,
        error TEXT,
        created_at TEXT NOT NULL,
        sent_at TEXT
    );
    CREATE INDEX IF NOT EXISTS ix_alerts_status ON alerts(status);
    CREATE TABLE IF NOT EXISTS source_health (
        collector TEXT PRIMARY KEY,
        last_run_at TEXT,
        last_ok_at TEXT,
        last_status TEXT,
        last_error TEXT,
        last_count INTEGER,
        last_latency_ms INTEGER,
        consecutive_failures INTEGER NOT NULL DEFAULT 0,
        alerted INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS reddit_posts (
        id TEXT PRIMARY KEY,
        subreddit TEXT,
        stream TEXT NOT NULL,          -- hiring | chatter
        title TEXT,
        url TEXT,
        summary TEXT,
        themes_json TEXT,
        score INTEGER,
        comments INTEGER,
        published_at TEXT,
        seen_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY,
        kind TEXT NOT NULL,            -- run | digest
        tier TEXT,
        dry_run INTEGER NOT NULL DEFAULT 0,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        stats_json TEXT
    );
    CREATE TABLE IF NOT EXISTS state (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """,
    # --- apply layer (BUI-81): data contract = profile/ (user layer, read-only to code) +
    # ledger/*.jsonl (system layer, append-only, canonical) -> these tables are a derived index
    # rebuildable with `jobwatch reindex`.
    """
    CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY,
        posting_id INTEGER NOT NULL UNIQUE REFERENCES postings(id),
        match_id INTEGER REFERENCES matches(id),
        arm TEXT,
        status TEXT NOT NULL DEFAULT 'interested',  -- interested|drafting|drafted|applied|assessment|interview|offer|rejected|withdrawn|skipped
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        applied_at TEXT,
        notes TEXT
    );
    CREATE TABLE IF NOT EXISTS application_events (
        id INTEGER PRIMARY KEY,
        application_id INTEGER NOT NULL REFERENCES applications(id),
        at TEXT NOT NULL,
        kind TEXT NOT NULL,              -- status|draft|outcome_proposed|outcome_decided|command
        from_status TEXT, to_status TEXT,
        actor TEXT NOT NULL,             -- owner|jobwatch
        source TEXT,                     -- web|mail:<message_id>|cli (was matrix:<event_id> until 2026-10-06)
        detail_json TEXT
    );
    CREATE TABLE IF NOT EXISTS drafts (
        id INTEGER PRIMARY KEY,
        application_id INTEGER NOT NULL REFERENCES applications(id),
        version INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        status TEXT NOT NULL,            -- drafting|failed|ready
        dir TEXT,                        -- drafts/<application_id>/v<version>/
        claims_json TEXT, verify_json TEXT, review_json TEXT, models_json TEXT, error TEXT,
        UNIQUE(application_id, version)
    );
    CREATE TABLE IF NOT EXISTS requirements (
        id INTEGER PRIMARY KEY,
        posting_id INTEGER NOT NULL REFERENCES postings(id),
        text TEXT NOT NULL,
        tier TEXT NOT NULL,              -- jd_quoted|structural|inferred
        quote TEXT,                      -- verbatim span from the posting (jd_quoted only)
        quote_verified INTEGER NOT NULL DEFAULT 0,
        weight REAL,
        blocker INTEGER NOT NULL DEFAULT 0,  -- never 1 for tier=inferred (enforced in code + CHECK)
        CHECK (NOT (tier = 'inferred' AND blocker = 1))
    );
    CREATE TABLE IF NOT EXISTS commands (
        event_id TEXT PRIMARY KEY,
        room_id TEXT NOT NULL,
        sender TEXT NOT NULL,
        body TEXT,
        received_at TEXT NOT NULL,
        parsed_json TEXT,
        status TEXT NOT NULL,            -- done|ignored|rejected_sender|error
        reply_event_id TEXT,
        error TEXT
    );
    CREATE TABLE IF NOT EXISTS outcome_proposals (
        id INTEGER PRIMARY KEY,
        application_id INTEGER REFERENCES applications(id),
        source_message_id TEXT NOT NULL UNIQUE,
        mailbox TEXT,
        received_at TEXT,
        subject TEXT,
        from_addr TEXT,
        proposed_status TEXT NOT NULL,   -- applied|assessment|interview|offer|rejected  (never 'hired')
        confidence REAL,
        evidence_json TEXT,
        batch_id TEXT,
        status TEXT NOT NULL DEFAULT 'proposed',  -- proposed|approved|rejected|expired
        decided_at TEXT,
        CHECK (proposed_status <> 'hired')
    );
    """,
    # v3 -- web board (BUI-91): UI-only state. Not apply-layer tables, so the ledger and
    # `jobwatch reindex` never touch them. Plus read indexes for the board.
    """
    CREATE TABLE IF NOT EXISTS web_views (
        posting_id INTEGER PRIMARY KEY REFERENCES postings(id) ON DELETE CASCADE,
        first_viewed_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS saved_searches (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        query_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        last_visit_at TEXT
    );
    CREATE INDEX IF NOT EXISTS ix_postings_first_seen ON postings(first_seen_at);
    CREATE INDEX IF NOT EXISTS ix_matches_matched_at ON matches(matched_at);
    CREATE INDEX IF NOT EXISTS ix_applications_status ON applications(status);
    CREATE INDEX IF NOT EXISTS ix_app_events_app ON application_events(application_id, at);
    """,
    # v4 -- design annotations (web/design.py): UI-only tables, like web_views and saved_searches.
    # Not apply-layer tables: the ledger and `jobwatch reindex` never touch them.
    """
    CREATE TABLE IF NOT EXISTS design_refs (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        source_url TEXT,
        filename TEXT NOT NULL,          -- random name under <data>/design/
        mime TEXT NOT NULL,
        width INTEGER,
        height INTEGER,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS design_notes (
        id INTEGER PRIMARY KEY,
        ref_id INTEGER REFERENCES design_refs(id) ON DELETE CASCADE,   -- NULL = a note on a live page
        page TEXT,                       -- path + query of the annotated page (or /design/ref/N)
        selector TEXT,
        snapshot TEXT,
        tag TEXT,
        rect_json TEXT,
        viewport_json TEXT,
        scheme TEXT,
        comment TEXT NOT NULL,
        category TEXT,
        priority TEXT,
        status TEXT NOT NULL DEFAULT 'open',   -- open | resolved
        created_at TEXT,
        resolved_at TEXT,
        resolution TEXT
    );
    CREATE INDEX IF NOT EXISTS ix_design_notes_status ON design_notes(status);
    CREATE INDEX IF NOT EXISTS ix_design_notes_page ON design_notes(page);
    CREATE INDEX IF NOT EXISTS ix_design_notes_ref ON design_notes(ref_id);
    """,
    # v5 -- AI ad reader (reader.py): the full ad text and the model's verdict, one row per posting.
    # Postings and matches are never changed by the reader; the board reads these to hide/rank.
    """
    CREATE TABLE IF NOT EXISTS ad_text (
        posting_id INTEGER PRIMARY KEY REFERENCES postings(id) ON DELETE CASCADE,
        text TEXT NOT NULL,
        source TEXT NOT NULL,            -- seek_detail | description | jora_detail
        fetched_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS ad_reviews (
        posting_id INTEGER PRIMARY KEY REFERENCES postings(id) ON DELETE CASCADE,
        content_hash TEXT NOT NULL,      -- sha256(prompt version, model, title, company, text): same ad = no new call
        prompt_version INTEGER NOT NULL,
        model TEXT NOT NULL,
        text_source TEXT,                -- full | teaser (teaser = the ad body could not be fetched)
        text_len INTEGER,
        verdict TEXT NOT NULL,           -- show | hide | review
        hide_reason TEXT,                -- sponsored_ad | not_a_real_job | needs_citizen_or_pr | too_senior | low_fit | not_target
        fit INTEGER,                     -- 0-100, the model's reading of how well the ad fits the owner's wanted jobs
        real_job INTEGER,
        ad_kind TEXT,                    -- employer | agency | talent_pool | scam | other
        rights TEXT,                     -- none_stated | valid_work_rights | citizen_or_pr | citizen_only | clearance
        rights_quote TEXT,               -- exact words from the ad (checked against the text)
        seniority TEXT,
        min_years INTEGER,
        role_match TEXT,
        reason TEXT,
        pros_json TEXT,
        cons_json TEXT,
        flags_json TEXT,
        cost_usd REAL,
        reviewed_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_ad_reviews_verdict ON ad_reviews(verdict, fit);
    """,
    # v6 -- keep the model's own answer, so a change to the hiding rules is re-applied without a new model call
    """
    ALTER TABLE ad_reviews ADD COLUMN model_json TEXT;
    """,
    # v7 -- AI recall (recall.py): which non-matching postings a model already judged by meaning (title + ad start)
    """
    CREATE TABLE IF NOT EXISTS ai_triage (
        posting_id INTEGER PRIMARY KEY REFERENCES postings(id) ON DELETE CASCADE,
        version INTEGER NOT NULL,
        content_hash TEXT NOT NULL,      -- postings.dedupe_key at the time (company|title|city)
        relevant INTEGER NOT NULL,
        model TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
    # v8 -- career-ops style evaluation (reader.py prompt v3): global score 1-5, archetype, legitimacy tier and the
    # whole structured report (requirement match table, gaps, authorization, dimensions) as JSON
    """
    ALTER TABLE ad_reviews ADD COLUMN score REAL;
    ALTER TABLE ad_reviews ADD COLUMN archetype TEXT;
    ALTER TABLE ad_reviews ADD COLUMN legitimacy TEXT;
    ALTER TABLE ad_reviews ADD COLUMN report_json TEXT;
    """,
    # v9 -- fetch log (adtext.py): every try to read an ad's page, so a dead or walled ad is not requested on every run
    # (at most 3 tries, not before 24 h after the last one)
    """
    CREATE TABLE IF NOT EXISTS ad_fetch (
        posting_id INTEGER PRIMARY KEY REFERENCES postings(id) ON DELETE CASCADE,
        tries INTEGER NOT NULL DEFAULT 0,
        last_try_at TEXT,
        last_status TEXT                 -- ok | gone | wall | empty | refused | blocked: ... | error: ...
    );
    """,
    # v10 -- private owner interview context; preparing is not applying.
    """
    CREATE TABLE IF NOT EXISTS interview_inputs (
        posting_id INTEGER PRIMARY KEY REFERENCES postings(id),
        updated_at TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK(revision >= 1),
        inputs_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS interview_runs (
        run_key TEXT PRIMARY KEY,
        posting_id INTEGER NOT NULL REFERENCES postings(id),
        detail_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS interview_runs_posting ON interview_runs(posting_id);
    """,
    # v11 -- private standalone preparation; never creates a tracker posting.
    """
    CREATE TABLE IF NOT EXISTS interview_subjects (
        subject_id TEXT PRIMARY KEY,
        revision INTEGER NOT NULL CHECK(revision >= 1),
        detail_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS interview_subject_runs (
        run_key TEXT PRIMARY KEY,
        subject_id TEXT NOT NULL REFERENCES interview_subjects(subject_id),
        detail_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS interview_subject_runs_subject ON interview_subject_runs(subject_id);
    """,
    # Every job has an expiry (owner 2026-10-20: "for all of the job need to have expiry so we wont have any stale
    # ads"). expires_at = the ad's own closing date when known, else 30 days after posting; past it the job is
    # re-checked live and closed_at is set when it is gone.
    """
    ALTER TABLE postings ADD COLUMN expires_at TEXT;
    ALTER TABLE postings ADD COLUMN closed_at TEXT;
    UPDATE postings SET expires_at = strftime('%Y-%m-%dT%H:%M:%S+00:00',
        COALESCE(posted_at, first_seen_at), '+30 days') WHERE expires_at IS NULL;
    CREATE INDEX IF NOT EXISTS ix_postings_expiry ON postings(closed_at, expires_at);
    """,
    # Private discovery vectors, judgments and counted paid work.
    """
    CREATE TABLE text_embeddings (
        key TEXT NOT NULL, model TEXT NOT NULL, dims INTEGER NOT NULL,
        vector BLOB NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(key, model)
    );
    CREATE TABLE posting_relevance (
        posting_id INTEGER NOT NULL REFERENCES postings(id) ON DELETE CASCADE,
        ad_hash TEXT NOT NULL, plan_hash TEXT NOT NULL,
        relevant TEXT NOT NULL CHECK(relevant IN ('yes','no','uncertain')),
        method TEXT NOT NULL, similarity REAL NOT NULL, mode TEXT NOT NULL,
        judgment_json TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(posting_id, ad_hash, plan_hash)
    );
    CREATE TABLE discovery_spend (
        id INTEGER PRIMARY KEY, at REAL NOT NULL, purpose TEXT NOT NULL,
        charged_tokens INTEGER NOT NULL
    );
    CREATE INDEX discovery_spend_at ON discovery_spend(at);
    """,
    # Versioned explained shortlist snapshots; all records stay per person.
    """
    CREATE TABLE shortlists (
        shortlist_id TEXT PRIMARY KEY, person TEXT NOT NULL, built_at TEXT NOT NULL,
        profile_version INTEGER NOT NULL, ordering TEXT NOT NULL,
        rules_version TEXT NOT NULL, fit_id TEXT, content_hash TEXT NOT NULL,
        input_hash TEXT NOT NULL, summary_json TEXT NOT NULL
    );
    CREATE INDEX shortlists_person ON shortlists(person,built_at);
    CREATE TABLE shortlist_entries (
        entry_id TEXT PRIMARY KEY, shortlist_id TEXT NOT NULL REFERENCES shortlists(shortlist_id),
        posting_id INTEGER NOT NULL, rank INTEGER NOT NULL, label TEXT NOT NULL,
        payload_json TEXT NOT NULL, UNIQUE(shortlist_id,posting_id)
    );
    CREATE INDEX shortlist_rank ON shortlist_entries(shortlist_id,rank);
    CREATE TABLE shortlist_impressions (
        id INTEGER PRIMARY KEY, shortlist_id TEXT NOT NULL REFERENCES shortlists(shortlist_id),
        entry_id TEXT NOT NULL REFERENCES shortlist_entries(entry_id), posting_id INTEGER NOT NULL,
        rank INTEGER NOT NULL, ordering TEXT NOT NULL, probability REAL,
        shown_at TEXT NOT NULL, surface TEXT NOT NULL, shown_day TEXT NOT NULL,
        UNIQUE(entry_id,surface,shown_day)
    );
    """,
    """
    CREATE TABLE feedback_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, person TEXT NOT NULL,
        posting_id INTEGER, entry_id TEXT,
        kind TEXT NOT NULL CHECK(kind IN ('reject','restore','select','exclude','comparison','answer')),
        reason_code TEXT, reason_text TEXT NOT NULL DEFAULT '', meaning TEXT,
        reasons_version TEXT NOT NULL, actor TEXT NOT NULL CHECK(actor='person'),
        source TEXT NOT NULL CHECK(source IN ('api','chat')), run_key TEXT,
        profile_version INTEGER, request_id TEXT NOT NULL, prompt_id TEXT,
        detail_json TEXT NOT NULL DEFAULT '{}', input_hash TEXT NOT NULL,
        created_at TEXT NOT NULL, UNIQUE(person,request_id)
    );
    CREATE INDEX feedback_person_posting ON feedback_events(person,posting_id,id);
    CREATE TRIGGER feedback_events_no_update BEFORE UPDATE ON feedback_events
        BEGIN SELECT RAISE(ABORT,'immutable'); END;
    CREATE TRIGGER feedback_events_no_delete BEFORE DELETE ON feedback_events
        BEGIN SELECT RAISE(ABORT,'immutable'); END;
    CREATE TABLE feedback_prompts (
        id TEXT PRIMARY KEY, person TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('comparison','question')),
        subject_json TEXT NOT NULL, context_hash TEXT NOT NULL,
        basis TEXT NOT NULL, expected_gain REAL, set_id TEXT,
        profile_version INTEGER, created_at TEXT NOT NULL,
        closed_at TEXT, closed_reason TEXT CHECK(closed_reason IN ('answered','dismissed','stale'))
    );
    CREATE UNIQUE INDEX feedback_one_open ON feedback_prompts(person) WHERE closed_at IS NULL;
    CREATE INDEX feedback_prompt_history ON feedback_prompts(person,created_at);
    CREATE TABLE selection_requests (
        id TEXT PRIMARY KEY, person TEXT NOT NULL, request_key TEXT NOT NULL,
        input_hash TEXT NOT NULL, manifest_json TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('pending_dispatch','queued','running','completed','failed','cancelled')),
        run_id TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(person,request_key)
    );
    CREATE INDEX selection_pending ON selection_requests(person,state,created_at);
    CREATE TRIGGER selection_inputs_immutable BEFORE UPDATE OF id,person,request_key,input_hash,manifest_json,created_at
        ON selection_requests BEGIN SELECT RAISE(ABORT,'immutable'); END;
    CREATE TRIGGER selection_no_delete BEFORE DELETE ON selection_requests
        BEGIN SELECT RAISE(ABORT,'immutable'); END;
    """,
    """
    ALTER TABLE selection_requests ADD COLUMN result_json TEXT;
    CREATE TRIGGER selection_result_immutable BEFORE UPDATE OF result_json ON selection_requests
        WHEN OLD.result_json IS NOT NULL AND NEW.result_json IS NOT OLD.result_json
        BEGIN SELECT RAISE(ABORT,'immutable'); END;
    """,
]


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    migrate(conn)
    return conn


def _statements(script: str):
    """Split a migration script into complete statements (executescript would commit between them)."""
    buf = ""
    for line in script.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            yield buf
            buf = ""
    if buf.strip():
        yield buf


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations, each in one BEGIN IMMEDIATE transaction together with its user_version.

    A kill mid-migration rolls back to the previous version; a second starter waits for the lock, then
    re-reads the version and skips what the first one already did.
    """
    if conn.in_transaction:
        conn.commit()
    if conn.execute("PRAGMA user_version").fetchone()[0] >= len(MIGRATIONS):
        return conn.execute("PRAGMA user_version").fetchone()[0]
    for index, script in enumerate(MIGRATIONS, start=1):
        conn.execute("BEGIN IMMEDIATE")
        try:
            if conn.execute("PRAGMA user_version").fetchone()[0] >= index:
                conn.rollback()
                continue
            for statement in _statements(script):
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version={index}")
            conn.commit()
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise
    return conn.execute("PRAGMA user_version").fetchone()[0]


def ts(dt=None) -> str:
    return (dt or now_utc()).isoformat(timespec="seconds")


# -- state ------------------------------------------------------------------
def get_state(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def set_state(conn: sqlite3.Connection, key: str, value) -> None:
    conn.execute("INSERT INTO state(key, value) VALUES(?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))
    # Commit now: collectors call this at their start (rotate), and an open write transaction would stay
    # locked for the whole collection (minutes of network), making every other writer fail with "database is locked".
    conn.commit()


# -- runs -------------------------------------------------------------------
def start_run(conn, kind: str, tier: str | None, dry_run: bool) -> int:
    cur = conn.execute("INSERT INTO runs(kind, tier, dry_run, started_at) VALUES(?,?,?,?)",
                       (kind, tier, int(dry_run), ts()))
    conn.commit()
    return cur.lastrowid


def finish_run(conn, run_id: int, stats: dict) -> None:
    conn.execute("UPDATE runs SET finished_at=?, stats_json=? WHERE id=?",
                 (ts(), json.dumps(stats, default=str), run_id))
    conn.commit()


# -- health -----------------------------------------------------------------
def record_health(conn, collector: str, status: str, count: int, latency_ms: int,
                  error: str | None) -> dict:
    """Update a collector's health row. status: ok | partial | error | skipped."""
    row = conn.execute("SELECT * FROM source_health WHERE collector=?", (collector,)).fetchone()
    failures = row["consecutive_failures"] if row else 0
    alerted = row["alerted"] if row else 0
    last_ok = row["last_ok_at"] if row else None
    now = ts()
    if status == "error":
        failures += 1
    elif status in ("ok", "partial"):
        failures, alerted, last_ok = 0, 0, now
    conn.execute(
        """INSERT INTO source_health(collector, last_run_at, last_ok_at, last_status, last_error,
               last_count, last_latency_ms, consecutive_failures, alerted)
           VALUES(?,?,?,?,?,?,?,?,?)
           ON CONFLICT(collector) DO UPDATE SET last_run_at=excluded.last_run_at,
               last_ok_at=excluded.last_ok_at, last_status=excluded.last_status,
               last_error=excluded.last_error, last_count=excluded.last_count,
               last_latency_ms=excluded.last_latency_ms,
               consecutive_failures=excluded.consecutive_failures, alerted=excluded.alerted""",
        (collector, now, last_ok, status, (error or "")[:1000] or None, count, latency_ms,
         failures, alerted))
    conn.commit()
    return {"collector": collector, "consecutive_failures": failures, "alerted": alerted,
            "status": status, "error": error}


def last_ok(conn, collector: str):
    row = conn.execute("SELECT last_ok_at FROM source_health WHERE collector=?", (collector,)).fetchone()
    return row[0] if row else None


# -- retention ----------------------------------------------------------------
def prune(conn, retention_days: int) -> int:
    """Delete non-matching postings not seen for `retention_days` (matches are kept).

    Postings that applications or requirements point to (foreign keys without ON DELETE) are kept too,
    and a failure here never aborts the run: the board and the ledger matter more than housekeeping.
    """
    cutoff = ts(now_utc() - timedelta(days=retention_days))
    try:
        cur = conn.execute(
            "DELETE FROM postings WHERE last_seen_at < ? AND id NOT IN (SELECT posting_id FROM matches)"
            " AND id NOT IN (SELECT posting_id FROM applications)"
            " AND id NOT IN (SELECT posting_id FROM requirements)"
            " AND id NOT IN (SELECT posting_id FROM interview_inputs)"
            " AND id NOT IN (SELECT posting_id FROM interview_runs)",
            (cutoff,))
        pruned = cur.rowcount
        conn.execute("DELETE FROM reddit_posts WHERE seen_at < ? AND stream='chatter'",
                     (ts(now_utc() - timedelta(days=max(retention_days, 365))),))
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        log.warning("prune skipped: %s", type(exc).__name__)
        return 0
    return pruned
