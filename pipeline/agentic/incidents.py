"""Durable assessment failures and their independent notification delivery state.

One person's job database owns these records. Incident text contains fixed codes
and numeric posting IDs, never advertisement text, profile data or exception text.
"""
from __future__ import annotations

import hashlib
import re
import time
import uuid

from jobwatch import notify, users

FAILURE_REASONS = frozenset({
    'deadline_exceeded', 'execution_failed', 'model_unavailable', 'model_auth',
    'model_invalid_response', 'model_truncated_response', 'invalid_requirements',
    'invalid_tool_arguments', 'invalid_tool_call', 'invalid_citation', 'artifact_invalid',
    'checkpoint_invalid', 'checkpoint_unavailable', 'checkpoint_conflict',
    'invalid_checkpoint', 'unknown_batch', 'batch_conflict', 'invalid_transition', 'candidate_hash_mismatch',
    'service_timeout', 'service_terminated', 'worker_interrupted',
    'chat_execution_failed', 'invalid_model_response',
    'token_limit', 'turn_limit', 'failed_attempt_limit', 'missing_terminal', 'tool_failed',
    'unknown_tool', 'invalid_registry', 'invalid_reservation', 'invalid_model_payload',
    'invalid_research_operation', 'terminal_already_selected',
    'model_deadline', 'model_rate_limited', 'model_transient',
    'invalid_configuration', 'credential_unavailable',
})
_CODE = re.compile(r'^[a-z][a-z0-9_]{0,79}$')
_RETRY_SECONDS = (60, 300, 900, 3600)


def _exists(conn, table):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def ensure(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS agentic_incidents (
            incident_id TEXT PRIMARY KEY, posting_id INTEGER, run_id TEXT NOT NULL,
            reason TEXT NOT NULL, phase TEXT, last_successful_phase TEXT, state TEXT NOT NULL DEFAULT 'paused',
            created_at REAL NOT NULL, resolved_at REAL,
            notification_state TEXT NOT NULL DEFAULT 'pending', notification_attempts INTEGER NOT NULL DEFAULT 0,
            next_notification_at REAL NOT NULL DEFAULT 0, notification_lease_until REAL,
            handed_off_at REAL, notification_error TEXT, message_id INTEGER);
        CREATE INDEX IF NOT EXISTS agentic_incidents_posting ON agentic_incidents(posting_id,state);
        CREATE TABLE IF NOT EXISTS agentic_invocations (
            run_id TEXT PRIMARY KEY, unit TEXT, phase TEXT NOT NULL, posting_id INTEGER,
            state TEXT NOT NULL, started_at REAL NOT NULL, updated_at REAL NOT NULL, last_successful_phase TEXT);
    ''')
    conn.execute('BEGIN IMMEDIATE')
    try:
        for table in ('agentic_incidents', 'agentic_invocations'):
            if 'last_successful_phase' not in {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN last_successful_phase TEXT')
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _dict(cursor, row):
    return dict(zip((c[0] for c in cursor.description), row)) if row is not None else None


def _get(conn, incident_id):
    cur = conn.execute('SELECT * FROM agentic_incidents WHERE incident_id=?', (incident_id,))
    return _dict(cur, cur.fetchone())


def list_incidents(conn, *, include_resolved=False, limit=100):
    if not _exists(conn, 'agentic_incidents'):
        return []
    cur = conn.execute('SELECT * FROM agentic_incidents ' + ('' if include_resolved else "WHERE state='paused' ")
                       + 'ORDER BY created_at DESC,incident_id LIMIT ?', (max(1, min(int(limit), 1000)),))
    return [_dict(cur, row) for row in cur.fetchall()]


def is_paused(conn, posting_id):
    if not _exists(conn, 'agentic_incidents'):
        return False
    return conn.execute("SELECT 1 FROM agentic_incidents WHERE posting_id=? AND state='paused' LIMIT 1",
                        (posting_id,)).fetchone() is not None


def _message(row):
    subject = f"assessment for job #{row['posting_id']}" if row['posting_id'] is not None else 'discovery run'
    action = ' Explicit retry is required for this job.' if row['posting_id'] is not None else ' Check discovery status before retrying.'
    return f"Jobwatch stopped {subject}: {row['reason']} (phase: {row['phase'] or 'unknown'}).{action} [incident:{row['incident_id']}]"


def report(conn, *, posting_id=None, run_id=None, reason, phase=None, now=None, notify_immediately=True):
    if reason not in FAILURE_REASONS:
        return None
    if posting_id is not None and (type(posting_id) is not int or posting_id < 1):
        raise ValueError('invalid_posting_id')
    if phase is not None and (type(phase) is not str or not _CODE.fullmatch(phase)):
        phase = 'unknown'
    run_id = str(run_id or '')[:200]
    ensure(conn)
    notify.ensure(conn)
    now = time.time() if now is None else now
    conn.execute('BEGIN IMMEDIATE')
    try:
        if run_id:
            cur = conn.execute('SELECT * FROM agentic_incidents WHERE run_id=? AND posting_id IS ? ORDER BY created_at LIMIT 1',
                               (run_id, posting_id))
        else:
            cur = conn.execute("SELECT * FROM agentic_incidents WHERE posting_id IS ? AND state='paused' ORDER BY created_at LIMIT 1",
                               (posting_id,))
        existing = _dict(cur, cur.fetchone())
        if existing is not None:
            conn.commit()
            return existing
        ident = hashlib.sha256(f'{run_id}:{posting_id}'.encode()).hexdigest()[:32] if run_id else uuid.uuid4().hex
        completed = conn.execute('SELECT last_successful_phase,posting_id FROM agentic_invocations WHERE run_id=?', (run_id,)).fetchone()
        conn.execute('INSERT INTO agentic_incidents(incident_id,posting_id,run_id,reason,phase,last_successful_phase,created_at) VALUES(?,?,?,?,?,?,?)',
                     (ident, posting_id, run_id, reason, phase,
                      completed[0] if completed and completed[1] == posting_id else None, now))
        row = _get(conn, ident)
        stamp = notify._now()
        message = conn.execute("INSERT INTO chat_messages(role,text,created_at,push) VALUES('jobwatch',?,?,0)",
                               (_message(row), stamp)).lastrowid
        conn.execute('UPDATE agentic_incidents SET message_id=? WHERE incident_id=?', (message, ident))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    if notify_immediately:
        flush_notifications(conn, now=now, incident_id=ident)
    return _get(conn, ident)


def release(conn, incident_id, posting_id, *, expected_run_id=None):
    if not _exists(conn, 'agentic_incidents'):
        raise ValueError('incident_not_found')
    conn.execute('BEGIN IMMEDIATE')
    try:
        row = _get(conn, incident_id)
        if row is None or row['posting_id'] != posting_id or (expected_run_id is not None and row['run_id'] != expected_run_id):
            raise ValueError('incident_not_found')
        if row['state'] != 'paused':
            raise ValueError('incident_already_released')
        conn.execute("UPDATE agentic_incidents SET state='released',resolved_at=? WHERE incident_id=?", (time.time(), incident_id))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return _get(conn, incident_id)


def flush_notifications(conn, *, force=False, now=None, incident_id=None):
    """Attempt at most one bounded delivery. SSH append acknowledges handoff only."""
    if not _exists(conn, 'agentic_incidents') or not notify.is_live(conn):
        return 0
    now = time.time() if now is None else now
    # The legacy install-wide route belongs to the owner, never another account.
    configured = users.current() == users.DEFAULT_USER and bool(
        notify._setting('JOBWATCH_HERMES_SSH') and notify._setting('JOBWATCH_HERMES_FILE'))
    params = [now]
    where = "notification_state<>'handed_off' AND (notification_lease_until IS NULL OR notification_lease_until<=?) "
    if not force:
        where += 'AND next_notification_at<=? '
        params.append(now)
    if incident_id is not None:
        where += 'AND incident_id=? '
        params.append(incident_id)
    cur = conn.execute('SELECT incident_id FROM agentic_incidents WHERE ' + where + 'ORDER BY created_at LIMIT 1', params)
    ids = [r[0] for r in cur.fetchall()]
    handed_off = 0
    for ident in ids:
        with conn:
            claimed = conn.execute("UPDATE agentic_incidents SET notification_state='sending',notification_lease_until=?, "
                "notification_attempts=notification_attempts+1 WHERE incident_id=? AND notification_state<>'handed_off' "
                'AND (notification_lease_until IS NULL OR notification_lease_until<=?) AND (? OR next_notification_at<=?)',
                (now + 60, ident, now, bool(force), now)).rowcount
        if not claimed:
            continue
        row = _get(conn, ident)
        try:
            sent = configured and notify._send([_message(row)])
        except Exception:
            sent = False
        delay = _RETRY_SECONDS[min(row['notification_attempts'] - 1, len(_RETRY_SECONDS) - 1)]
        with conn:
            conn.execute('UPDATE agentic_incidents SET notification_state=?,notification_lease_until=NULL,'
                         'next_notification_at=?,handed_off_at=?,notification_error=? WHERE incident_id=?',
                         ('handed_off' if sent else 'failed', now + delay, now if sent else None,
                          None if sent else 'hermes_handoff_failed' if configured else 'hermes_not_configured', ident))
        handed_off += bool(sent)
    return handed_off


def begin_run(conn, run_id, unit=None):
    ensure(conn)
    now = time.time()
    with conn:
        conn.execute("INSERT OR IGNORE INTO agentic_invocations(run_id,unit,phase,posting_id,state,started_at,updated_at) VALUES(?,?,'starting',NULL,'running',?,?)",
                     (str(run_id), unit, now, now))
    flush_notifications(conn)


def mark_phase(conn, run_id, phase, posting_id=None, *, completed=False):
    if not _CODE.fullmatch(phase):
        raise ValueError('invalid_phase')
    ensure(conn)
    with conn:
        conn.execute("UPDATE agentic_invocations SET phase=?,posting_id=?,updated_at=?,"
                     "last_successful_phase=CASE WHEN ? THEN ? WHEN posting_id IS NOT ? THEN NULL ELSE last_successful_phase END "
                     "WHERE run_id=? AND state='running'",
                     (phase, posting_id, time.time(), bool(completed), phase, posting_id, str(run_id)))


def end_run(conn, run_id, state='completed'):
    if state not in ('completed', 'failed', 'interrupted'):
        raise ValueError('invalid_state')
    ensure(conn)
    with conn:
        conn.execute("UPDATE agentic_invocations SET state=?,updated_at=? WHERE run_id=? AND state='running'",
                     (state, time.time(), str(run_id)))


def reconcile_service_exit(conn, *, unit=None, run_id=None, reason='service_timeout'):
    if unit is None and run_id is None:
        raise ValueError('run_identity_required')
    if reason not in ('service_timeout', 'service_terminated', 'worker_interrupted'):
        raise ValueError('invalid_reason')
    if not _exists(conn, 'agentic_invocations'):
        return []
    field, value = ('run_id', str(run_id)) if run_id is not None else ('unit', unit)
    cur = conn.execute(f"SELECT run_id,posting_id,phase FROM agentic_invocations WHERE state='running' AND {field}=?", (value,))
    rows = cur.fetchall()
    result = []
    for ident, pid, phase in rows:
        result.append(report(conn, posting_id=pid, run_id=ident, reason=reason, phase=phase))
        end_run(conn, ident, 'interrupted')
    return result


def reconcile_known_failures(conn):
    """Pause unreported latest failures written before incident reporting existed.

    A later normal outcome wins. Already observed attempts stay observed after an
    explicit retry release; reconciliation must not restore their old pause.
    """
    if not _exists(conn, 'agentic_activity'):
        return []
    rows = conn.execute("SELECT a.posting_id,a.run_key,a.invocation_id,a.reason,a.at FROM agentic_activity a "
                        "JOIN (SELECT posting_id,MAX(id) AS latest FROM agentic_activity WHERE event='finished' "
                        "GROUP BY posting_id) newest ON newest.latest=a.id ORDER BY a.id").fetchall()
    failures = [row for row in rows if row[3] in FAILURE_REASONS]
    if not failures:
        return []
    ensure(conn)
    added = []
    for posting_id, run_key, invocation_id, reason, finished_at in failures:
        if is_paused(conn, posting_id):
            continue
        historical_id = 'historical:' + str(invocation_id or run_key)
        observed = conn.execute('SELECT 1 FROM agentic_incidents WHERE posting_id=? AND '
                                '(run_id IN (?,?,?) OR created_at>=?) LIMIT 1',
                                (posting_id, historical_id, str(invocation_id or ''), str(run_key or ''), finished_at)).fetchone()
        if observed:
            continue
        row = report(conn, posting_id=posting_id, run_id=historical_id, reason=reason,
                     phase=None, notify_immediately=False)
        if row is not None and row['state'] == 'paused':
            added.append(row)
    if added:
        flush_notifications(conn)
    return added
