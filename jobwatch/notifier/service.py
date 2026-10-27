"""Channels, outbox and receipts.

`enqueue` + `dispatch`: durable delivery with attempts and backoff (alerts). `deliver`: one attempt now, for a caller
that keeps its own retry state (the incident digest). Both write a receipt per attempt and skip an event whose
dedupe key was already sent inside its window.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from . import channels as _channels
from . import legacy
from .events import EVENT_KINDS, Event
from .schema import DDL

log = logging.getLogger(__name__)
RETRY_SECONDS = (60, 300, 900, 3600)
MAX_ATTEMPTS = 8
LEASE_SECONDS = 60
DEFAULT_EVENTS = ("failure", "action_required")
DEFAULT_DIGEST = {"incident": 6 * 3600}


@dataclass(frozen=True)
class ChannelConfig:
    name: str
    kind: str
    enabled: bool = True
    config: dict = field(default_factory=dict)
    events: tuple = DEFAULT_EVENTS
    digest: dict = field(default_factory=lambda: dict(DEFAULT_DIGEST))
    source: str = "database"          # 'database' | 'env-alias'

    def window(self, group: str) -> int:
        return int(self.digest.get(group, DEFAULT_DIGEST.get(group, 0)))


@dataclass
class DeliveryResult:
    status: str                       # 'delivered' | 'failed' | 'no_channel'
    receipts: list = field(default_factory=list)

    @property
    def delivered(self) -> bool:
        return self.status == "delivered"

    @property
    def error(self) -> str | None:
        return {"delivered": None, "no_channel": "no_channel"}.get(self.status, "delivery_failed")


def ensure(conn) -> None:
    for statement in DDL.split(";"):
        if statement.strip():
            conn.execute(statement)
    conn.commit()


def _person(person):
    from jobwatch import users
    return person or users.current()


def _now_text() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# -- channel configuration ---------------------------------------------------
def _row_to_config(row) -> ChannelConfig:
    return ChannelConfig(row[0], row[1], bool(row[2]), json.loads(row[3]), tuple(json.loads(row[4])), json.loads(row[5]))


_COLS = "name,kind,enabled,config_json,events_json,digest_json"


def stored_channels(conn, person=None) -> list[ChannelConfig]:
    ensure(conn)
    return [_row_to_config(r) for r in conn.execute(
        f"SELECT {_COLS} FROM notify_channels WHERE person=? ORDER BY id", (_person(person),))]


def _alias(conn, person) -> ChannelConfig | None:
    """The older install-wide settings, as an equivalent channel for the owner only."""
    from jobwatch import settings, users
    if person != users.DEFAULT_USER:
        return None
    if not (settings.get(legacy.SSH_ENV) and settings.get(legacy.FILE_ENV)):
        return None
    return ChannelConfig(legacy.ALIAS_CHANNEL, "ssh_append",
                         config={"host_ref": f"env:{legacy.SSH_ENV}", "file_ref": f"env:{legacy.FILE_ENV}"},
                         source="env-alias")


def channels_for(conn, person=None, *, include_disabled=False) -> list[ChannelConfig]:
    """Stored channels, plus the settings alias while the person has no channel of their own that can deliver."""
    person = _person(person)
    stored = stored_channels(conn, person)
    out = list(stored)
    own = any(c.enabled and c.kind != "none" for c in stored)
    if not own and not any(c.name == legacy.ALIAS_CHANNEL for c in stored):
        alias = _alias(conn, person)
        if alias:
            out.append(alias)
    return out if include_disabled else [c for c in out if c.enabled and c.kind != "none"]


def add_channel(conn, name: str, kind: str, config: dict | None = None, *, person=None, events=None, digest=None,
                enabled=True) -> ChannelConfig:
    """Create or replace a channel by (person, name). Config is validated: secrets must be references."""
    name = (name or "").strip()
    if not name or len(name) > 60 or not name.replace("-", "").replace("_", "").isalnum():
        raise ValueError("invalid_channel_name")
    config = _channels.validate_config(kind, config or {})
    events = list(events or DEFAULT_EVENTS)
    if not set(events) <= set(EVENT_KINDS):
        raise ValueError("invalid_event_filter")
    digest = {str(k): int(v) for k, v in (digest or DEFAULT_DIGEST).items()}
    if any(v < 0 for v in digest.values()):
        raise ValueError("invalid_digest_window")
    ensure(conn)
    conn.execute("INSERT INTO notify_channels(person,name,kind,enabled,config_json,events_json,digest_json,created_at) "
                 "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(person,name) DO UPDATE SET kind=excluded.kind,"
                 "enabled=excluded.enabled,config_json=excluded.config_json,events_json=excluded.events_json,"
                 "digest_json=excluded.digest_json",
                 (_person(person), name, kind, int(enabled), json.dumps(config, sort_keys=True), json.dumps(events),
                  json.dumps(digest, sort_keys=True), _now_text()))
    conn.commit()
    return next(c for c in stored_channels(conn, person) if c.name == name)


def disable_channel(conn, name: str, *, person=None) -> bool:
    """Switch a channel off. The settings alias has no row, so disabling it stores a disabled one."""
    person = _person(person)
    ensure(conn)
    if conn.execute("UPDATE notify_channels SET enabled=0 WHERE person=? AND name=?", (person, name)).rowcount:
        conn.commit()
        return True
    if name == legacy.ALIAS_CHANNEL:
        conn.execute("INSERT INTO notify_channels(person,name,kind,enabled,config_json,created_at) VALUES(?,?,?,?,?,?)",
                     (person, name, "none", 0, "{}", _now_text()))
        conn.commit()
        return True
    return False


def _matching(conn, event: Event, person) -> list[ChannelConfig]:
    return [c for c in channels_for(conn, person) if event.kind in c.events]


def digest_window(conn, group: str, *, person=None) -> int:
    """Seconds to batch a group of events: the shortest window among the channels that would deliver it."""
    windows = [c.window(group) for c in channels_for(conn, person)]
    return min(windows) if windows else DEFAULT_DIGEST.get(group, 0)


# -- sending -------------------------------------------------------------------
def _attempt(conn, cfg: ChannelConfig, event: Event, person, *, outbox_id, attempt, now) -> _channels.Receipt:
    try:
        receipt = _channels.build(cfg.kind, cfg.name, cfg.config).send(event)
    except Exception as exc:  # noqa: BLE001 - a transport bug is a failed receipt, not a crash
        receipt = _channels.Receipt("failed", f"error_{type(exc).__name__}"[:60], now)
    conn.execute("INSERT INTO notify_receipts(outbox_id,person,channel,kind,event_kind,dedupe_key,attempt,status,detail,at) "
                 "VALUES(?,?,?,?,?,?,?,?,?,?)",
                 (outbox_id, person, cfg.name, cfg.kind, event.kind, event.key, attempt, receipt.status, receipt.detail, now))
    if not receipt.ok:
        log.warning("notify: channel %s (%s) did not deliver: %s", cfg.name, cfg.kind, receipt.detail)
    return receipt


def _duplicate(conn, person, channel, event: Event, now) -> bool:
    if event.dedupe_window <= 0:
        return False
    return conn.execute("SELECT 1 FROM notify_outbox WHERE person=? AND channel=? AND dedupe_key=? AND created_at>? AND state<>'failed' LIMIT 1",
                        (person, channel, event.key, now - event.dedupe_window)).fetchone() is not None


def enqueue(conn, event: Event, *, person=None, message_id=None, now=None) -> int:
    """Queue the event for every channel that takes it; a key already sent inside its window is skipped.
    Returns the number of new outbox rows."""
    person, now = _person(person), time.time() if now is None else now
    ensure(conn)
    made = 0
    for cfg in _matching(conn, event, person):
        if _duplicate(conn, person, cfg.name, event, now):
            continue
        conn.execute("INSERT INTO notify_outbox(person,channel,dedupe_key,event_kind,event_json,message_id,created_at) "
                     "VALUES(?,?,?,?,?,?,?)",
                     (person, cfg.name, event.key, event.kind, json.dumps(event.to_dict()), message_id, now))
        made += 1
    conn.commit()
    return made


def dispatch(conn, *, person=None, now=None, limit=50) -> int:
    """Try every due outbox row once; failures wait RETRY_SECONDS, then stop after MAX_ATTEMPTS. Returns deliveries."""
    person, now = _person(person), time.time() if now is None else now
    ensure(conn)
    rows = conn.execute("SELECT id,channel,event_json,attempts,message_id FROM notify_outbox WHERE person=? AND state='pending' "
                        "AND next_attempt_at<=? AND (lease_until IS NULL OR lease_until<=?) ORDER BY id LIMIT ?",
                        (person, now, now, limit)).fetchall()
    configs = {c.name: c for c in channels_for(conn, person)}
    delivered = 0
    for oid, name, event_json, attempts, message_id in rows:
        cfg = configs.get(name)
        if cfg is None:                       # channel since disabled or removed: leave the row, it may come back
            continue
        if not conn.execute("UPDATE notify_outbox SET lease_until=? WHERE id=? AND state='pending' "
                            "AND (lease_until IS NULL OR lease_until<=?)", (now + LEASE_SECONDS, oid, now)).rowcount:
            continue
        conn.commit()
        receipt = _attempt(conn, cfg, Event.from_dict(json.loads(event_json)), person,
                           outbox_id=oid, attempt=attempts + 1, now=now)
        attempts += 1
        if receipt.ok:
            conn.execute("UPDATE notify_outbox SET state='delivered',attempts=?,delivered_at=?,lease_until=NULL,last_error=NULL "
                         "WHERE id=?", (attempts, now, oid))
            if message_id is not None and conn.execute("SELECT 1 FROM sqlite_master WHERE name='chat_messages'").fetchone():
                conn.execute("UPDATE chat_messages SET pushed_at=? WHERE id=? AND pushed_at IS NULL", (_now_text(), message_id))
            delivered += 1
        else:
            state = "failed" if attempts >= MAX_ATTEMPTS else "pending"
            conn.execute("UPDATE notify_outbox SET state=?,attempts=?,next_attempt_at=?,lease_until=NULL,last_error=? WHERE id=?",
                         (state, attempts, now + RETRY_SECONDS[min(attempts - 1, len(RETRY_SECONDS) - 1)], receipt.detail, oid))
        conn.commit()
    return delivered


def deliver(conn, event: Event, *, person=None, now=None) -> DeliveryResult:
    """One attempt now on every channel that takes the event; the caller owns any retry. Delivered if any channel took it."""
    person, now = _person(person), time.time() if now is None else now
    ensure(conn)
    targets = _matching(conn, event, person)
    if not targets:
        return DeliveryResult("no_channel")
    receipts = []
    for cfg in targets:
        if _duplicate(conn, person, cfg.name, event, now):
            continue
        oid = conn.execute("INSERT INTO notify_outbox(person,channel,dedupe_key,event_kind,event_json,state,attempts,created_at) "
                           "VALUES(?,?,?,?,?,'failed',1,?)",
                           (person, cfg.name, event.key, event.kind, json.dumps(event.to_dict()), now)).lastrowid
        receipt = _attempt(conn, cfg, event, person, outbox_id=oid, attempt=1, now=now)
        if receipt.ok:
            conn.execute("UPDATE notify_outbox SET state='delivered',delivered_at=? WHERE id=?", (now, oid))
        else:
            conn.execute("UPDATE notify_outbox SET last_error=? WHERE id=?", (receipt.detail, oid))
        receipts.append(receipt)
    conn.commit()
    return DeliveryResult("delivered" if any(r.ok for r in receipts) else "failed", receipts)


def test_channel(conn, name: str, *, person=None) -> tuple[ChannelConfig, _channels.Receipt, bool]:
    """Send a harmless test event straight through one channel (event filters do not apply). Returns the channel, the
    receipt and whether the channel reports itself healthy. Never prints or stores a secret."""
    person = _person(person)
    cfg = next((c for c in channels_for(conn, person, include_disabled=True) if c.name == name), None)
    if cfg is None:
        raise ValueError("channel_not_found")
    event = Event("action_required", "Jobwatch: test notification, nothing to do.", f"test:{int(time.time())}")
    ensure(conn)
    healthy = _channels.build(cfg.kind, cfg.name, cfg.config).healthy()
    receipt = _attempt(conn, cfg, event, person, outbox_id=None, attempt=1, now=time.time())
    conn.commit()
    return cfg, receipt, healthy
