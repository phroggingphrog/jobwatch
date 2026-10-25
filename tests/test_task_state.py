"""Hermes-style chat: plain task state, honest unknown outcome, Stop (owner 2026-10-25)."""
import json
import time

import pytest

from jobwatch import db as dbm, users
from jobwatch.apply import submit_confirm as sc
from pipeline.agentic import task_state as ts


def _conn(tmp_path):
    return dbm.connect(tmp_path / 'j.db')


def _selection(conn, ident, state, posting=1):
    conn.execute('INSERT INTO selection_requests(id,person,request_key,input_hash,manifest_json,state,created_at,updated_at) '
                 'VALUES(?,?,?,?,?,?,?,?)', (ident, users.current(), ident, 'h', json.dumps({'request': {'posting_ids': [posting]}}),
                                             state, 't', 't'))
    conn.commit()


def _queue(conn, approval='a', posting=1):
    return sc.queue(conn, posting_id=posting, application_id=7, confirm_digest='d', approval=approval, now=time.time())['request_id']


def test_task_card_keeps_draft_ready_apart_from_submitted(tmp_path):
    conn = _conn(tmp_path)
    assert ts.task_card(conn, 1)['state'] == 'not started'
    _selection(conn, 's1', 'running')
    assert ts.task_card(conn, 1)['state'] == 'drafting'
    conn.execute("UPDATE selection_requests SET state='completed' WHERE id='s1'"); conn.commit()
    assert ts.task_card(conn, 1)['state'] == 'draft ready'
    rid = _queue(conn)
    assert ts.task_card(conn, 1)['state'] == 'awaiting browser press'
    sc.settle(conn, rid, 'pressed')
    assert ts.task_card(conn, 1)['state'] == 'executing'
    sc.verdict(conn, 7, 'confident')
    assert ts.task_card(conn, 1)['state'] == 'submitted'


def test_unsure_outcome_is_stated_and_blocks_any_retry(tmp_path):
    conn = _conn(tmp_path)
    rid = _queue(conn)
    sc.settle(conn, rid, 'pressed')
    sc.verdict(conn, 7, 'unsure')
    card = ts.task_card(conn, 1)
    assert card['state'] == 'outcome unknown' and 'retries are paused' in card['message']
    assert ts.retry_blocked(conn, 1) == 'submit_outcome_unknown'
    assert ts.retry_blocked(conn, 2) is None


def test_stop_cancels_unpressed_work_and_reports_what_it_cannot_undo(tmp_path):
    conn = _conn(tmp_path)
    _selection(conn, 'done', 'completed'); _selection(conn, 'wait', 'queued')
    rid = _queue(conn, 'a1')
    report = ts.stop(conn, 1)
    assert report['done'] == ['preparation done'] and 'preparation wait' in report['cancelled'] and f'submit request {rid}' in report['cancelled']
    assert sc.outcome(conn, 1)['status'] == 'refused' and ts.task_card(conn, 1)['state'] == 'cancelled'
    # a press already in flight cannot be recalled: reported as uncertain, not cancelled
    rid2 = _queue(conn, 'a2')
    sc.settle(conn, rid2, 'pressed')
    assert f'submit request {rid2}' in ts.stop(conn, 1)['uncertain']
