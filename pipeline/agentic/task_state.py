"""Plain task state and Stop for one posting (owner 2026-10-25: Hermes-style chat).

Maps the preparation selection and the chat-approved Submit request to one label so chat never calls a
draft "submitted" and never hides an unknown outcome. Stop only removes authority; it needs no approval.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from jobwatch import users
from jobwatch.apply import submit_confirm

SELECTION_LABEL = {'pending_dispatch': 'queued', 'queued': 'queued', 'running': 'drafting', 'completed': 'draft ready',
                   'failed': 'failed', 'cancelled': 'cancelled'}
SUBMIT_LABEL = {'pending': 'awaiting browser press', 'pressed': 'executing', 'submitted': 'submitted', 'unsure': 'outcome unknown',
                'refused': 'failed', 'expired': 'expired'}
UNKNOWN_MESSAGE = 'Outcome unknown; retries are paused. Check the employer site or your email before anything is sent again.'


def _selections(conn: sqlite3.Connection, posting_id: int) -> list[dict]:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='selection_requests'").fetchone():
        return []
    rows = conn.execute('SELECT id,state,manifest_json FROM selection_requests WHERE person=? ORDER BY created_at,id',
                        (users.current(),)).fetchall()
    return [{'id': r[0], 'state': r[1]} for r in rows if posting_id in json.loads(r[2])['request']['posting_ids']]


def task_card(conn: sqlite3.Connection, posting_id: int) -> dict:
    """One label for the posting; a submit request outranks the preparation that came before it."""
    selections = _selections(conn, posting_id)
    outcome = submit_confirm.outcome(conn, posting_id) if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='submit_requests'").fetchone() else None
    if outcome:
        card = {'posting_id': posting_id, 'state': SUBMIT_LABEL.get(outcome['status'], outcome['status']), 'submit': outcome}
        if outcome.get('reason') == 'stopped_by_owner':
            card['state'] = 'cancelled'
        if outcome['status'] == 'unsure':
            card['message'] = UNKNOWN_MESSAGE
        return card
    if selections:
        last = selections[-1]
        return {'posting_id': posting_id, 'state': SELECTION_LABEL.get(last['state'], last['state']), 'selection_id': last['id']}
    return {'posting_id': posting_id, 'state': 'not started'}


# needs_info stays 0 until task_card has a state for an open question to the owner.
COUNT_BUCKET = {'draft ready': 'needs_you', 'awaiting browser press': 'needs_you', 'failed': 'needs_you', 'expired': 'needs_you',
                'outcome unknown': 'outcome_unknown', 'submitted': 'submitted'}


def _epoch(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except ValueError:
        return 0.0


def _has(conn: sqlite3.Connection, table: str) -> bool:
    return bool(conn.execute('SELECT 1 FROM sqlite_master WHERE name=?', (table,)).fetchone())


def jobs_overview(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """One row per posting with application, preparation or submit activity, newest first. Read-only."""
    seen: dict[int, float] = {}

    def touch(posting_id, at):
        seen[posting_id] = max(seen.get(posting_id, 0.0), _epoch(at))
    if _has(conn, 'applications'):
        for pid, at in conn.execute('SELECT posting_id, updated_at FROM applications'):
            touch(pid, at)
    if _has(conn, 'selection_requests'):
        for manifest, at in conn.execute('SELECT manifest_json, updated_at FROM selection_requests WHERE person=?', (users.current(),)):
            for pid in json.loads(manifest)['request']['posting_ids']:
                touch(pid, at)
    if _has(conn, 'submit_requests'):
        for pid, at in conn.execute('SELECT posting_id, updated_at FROM submit_requests'):
            touch(pid, at)
    rows = []
    for pid in sorted(seen, key=lambda p: (seen[p], p), reverse=True)[:max(limit, 0)]:
        post = conn.execute('SELECT company, title FROM postings WHERE id=?', (pid,)).fetchone() or (None, None)
        score = conn.execute('SELECT score FROM ad_reviews WHERE posting_id=?', (pid,)).fetchone() if _has(conn, 'ad_reviews') else None
        card = task_card(conn, pid)
        rows.append({'posting_id': pid, 'employer': post[0], 'title': post[1], 'score': score[0] if score else None,
                     'state': card['state'], 'detail': card.get('message') or (card.get('submit') or {}).get('reason') or ''})
    return rows


def overview_counts(rows: list[dict]) -> dict:
    counts = {'needs_you': 0, 'needs_info': 0, 'outcome_unknown': 0, 'submitted': 0}
    for row in rows:
        if row['state'] in COUNT_BUCKET:
            counts[COUNT_BUCKET[row['state']]] += 1
    return counts


def retry_blocked(conn: sqlite3.Connection, posting_id: int) -> str | None:
    """A Submit that may already have gone through (or is still queued) is never queued again automatically."""
    card = task_card(conn, posting_id)
    status = (card.get('submit') or {}).get('status')
    return {'unsure': 'submit_outcome_unknown', 'pressed': 'submit_outcome_unknown', 'pending': 'submit_already_queued'}.get(status)


def stop(conn: sqlite3.Connection, posting_id: int) -> dict:
    """Cancel unpressed work for a posting and say what is done, still in flight, or uncertain."""
    from pipeline.agentic import selection
    report = {'posting_id': posting_id, 'done': [], 'cancelled': [], 'in_flight': [], 'uncertain': []}
    for item in _selections(conn, posting_id):
        if item['state'] == 'completed':
            report['done'].append(f"preparation {item['id']}")
        elif item['state'] in ('failed', 'cancelled'):
            continue
        else:
            after = selection.cancel(conn, item['id'], actor='person')
            # a running preparation was asked to stop; the worker may finish its current step
            (report['in_flight'] if item['state'] == 'running' else report['cancelled']).append(f"preparation {item['id']}")
            report.setdefault('selection_state_' + str(item['id']), after['state'])
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='submit_requests'").fetchone():
        for rid, status in conn.execute("SELECT id,status FROM submit_requests WHERE posting_id=? AND status IN ('pending','pressed','unsure','submitted')",
                                        (posting_id,)).fetchall():
            if status == 'pending':
                submit_confirm.settle(conn, rid, 'refused', 'stopped_by_owner')    # atomic: only if still pending
                now = conn.execute('SELECT status FROM submit_requests WHERE id=?', (rid,)).fetchone()[0]
                (report['cancelled'] if now == 'refused' else report['uncertain']).append(f'submit request {rid}')
            elif status == 'submitted':
                report['done'].append(f'submit request {rid}')
            else:
                report['uncertain'].append(f'submit request {rid}')
    return report
