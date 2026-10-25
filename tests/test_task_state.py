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


def _posting(conn, ident, company='Acme', title='Analyst'):
    conn.execute('INSERT INTO postings(id,source,source_id,url,url_hash,dedupe_key,title,company,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                 (ident, 's', str(ident), f'u{ident}', f'h{ident}', f'd{ident}', title, company, 't', 't'))
    conn.commit()


def test_jobs_overview_newest_first_with_card_states_and_counts(tmp_path):
    conn = _conn(tmp_path)
    tables = lambda: sorted(r[0] for r in conn.execute('SELECT name FROM sqlite_master'))
    before = tables()
    assert ts.jobs_overview(conn) == [] and tables() == before and ts.overview_counts([]) == {'needs_you': 0, 'needs_info': 0, 'outcome_unknown': 0, 'submitted': 0}
    for i in (1, 2, 3):
        _posting(conn, i, f'Co{i}')
    _selection(conn, 's1', 'completed', posting=1)
    conn.execute("UPDATE selection_requests SET updated_at='2026-10-01T00:00:00'"); conn.commit()
    conn.execute("INSERT INTO ad_reviews(posting_id,content_hash,prompt_version,model,verdict,reviewed_at,score) VALUES(1,'c',1,'m','show','t',4.5)")
    rid = sc.queue(conn, posting_id=2, application_id=8, confirm_digest='d', approval='b', now=time.time())['request_id']
    sc.settle(conn, rid, 'pressed'); sc.verdict(conn, 8, 'unsure')
    rid = sc.queue(conn, posting_id=3, application_id=9, confirm_digest='d', approval='c', now=time.time() + 5)['request_id']
    sc.settle(conn, rid, 'pressed'); sc.verdict(conn, 9, 'confident')
    rows = ts.jobs_overview(conn)
    assert [r['posting_id'] for r in rows[:2]] == [3, 2] and rows[-1]['posting_id'] == 1
    assert all(r['state'] == ts.task_card(conn, r['posting_id'])['state'] for r in rows)
    assert rows[-1]['state'] == 'draft ready' and rows[-1]['score'] == 4.5 and rows[-1]['employer'] == 'Co1'
    assert 'retries are paused' in rows[1]['detail']
    assert ts.overview_counts(rows) == {'needs_you': 1, 'needs_info': 0, 'outcome_unknown': 1, 'submitted': 1}
    assert len(ts.jobs_overview(conn, limit=2)) == 2
