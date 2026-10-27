"""Tables of the notification layer. One DDL string, used by the database migration and by `ensure()` (tests and
older databases open without the migration), so both stay identical and idempotent."""

DDL = """
CREATE TABLE IF NOT EXISTS notify_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    config_json TEXT NOT NULL DEFAULT '{}',      -- no secrets: only "<key>_ref": "env:NAME" or "file:/path"
    events_json TEXT NOT NULL DEFAULT '["failure","action_required"]',
    digest_json TEXT NOT NULL DEFAULT '{}',      -- {"<event group>": window seconds}, 0 sends each one at once
    created_at TEXT NOT NULL,
    UNIQUE(person, name)
);
CREATE TABLE IF NOT EXISTS notify_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person TEXT NOT NULL,
    channel TEXT NOT NULL,                       -- channel name
    dedupe_key TEXT NOT NULL,
    event_kind TEXT NOT NULL,
    event_json TEXT NOT NULL,
    message_id INTEGER,                          -- chat_messages row this delivers, if any
    state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','delivered','failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    lease_until REAL,
    created_at REAL NOT NULL,
    delivered_at REAL,
    last_error TEXT
);
CREATE INDEX IF NOT EXISTS notify_outbox_due ON notify_outbox(state, next_attempt_at);
CREATE INDEX IF NOT EXISTS notify_outbox_key ON notify_outbox(person, channel, dedupe_key, created_at);
CREATE TABLE IF NOT EXISTS notify_receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    outbox_id INTEGER,                           -- NULL for a channel test
    person TEXT NOT NULL,
    channel TEXT NOT NULL,
    kind TEXT NOT NULL,
    event_kind TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('delivered','failed')),
    detail TEXT NOT NULL DEFAULT '',             -- short fixed code, never a message, address or secret
    at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS notify_receipts_outbox ON notify_receipts(outbox_id);
"""
