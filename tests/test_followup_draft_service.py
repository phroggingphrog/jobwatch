
from jobwatch import model_choice
from datetime import timedelta
import json

import pytest

from test_followup_events import conn, NOW, record, confirm_application
from test_followup_draft import Writer, Reviewer
from jobwatch import ledger
from jobwatch.candidate.evidence import snapshot_evidence
from jobwatch.config import Config, DEFAULT_CONFIG_DIR, DEFAULT_SETTINGS, _merge
from jobwatch.followup_drafts import generate, load_draft
from jobwatch.followup_events import application_cadence
from pipeline.agentic.contracts import AgenticError


@pytest.fixture
def setup(conn,tmp_path,monkeypatch):
    root=tmp_path/'profile';root.mkdir();(root/'cv.md').write_text('# Synthetic Example\n\n## Skills\n- Reconciled ledgers.\n')
    monkeypatch.setenv('JOBWATCH_PROFILE_DIR',str(root))
    bundle=snapshot_evidence(root)
    confirm_application(conn)
    conn.execute("INSERT INTO ad_text(posting_id,text,source,fetched_at) VALUES(1,?,'cached',?)",('Example seeks an accounts assistant. '+('Reconcile ledgers accurately. '*30),NOW.isoformat()));conn.commit()
    config=Config(config_dir=DEFAULT_CONFIG_DIR,settings=_merge(DEFAULT_SETTINGS,{'pipeline':{'agentic':{'enabled':True,'worker_model':'claude/sonnet','reviewer_model':'openai/sol'}}}),rules={},searches={},feeds={},employers=[])
    return conn,bundle,config


def test_ready_draft_is_private_durable_cached_and_never_sent(setup):
    conn,bundle,config=setup;writer=Writer(bundle);reviewer=Reviewer()
    result=generate(conn,1,config,bundle=bundle,writer=writer,reviewer=reviewer,now=NOW)
    assert result['status']=='ready'
    assert application_cadence(conn,1,now=NOW).sent_count==0
    result2=generate(conn,1,config,bundle=bundle,writer=writer,reviewer=reviewer,now=NOW)
    assert result2['draft']==result['draft'] and len(writer.calls)==2
    payload=json.loads(conn.execute("select detail_json from application_events where kind='followup_draft'").fetchone()[0])
    assert payload['checkpoint']['job_charged']==60
    before=ledger.snapshot(conn);ledger.reindex(conn)
    assert ledger.snapshot(conn)==before
    assert load_draft(conn,1,bundle=bundle,now=NOW)['status']=='ready'


def test_new_owner_history_and_changed_profile_invalidate_old_draft(setup):
    conn,bundle,config=setup
    generate(conn,1,config,bundle=bundle,writer=Writer(bundle),reviewer=Reviewer(),now=NOW)
    record(conn,'response','new-reply',occurred_at=NOW)
    assert load_draft(conn,1,bundle=bundle,now=NOW)['status']=='missing'


def test_terminal_and_not_due_state_refuse_before_any_model_call(setup):
    conn,bundle,config=setup;writer=Writer(bundle)
    record(conn,'sent','sent1',occurred_at=NOW,channel='email')
    with pytest.raises(AgenticError,match='followup_not_due'):
        generate(conn,1,config,bundle=bundle,writer=writer,reviewer=Reviewer(),now=NOW)
    assert not writer.calls


def test_unknown_failed_dispatch_retains_reservation_and_does_not_auto_retry(setup):
    conn,bundle,config=setup
    class Failed:
        base_url = model_choice.SERVER_URL
        calls=0
        def chat_once(self,*a,**kw):
            self.calls+=1
            raise RuntimeError('private-upstream-message-must-not-leak')
    failed=Failed()
    result=generate(conn,1,config,bundle=bundle,writer=failed,reviewer=Reviewer(),now=NOW)
    assert result['status']=='held'
    row=conn.execute("select detail_json from application_events where kind='followup_draft'").fetchone()[0]
    assert 'private-upstream-message' not in row
    cp=json.loads(row)['checkpoint'];assert cp['job_charged']>12000
    generate(conn,1,config,bundle=bundle,writer=failed,reviewer=Reviewer(),now=NOW)
    assert failed.calls==1


def test_profile_change_during_generation_prevents_ready_publication(setup):
    from jobwatch.apply.paths import profile_dir
    conn,bundle,config=setup
    class ChangingWriter(Writer):
        base_url = model_choice.SERVER_URL
        def chat_once(self,*args,**kwargs):
            result=super().chat_once(*args,**kwargs)
            if len(self.calls)==2:
                (profile_dir()/'cv.md').write_text('# Synthetic Example\n\n## Skills\n- Prepared bank reconciliations.\n')
            return result
    result=generate(conn,1,config,writer=ChangingWriter(bundle),reviewer=Reviewer(),now=NOW)
    assert result['status']=='held' and result['reason']=='followup_snapshot_changed'


def test_explicit_retry_preserves_unknown_charges_and_original_ceiling(setup):
    conn,bundle,config=setup
    class Failed:
        base_url = model_choice.SERVER_URL
        def chat_once(self,*a,**kw): raise RuntimeError('private failure')
    generate(conn,1,config,bundle=bundle,writer=Failed(),reviewer=Reviewer(),now=NOW)
    old=json.loads(conn.execute("select detail_json from application_events where kind='followup_draft'").fetchone()[0])
    writer=Writer(bundle)
    result=generate(conn,1,config,bundle=bundle,writer=writer,reviewer=Reviewer(),now=NOW,retry=True)
    assert result['status']=='ready'
    new=json.loads(conn.execute("select detail_json from application_events where kind='followup_draft'").fetchone()[0])
    assert new['checkpoint']['job_charged']==old['checkpoint']['job_charged']+60
    assert new['checkpoint']['job_token_ceiling']==old['checkpoint']['job_token_ceiling']
    assert new['checkpoint']['reservations'][:1]==old['checkpoint']['reservations'][:1]
    assert new['retry_count']==1
    assert conn.execute("select count(*) from application_events where kind='followup_draft'").fetchone()[0]==1
    generate(conn,1,config,bundle=bundle,writer=writer,reviewer=Reviewer(),now=NOW,retry=True)
    assert len(writer.calls)==2


def test_explicit_retry_keeps_failure_limit_and_cannot_dispatch_forever(setup):
    conn,bundle,config=setup
    class Failed:
        base_url = model_choice.SERVER_URL
        calls=0
        def chat_once(self,*a,**kw):
            self.calls+=1
            raise RuntimeError('private failure')
    failed=Failed()
    from pipeline.agentic.runtime import MAX_FAILED_ATTEMPTS
    for attempt in range(MAX_FAILED_ATTEMPTS+2):
        result=generate(conn,1,config,bundle=bundle,writer=failed,reviewer=Reviewer(),now=NOW,retry=attempt>0)
        assert result['status']=='held'
    assert failed.calls==MAX_FAILED_ATTEMPTS


def test_expired_attempt_renews_time_but_preserves_budget(setup):
    conn,bundle,config=setup
    class Failed:
        base_url = model_choice.SERVER_URL
        def chat_once(self,*a,**kw):raise RuntimeError('private failure')
    generate(conn,1,config,bundle=bundle,writer=Failed(),reviewer=Reviewer(),now=NOW)
    row=conn.execute("select * from application_events where kind='followup_draft'").fetchone()
    value=json.loads(row['detail_json']);old_charge=value['checkpoint']['job_charged']
    value.update(status='running',deadline=1.0)
    value['checkpoint'].update(job_deadline=1.0,batch_deadline=1.0)
    ledger.upsert(conn,'applications','application_events',{'id':row['id'],'detail_json':json.dumps(value)})
    writer=Writer(bundle)
    assert generate(conn,1,config,bundle=bundle,writer=writer,reviewer=Reviewer(),now=NOW)['status']=='held'
    assert not writer.calls
    assert generate(conn,1,config,bundle=bundle,writer=writer,reviewer=Reviewer(),now=NOW,retry=True)['status']=='ready'
    new=json.loads(conn.execute("select detail_json from application_events where id=?",(row['id'],)).fetchone()[0])
    assert new['checkpoint']['job_charged']==old_charge+60
    assert new['checkpoint']['job_deadline']>1


def test_late_worker_cannot_overwrite_explicit_takeover(setup):
    conn,bundle,config=setup
    replacement=Writer(bundle)
    class LateWriter(Writer):
        base_url = model_choice.SERVER_URL
        def chat_once(self,*args,**kwargs):
            result=super().chat_once(*args,**kwargs)
            row=conn.execute("select * from application_events where kind='followup_draft'").fetchone()
            value=json.loads(row['detail_json']);value['deadline']=1.0
            ledger.upsert(conn,'applications','application_events',{'id':row['id'],'detail_json':json.dumps(value)})
            assert generate(conn,1,config,bundle=bundle,writer=replacement,reviewer=Reviewer(),now=NOW,retry=True)['status']=='ready'
            return result
    late=LateWriter(bundle)
    with pytest.raises(AgenticError,match='followup_attempt_replaced'):
        generate(conn,1,config,bundle=bundle,writer=late,reviewer=Reviewer(),now=NOW)
    assert len(late.calls)==1 and len(replacement.calls)==2
    assert load_draft(conn,1,bundle=bundle,now=NOW)['status']=='ready'
    value=json.loads(conn.execute("select detail_json from application_events where kind='followup_draft'").fetchone()[0])
    assert value['checkpoint']['reservations'][0]['state']=='dispatched'
    assert value['checkpoint']['job_charged']>12000


def test_stricter_batch_limit_prevents_dispatch(setup):
    conn,bundle,config=setup;writer=Writer(bundle)
    config.settings['pipeline']['agentic']['batch_token_ceiling']=1
    result=generate(conn,1,config,bundle=bundle,writer=writer,reviewer=Reviewer(),now=NOW)
    assert result['status']=='held' and not writer.calls
