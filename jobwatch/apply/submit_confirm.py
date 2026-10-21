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

# The fields an applicant fills: hidden inputs (tokens, timestamps) and captcha responses change without the owner and
# are not reviewed content, so they are left out; contenteditable and custom widgets are not read (owner touches on
# them still void a confirmation through the owner revision).
_FORM_STATE = '''() => Array.from(document.querySelectorAll('input,select,textarea'))
  .filter(e => e.type !== 'hidden' && !/^(g-recaptcha|h-captcha|cf-turnstile)-response$/.test(e.name || e.id || ''))
  .map(e => [e.tagName, e.type || '', e.name || '', e.id || '',
    (e.type === 'checkbox' || e.type === 'radio') ? (e.checked ? '1' : '0')
      : e.type === 'file' ? Array.from(e.files || []).map(f => f.name + ':' + f.size).join('|')
      : e.multiple && e.tagName === 'SELECT' ? Array.from(e.selectedOptions).map(o => o.value).join('|') : (e.value || '')])'''
# One label rule for recording and for pressing (aria-label first, then an input's value, then the visible text).
_LABEL = (r"e=>(e.getAttribute('aria-label')||(e.tagName==='INPUT'?e.value:e.innerText)||'')"
          r".trim().toLowerCase().replace(/\s+/g,' ')")

_BOUND = ('run_id', 'package_hash', 'session_id', 'page_url_sha256', 'owner_revision', 'attached_documents',
          'final_control', 'form_state')


class SubmitRefused(ValueError):
    """Fixed reason codes only; never page text."""


def form_state(page) -> str:
    """Digest of every input, select and textarea value in every frame of the live page, in frame order."""
    rows = []
    for frame in page.frames:
        try:
            fields = frame.evaluate(_FORM_STATE)
        except Exception:  # noqa: BLE001 - a frame that cannot be read holds no reviewed field
            continue
        if fields:                      # only frames with form fields: ads and widgets come and go with new URLs
            rows.append([frame.url, fields])
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()


def control_label(element) -> str:
    return element.evaluate(_LABEL)


def digest(prepared: dict | None) -> str | None:
    """The confirmation digest of a ready-for-review fill, or None when it cannot be confirmed."""
    if not prepared or prepared.get('status') != 'ready_for_owner' or any(prepared.get(k) in (None, '') for k in _BOUND):
        return None
    bound = {k: prepared[k] for k in _BOUND}
    return hashlib.sha256(json.dumps(bound, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def record_control(page, control: dict) -> dict | None:
    """The final control as a confirmation stores it: its frame chain and selector plus the label read with the same
    rule final_control checks at press time. None when it does not resolve to one final-labelled element."""
    from .prefill_workflow import PrefillRefused, _scope
    try:
        handles = _scope(page, {'url': control['url'], 'frame_path': control.get('frame_path') or []}
                         ).query_selector_all(control['selector'])
    except (PrefillRefused, KeyError):
        return None
    label = control_label(handles[0]) if len(handles) == 1 else ''
    return dict(control, label=label) if FINAL_LABEL.fullmatch(label) else None


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
    label = control_label(element)
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
        status TEXT NOT NULL DEFAULT 'pending', reason TEXT, updated_at REAL NOT NULL,  -- pending|pressed|submitted|unsure|refused|expired
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


PRESS_WAIT_SECONDS = 120     # a pressed request with no page verdict by then is recorded as unsure


def pending(conn: sqlite3.Connection, now: float | None = None) -> list[sqlite3.Row]:
    """Pending requests; expired ones, and pressed ones that never got a page verdict, are closed first."""
    now = time.time() if now is None else now
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='submit_requests'").fetchone():
        return []                       # nothing ever queued for this person: no write from a background loop
    changed = conn.execute("UPDATE submit_requests SET status='expired', updated_at=? WHERE status='pending' AND expires_at<=?",
                           (now, now)).rowcount
    changed += conn.execute("UPDATE submit_requests SET status='unsure', reason='no_page_verdict', updated_at=? "
                            "WHERE status='pressed' AND updated_at<=?", (now, now - PRESS_WAIT_SECONDS)).rowcount
    if changed:
        conn.commit()
    conn.row_factory = sqlite3.Row
    return conn.execute("SELECT * FROM submit_requests WHERE status='pending' ORDER BY id").fetchall()


def settle(conn: sqlite3.Connection, request_id: int, status: str, reason: str | None = None) -> None:
    conn.execute("UPDATE submit_requests SET status=?, reason=?, updated_at=? WHERE id=? AND status='pending'",
                 (status, reason, time.time(), request_id))
    conn.commit()


def verdict(conn: sqlite3.Connection, application_id: int, result: str) -> None:
    """The page's verdict after a press ('confident' or 'unsure') closes that application's pressed request, whoever
    read it first (the prepare page poll or the background loop)."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='submit_requests'").fetchone():
        return
    conn.execute("UPDATE submit_requests SET status=?, updated_at=? WHERE application_id=? AND status='pressed'",
                 ('submitted' if result == 'confident' else 'unsure', time.time(), application_id))
    conn.commit()


def outcome(conn: sqlite3.Connection, posting_id: int) -> dict | None:
    """The newest request for a posting, for chat status replies."""
    ensure(conn)
    row = conn.execute("SELECT id, status, reason FROM submit_requests WHERE posting_id=? ORDER BY id DESC LIMIT 1",
                       (posting_id,)).fetchone()
    return {'request_id': row[0], 'status': row[1], 'reason': row[2]} if row else None
