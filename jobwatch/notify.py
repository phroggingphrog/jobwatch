"""Owner messages: the Chat page's history and the push of urgent ones to the person's notification channels
(owner 2026-10-12: "I want a chatgpt-like chat box page in jobwatch so it can be reachable" and that jobwatch should
tell their personal assistant when something is wrong).

`notify()` saves a message from jobwatch in `chat_messages`. `alert()` saves an error and queues it for the person's
channels (jobwatch.notifier: ssh_append, command, webhook...), at most once a day per key. A failed delivery stays
in the outbox and is retried by the next alert() or `python -m jobwatch.notify --flush`.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)
from .settings import get as _setting
# No channel configured = no push (messages stay in the Chat page).
BOARD = _setting("JOBWATCH_BOARD_URL", "http://127.0.0.1:8960")

SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY,
    role TEXT NOT NULL CHECK (role IN ('owner','assistant','jobwatch')),
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read_at TEXT,
    push INTEGER NOT NULL DEFAULT 0,      -- 1 = send to the person's notification channels
    pushed_at TEXT
);
"""


def ensure(conn) -> None:
    conn.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def add(conn, role: str, text: str, *, push: bool = False) -> int:
    ensure(conn)
    cur = conn.execute("INSERT INTO chat_messages(role,text,created_at,read_at,push) VALUES(?,?,?,?,?)",
                       (role, text.strip(), _now(), _now() if role == "owner" else None, int(push)))
    conn.commit()
    return cur.lastrowid


def is_live(conn) -> bool:
    """Only the real jobwatch database may text the owner (2026-10-12: test runs pushed five fake 'Synthetic Alpha'
    READY jobs to iMessage)."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    try:
        from jobwatch.config import load_config
        files = [row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main"]
        return bool(files and files[0]) and Path(files[0]).resolve() == Path(load_config().db_path).resolve()
    except Exception:  # noqa: BLE001 - unsure = do not text
        return False


def notify(conn, text: str) -> int:
    """News for the owner (a READY job): Chat page only. The owner wants texts only when something is wrong
    (2026-10-12: "i only want wheres something eror not like that")."""
    return add(conn, "jobwatch", text)


# Pipeline errors are stored as 'Error: ...' rows (texted to the owner, never shown in Chat or sent to the chat model).
CHAT_VISIBLE = "text NOT LIKE 'Error:%'"

# Hold reasons that mean jobwatch itself failed (normal decisions like posting_unavailable or insufficient_evidence
# are not errors and never text the owner).
ERROR_REASONS = {"execution_failed", "artifact_invalid", "invalid_citation", "invalid_requirements",
                 "invalid_tool_arguments", "model_unavailable", "model_truncated_response", "model_invalid_response",
                 "model_auth"}


def alert(conn, text: str, key: str) -> int | None:
    """Something is broken: pushed to the person's notification channels, at most once a day per `key`."""
    ensure(conn)
    since = datetime.now(UTC).timestamp() - 86400
    for (at,) in conn.execute("SELECT created_at FROM chat_messages WHERE role='jobwatch' AND push=1 AND text LIKE ?",
                              (f"%[{key}]%",)):
        if datetime.fromisoformat(at).timestamp() > since:
            return None
    live = is_live(conn)
    mid = add(conn, "jobwatch", f"Error: {text} [{key}]", push=live)
    if live:
        flush(conn)
    return mid


def flush(conn) -> int:
    """Hand every unsent pushed message to the channels and retry what failed earlier. Returns messages delivered."""
    from jobwatch.notifier import FAILURE, Event, FailurePayload, dispatch, enqueue, ensure as ensure_channels
    ensure(conn)
    ensure_channels(conn)
    for mid, text in conn.execute("SELECT id,text FROM chat_messages WHERE push=1 AND pushed_at IS NULL AND id NOT IN "
                                  "(SELECT message_id FROM notify_outbox WHERE message_id IS NOT NULL) ORDER BY id").fetchall():
        key = _alert_key(text) or f"message:{mid}"
        enqueue(conn, Event(FAILURE, f"Jobwatch: {' '.join(text.split())}", key, FailurePayload(reason=key)), message_id=mid)
    return dispatch(conn)


def _alert_key(text: str) -> str | None:
    """The `[key]` an alert() message ends with."""
    tail = text.rstrip()
    if tail.endswith("]") and "[" in tail:
        return "alert:" + tail[tail.rindex("[") + 1:-1]
    return None


def unread(conn) -> int:
    ensure(conn)
    return conn.execute("SELECT COUNT(*) FROM chat_messages WHERE role!='owner' AND text NOT LIKE 'Error:%' AND read_at IS NULL").fetchone()[0]


def mark_read(conn) -> None:
    ensure(conn)
    conn.execute("UPDATE chat_messages SET read_at=? WHERE read_at IS NULL", (_now(),))
    conn.commit()


if __name__ == "__main__":                      # python -m jobwatch.notify "error text" | --flush
    from jobwatch.config import load_config
    from jobwatch.db import connect
    c = connect(load_config().db_path)
    if sys.argv[1:] == ["--flush"]:
        print(flush(c), "pushed")
    else:
        print(alert(c, " ".join(sys.argv[1:]), "manual"))
