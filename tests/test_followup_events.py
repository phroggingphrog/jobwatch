from datetime import UTC, datetime, timedelta
import json

import pytest

from jobwatch import db, ledger
from jobwatch.followup_events import FollowupEventError, record_event, application_cadence

NOW = datetime(2026, 10, 11, 1, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    c = db.connect(tmp_path / 'test.db')
    c.execute("INSERT INTO postings(id,source,source_id,url,url_hash,dedupe_key,title,first_seen_at,last_seen_at) VALUES(1,'test','1','https://example.test/job','h','d','Synthetic role',?,?)", (NOW.isoformat(), NOW.isoformat()))
    c.commit()
    ledger.upsert(c, 'applications', 'applications', {'id':1,'posting_id':1,'status':'applied','created_at':NOW.isoformat(),'updated_at':NOW.isoformat(),'applied_at':(NOW-timedelta(days=14)).isoformat()})
    yield c
    c.close()


def record(c, action, key, **kw):
    return record_event(c, 1, action, operation_id=key, owner_confirmed=True, now=NOW, **kw)


def confirm_application(c):
    record(c, 'applied_confirmed', 'apply1', occurred_at=NOW-timedelta(days=14))


def test_missing_confirmation_and_notes(conn):
    assert application_cadence(conn,1,now=NOW).state == 'unknown'
    confirm_application(conn)
    assert application_cadence(conn,1,now=NOW).state == 'overdue'
    ledger.upsert(conn,'applications','application_events',{'application_id':1,'at':NOW.isoformat(),'kind':'note','actor':'owner','detail_json':'{}'})
    assert application_cadence(conn,1,now=NOW).state == 'overdue'


def test_same_day_reply_then_send_and_send_then_reply(conn):
    confirm_application(conn)
    record(conn,'response','reply1',occurred_at=NOW-timedelta(hours=2))
    record(conn,'sent','sent1',occurred_at=NOW-timedelta(hours=1),channel='email')
    assert application_cadence(conn,1,now=NOW).state == 'waiting'
    record(conn,'response','reply2',occurred_at=NOW-timedelta(minutes=30))
    result=application_cadence(conn,1,now=NOW)
    assert result.state == 'urgent' and result.followups_since_response == 0


def test_idempotency_conflict_owner_confirmation_and_ledger_replay(conn):
    confirm_application(conn)
    before=conn.execute('select count(*) from application_events').fetchone()[0]
    first=record(conn,'sent','send1',occurred_at=NOW,channel='email')
    assert record(conn,'sent','send1',occurred_at=NOW,channel='email')['id']==first['id']
    assert conn.execute('select count(*) from application_events').fetchone()[0]==before+1
    with pytest.raises(FollowupEventError):record(conn,'sent','send1',occurred_at=NOW,channel='phone')
    with pytest.raises(FollowupEventError):record_event(conn,1,'sent',operation_id='bad1',owner_confirmed=False,occurred_at=NOW,now=NOW,channel='email')
    snapshot=ledger.snapshot(conn)
    ledger.reindex(conn)
    assert ledger.snapshot(conn)==snapshot


def test_pin_order_uses_recorded_time_and_terminal_state_suppresses(conn):
    confirm_application(conn)
    record(conn,'sent','send1',occurred_at=NOW-timedelta(days=8),channel='email')
    record(conn,'sent','send2',occurred_at=NOW-timedelta(days=1),channel='email')
    assert application_cadence(conn,1,now=NOW).state=='cold'
    record(conn,'pin','pin1',due_on=NOW.date()+timedelta(days=2))
    assert application_cadence(conn,1,now=NOW).state=='waiting'
    record(conn,'clear_pin','clear1')
    assert application_cadence(conn,1,now=NOW).state=='cold'
    conn.execute("UPDATE applications SET status='rejected' WHERE id=1");conn.commit()
    assert application_cadence(conn,1,now=NOW).state=='inactive'
    with pytest.raises(FollowupEventError):record(conn,'sent','send3',occurred_at=NOW,channel='email')


def test_reject_future_and_naive_events_and_pre_application_dates(conn):
    confirm_application(conn)
    for at in (NOW+timedelta(seconds=1), NOW.replace(tzinfo=None), NOW-timedelta(days=15)):
        with pytest.raises(FollowupEventError):record(conn,'sent','invalid',occurred_at=at,channel='email')


def test_scheduled_interview_requires_completion_event(conn):
    confirm_application(conn)
    conn.execute("UPDATE applications SET status='interview' WHERE id=1");conn.commit()
    assert application_cadence(conn,1,now=NOW).state=='unknown'
    record(conn,'interview_completed','interview1',occurred_at=NOW-timedelta(days=1))
    assert application_cadence(conn,1,now=NOW).kind=='interview_thankyou'


def test_same_day_pin_after_send_remains_active(conn):
    confirm_application(conn)
    record(conn,'sent','send1',occurred_at=NOW-timedelta(hours=1),channel='email')
    record(conn,'pin','pin1',due_on=NOW.date())
    assert application_cadence(conn,1,now=NOW).state=='overdue'


def test_exact_time_pre_submission_send_is_rejected(conn):
    record(conn,'applied_confirmed','apply1',occurred_at=NOW-timedelta(hours=1))
    with pytest.raises(FollowupEventError):
        record(conn,'sent','send1',occurred_at=NOW-timedelta(hours=2),channel='email')


def test_untrusted_jobwatch_events_and_drafts_never_count_as_sent(conn):
    confirm_application(conn)
    for kind in ('followup_sent','followup_draft'):
        ledger.upsert(conn,'applications','application_events',{'application_id':1,'at':NOW.isoformat(),
            'kind':kind,'actor':'jobwatch','detail_json':json.dumps({'owner_confirmed':True,'occurred_at':NOW.isoformat()})})
    assert application_cadence(conn,1,now=NOW).sent_count==0


def test_concurrent_repeated_owner_action_has_one_event(conn):
    from concurrent.futures import ThreadPoolExecutor
    confirm_application(conn)
    path=conn.execute('pragma database_list').fetchone()[2]
    def invoke(_):
        c=db.connect(path)
        try:return record(c,'sent','concurrent1',occurred_at=NOW,channel='email')['id']
        finally:c.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids=list(pool.map(invoke,range(2)))
    assert len(set(ids))==1
    assert application_cadence(conn,1,now=NOW).sent_count==1


def test_application_date_correction_cannot_move_after_confirmed_communication(conn):
    confirm_application(conn)
    record(conn,'sent','sent1',occurred_at=NOW-timedelta(hours=2),channel='email')
    with pytest.raises(FollowupEventError):
        record(conn,'applied_confirmed','correction1',occurred_at=NOW-timedelta(hours=1))
    assert application_cadence(conn,1,now=NOW).sent_count==1
