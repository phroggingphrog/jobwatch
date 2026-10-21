"""Owner-confirmed Submit (owner 2026-10-21: "it can submit either the owner click the submit button OR with an
explicit confirmation by user").

Jobwatch presses an employer form's final Submit only for the exact filled form the owner confirmed:

- When a fill stops at the review page (prepared.json status ready_for_owner) it records the one recognised final
  control (frame chain, selector, label) and a digest of the field values read back from the live page.
- `digest(prepared)` binds a confirmation to that run, package, browser target, page URL, owner revision, attached
  PDFs, final control and form state. The board shows it; a chat `submit_application` approval hashes it.
- At press time the browser thread recomputes it from the live page (`live_digest`). Any difference, a touch by the
  owner, a closed browser or an expired request refuses, and nothing is pressed.
- Chat approvals cross processes through `submit_requests` in the person's jobs DB: the agent API only queues; the
  web process, which owns the browser, re-checks and presses within CONFIRM_SECONDS of the approval.

Auto-fill never submits by itself, and the owner's own click on Submit keeps working as before.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time

FINAL_LABEL = re.compile(r'(submit|apply|send)( (application|now|my application))?')
CONFIRM_SECONDS = 15 * 60

_FORM_STATE = '''() => Array.from(document.querySelectorAll('input,select,textarea')).map(e => [
    e.tagName, e.type || '', e.name || '', e.id || '',
    (e.type === 'checkbox' || e.type === 'radio') ? (e.checked ? '1' : '0')
      : e.type === 'file' ? Array.from(e.files || []).map(f => f.name + ':' + f.size).join('|') : (e.value || '')])'''

_BOUND = ('run_id', 'package_hash', 'session_id', 'page_url_sha256', 'owner_revision', 'attached_documents',
          'final_control', 'form_state')


class SubmitRefused(ValueError):
    """Fixed reason codes only; never page text."""


def form_state(page) -> str:
    """Digest of every input, select and textarea value in every frame of the live page, in frame order."""
    rows = []
    for frame in page.frames:
        try:
            rows.append([frame.url, frame.evaluate(_FORM_STATE)])
        except Exception:  # noqa: BLE001 - a detached frame is part of the state too
            rows.append([frame.url, None])
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()


def digest(prepared: dict | None) -> str | None:
    """The confirmation digest of a ready-for-review fill, or None when it cannot be confirmed."""
    if not prepared or prepared.get('status') != 'ready_for_owner' or any(prepared.get(k) in (None, '') for k in _BOUND):
        return None
    bound = {k: prepared[k] for k in _BOUND}
    return hashlib.sha256(json.dumps(bound, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def final_control(page, control: dict):
    """The one element the fill recognised as final Submit, re-found and re-checked on the live page."""
    from .prefill_workflow import PrefillRefused, _scope
    try:
        frame = _scope(page, {'url': control['url'], 'frame_path': control.get('frame_path') or []})
    except (PrefillRefused, KeyError):
        raise SubmitRefused('final_control_changed') from None
    handles = frame.query_selector_all(control['selector'])
    if len(handles) != 1:
        raise SubmitRefused('final_control_changed')
    element = handles[0]
    label = element.evaluate(r"e=>(e.tagName==='INPUT'?e.value:(e.innerText||e.getAttribute('aria-label')||''))"
                             r".trim().toLowerCase().replace(/\s+/g,' ')")
    if not FINAL_LABEL.fullmatch(label) or label != control.get('label') or not element.is_visible() or not element.is_enabled():
        raise SubmitRefused('final_control_changed')
    return element


def live_digest(prepared: dict, page, *, session_id, owner_revision) -> str | None:
    """The digest recomputed from the live page and session (browser thread only)."""
    live = dict(prepared, session_id=session_id, owner_revision=owner_revision,
                page_url_sha256=hashlib.sha256(page.url.encode()).hexdigest(), form_state=form_state(page))
    return digest(live)


# -- chat-approved requests (agent API process -> web process) ---------------------------------------------------
def ensure(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS submit_requests(
        id INTEGER PRIMARY KEY, posting_id INTEGER NOT NULL, application_id INTEGER NOT NULL, digest TEXT NOT NULL,
        approval TEXT NOT NULL, requested_at REAL NOT NULL, expires_at REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', reason TEXT, updated_at REAL NOT NULL,
        UNIQUE(approval))""")


def queue(conn: sqlite3.Connection, *, posting_id: int, application_id: int, confirm_digest: str, approval: str,
          now: float | None = None) -> dict:
    """Queue one approved press; the same approval never queues twice."""
    now = time.time() if now is None else now
    ensure(conn)
    conn.execute("INSERT OR IGNORE INTO submit_requests(posting_id, application_id, digest, approval, requested_at, "
                 "expires_at, updated_at) VALUES(?,?,?,?,?,?,?)",
                 (posting_id, application_id, confirm_digest, approval, now, now + CONFIRM_SECONDS, now))
    conn.commit()
    row = conn.execute("SELECT id, status FROM submit_requests WHERE approval=?", (approval,)).fetchone()
    return {'status': 'queued' if row[1] == 'pending' else row[1], 'request_id': row[0]}


def pending(conn: sqlite3.Connection, now: float | None = None) -> list[sqlite3.Row]:
    """Pending requests; the expired ones are marked expired first."""
    now = time.time() if now is None else now
    ensure(conn)
    conn.execute("UPDATE submit_requests SET status='expired', updated_at=? WHERE status='pending' AND expires_at<=?", (now, now))
    conn.commit()
    conn.row_factory = sqlite3.Row
    return conn.execute("SELECT * FROM submit_requests WHERE status='pending' ORDER BY id").fetchall()


def settle(conn: sqlite3.Connection, request_id: int, status: str, reason: str | None = None) -> None:
    conn.execute("UPDATE submit_requests SET status=?, reason=?, updated_at=? WHERE id=? AND status='pending'",
                 (status, reason, time.time(), request_id))
    conn.commit()


def outcome(conn: sqlite3.Connection, posting_id: int) -> dict | None:
    """The newest request for a posting, for chat status replies."""
    ensure(conn)
    row = conn.execute("SELECT id, status, reason FROM submit_requests WHERE posting_id=? ORDER BY id DESC LIMIT 1",
                       (posting_id,)).fetchone()
    return {'request_id': row[0], 'status': row[1], 'reason': row[2]} if row else None
