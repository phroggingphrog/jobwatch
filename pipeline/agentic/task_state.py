"""Plain task state and Stop for one posting (owner 2026-10-25: Hermes-style chat).

Maps the preparation selection and the chat-approved Submit request to one label so chat never calls a
draft "submitted" and never hides an unknown outcome. Stop only removes authority; it needs no approval.
"""
from __future__ import annotations

import json
import sqlite3

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
