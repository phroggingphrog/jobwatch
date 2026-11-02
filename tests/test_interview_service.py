
from jobwatch.util import model_choice as model_choice
import json

import pytest

from test_interview_inputs import conn
from test_interview_prep import Writer, Reviewer, proposal
from jobwatch import ledger
from jobwatch.candidate.evidence import snapshot_evidence
from jobwatch.config import Config, DEFAULT_CONFIG_DIR, DEFAULT_SETTINGS, _merge
from jobwatch.interview.inputs import InterviewInputs, save_inputs
from jobwatch.interview.prep import generate, load_report

AD='Reconcile accounts using SQL. '+('Assist the accounting team with accurate ledgers. '*30)


@pytest.fixture
def world(conn,tmp_path,monkeypatch):
    root=tmp_path/'profile';root.mkdir();(root/'cv.md').write_text('# Synthetic Candidate\n\n## Skills\n- Reconciled ledgers.\n')
    monkeypatch.setenv('JOBWATCH_PROFILE_DIR',str(root))
    bundle=snapshot_evidence(root)
    conn.execute("UPDATE postings SET company='Example' WHERE id=1")
    conn.execute("INSERT INTO ad_text(posting_id,text,source,fetched_at) VALUES(1,?,'cached','2026-10-11')",(AD,));conn.commit()
    config=Config(config_dir=DEFAULT_CONFIG_DIR,settings=_merge(DEFAULT_SETTINGS,{'pipeline':{'agentic':{'enabled':True,'worker_model':'claude/sonnet','reviewer_model':'openai/sol','research_enabled':False}}}),rules={},searches={},feeds={},employers=[])
    return conn,bundle,config


def writer_for(bundle):return Writer(bundle,payload=proposal(bundle,AD))


def test_ready_prep_without_application_is_durable_and_cached(world):
    conn,bundle,config=world;writer=writer_for(bundle)
    result=generate(conn,1,config,bundle=bundle,writer=writer,reviewer=Reviewer())
    assert result['status']=='ready'
    assert conn.execute('select count(*) from applications').fetchone()[0]==0
    generate(conn,1,config,bundle=bundle,writer=writer,reviewer=Reviewer())
    assert len(writer.calls)==2
    before=ledger.snapshot(conn);ledger.reindex(conn)
    assert ledger.snapshot(conn)==before
    assert load_report(conn,1,config,bundle=bundle)['report']==result['report']


def test_changed_owner_inputs_hide_prior_report(world):
    conn,bundle,config=world
    generate(conn,1,config,bundle=bundle,writer=writer_for(bundle),reviewer=Reviewer())
    save_inputs(conn,1,InterviewInputs(invite='Changed invite'),expected_revision=0)
    assert load_report(conn,1,config,bundle=bundle)['status']=='missing'


def test_unknown_dispatch_is_not_automatically_retried_and_charge_survives_recovery(world):
    conn,bundle,config=world
    class Failed:
        base_url = model_choice.SERVER_URL
        calls=0
        def chat_once(self,*a,**kw):
            self.calls+=1
            raise RuntimeError('private provider message')
    failed=Failed()
    assert generate(conn,1,config,bundle=bundle,writer=failed,reviewer=Reviewer())['status']=='held'
    generate(conn,1,config,bundle=bundle,writer=failed,reviewer=Reviewer())
    assert failed.calls==1
    value=json.loads(conn.execute('select detail_json from interview_runs').fetchone()[0])
    charge=value['checkpoint']['job_charged'];assert charge>12000
    assert 'private provider message' not in json.dumps(value)
    assert generate(conn,1,config,bundle=bundle,writer=writer_for(bundle),reviewer=Reviewer(),retry=True)['status']=='ready'
    after=json.loads(conn.execute('select detail_json from interview_runs').fetchone()[0])
    assert after['checkpoint']['job_charged']==charge+60
    assert after['checkpoint']['reservations'][0]==value['checkpoint']['reservations'][0]


def test_changed_approved_evidence_during_generation_prevents_publication(world, monkeypatch, tmp_path):
    conn,bundle,config=world
    from jobwatch.interview import prep
    from jobwatch.candidate.evidence import snapshot_evidence
    changed_root = tmp_path / 'changed-approved-evidence'
    changed_root.mkdir()
    (changed_root / 'cv.md').write_text('# Synthetic\n\n## Skills\n- Prepared reports.\n')
    changed_bundle = snapshot_evidence(changed_root)
    calls = []
    def approved_evidence(person):
        calls.append(person)
        return bundle if len(calls) == 1 else changed_bundle
    monkeypatch.setattr(prep.approved, 'evidence', approved_evidence)
    class Changed(Writer):
        base_url = model_choice.SERVER_URL
        def chat_once(self,*a,**kw):
            result=super().chat_once(*a,**kw)
            return result
    assert generate(conn,1,config,writer=Changed(bundle,payload=proposal(bundle,AD)),reviewer=Reviewer())['status']=='held'
    assert load_report(conn,1,config)['status']=='missing'


def test_late_worker_cannot_settle_or_publish_after_takeover(world):
    from pipeline.agentic.contracts import AgenticError
    conn,bundle,config=world
    replacement=writer_for(bundle)
    class Late(Writer):
        base_url = model_choice.SERVER_URL
        def chat_once(self,*a,**kw):
            result=super().chat_once(*a,**kw)
            row=conn.execute('select * from interview_runs').fetchone()
            value=json.loads(row['detail_json']);value['deadline']=1.0
            ledger.upsert(conn,'applications','interview_runs',{'run_key':row['run_key'],'detail_json':json.dumps(value)})
            assert generate(conn,1,config,bundle=bundle,writer=replacement,reviewer=Reviewer(),retry=True)['status']=='ready'
            return result
    late=Late(bundle,payload=proposal(bundle,AD))
    with pytest.raises(AgenticError,match='interview_attempt_replaced'):
        generate(conn,1,config,bundle=bundle,writer=late,reviewer=Reviewer())
    assert len(late.calls)==1 and load_report(conn,1,config,bundle=bundle)['status']=='ready'
    value=json.loads(conn.execute('select detail_json from interview_runs').fetchone()[0])
    assert value['checkpoint']['reservations'][0]['state']=='dispatched'
    assert value['checkpoint']['job_charged']>12000


def test_auto_trigger_requires_interview_current_evaluation_and_no_attempt(world,monkeypatch):
    from jobwatch.interview.prep import should_prepare_after_interview
    conn,bundle,config=world
    from jobwatch.interview import prep
    monkeypatch.setattr(prep.approved, 'evidence', lambda person: bundle)
    context={'application':{'status':'interview'},'evaluation':{'global_score':4.0}}
    monkeypatch.setattr('jobwatch.interview.prep.capture',lambda *a:(context,AD,'a'*64))
    assert should_prepare_after_interview(conn,1,config)
    context['evaluation']['global_score']=3.9
    assert should_prepare_after_interview(conn,1,config)  # career score cannot veto the person's interview transition
    context['evaluation']['global_score']=4.0;context['application']['status']='applied'
    assert not should_prepare_after_interview(conn,1,config)
    context['application']['status']='interview'
    ledger.upsert(conn,'applications','interview_runs',{'run_key':'a'*64,'posting_id':1,'detail_json':'{"status":"held"}'})
    assert not should_prepare_after_interview(conn,1,config)


def test_missing_evaluation_does_not_start_automatic_work(world):
    from jobwatch.interview.prep import should_prepare_after_interview
    conn,bundle,config=world
    assert not should_prepare_after_interview(conn,1,config)


def test_stricter_batch_limit_prevents_dispatch(world):
    conn,bundle,config=world;writer=writer_for(bundle)
    config.settings['pipeline']['agentic']['batch_token_ceiling']=1
    result=generate(conn,1,config,bundle=bundle,writer=writer,reviewer=Reviewer())
    assert result['status']=='held' and not writer.calls


def test_queued_request_is_durable_and_only_undispatched_work_recovers(world, monkeypatch):
    from jobwatch.interview.prep import enqueue, queued_posting_ids, is_queued
    conn,bundle,config=world
    from jobwatch.interview import prep
    monkeypatch.setattr(prep.approved, 'evidence', lambda person: bundle)
    assert enqueue(conn,1,config) and is_queued(conn,1,config)
    before=ledger.snapshot(conn);ledger.reindex(conn)
    assert ledger.snapshot(conn)==before and queued_posting_ids(conn,config)==(1,)
    writer=writer_for(bundle)
    assert generate(conn,1,config,bundle=bundle,writer=writer,reviewer=Reviewer(),queued_only=True)['status']=='ready'
    assert queued_posting_ids(conn,config)==() and not enqueue(conn,1,config)
    assert not is_queued(conn,1,config)


def test_source_change_before_worker_never_dispatches_unrequested_snapshot(world, monkeypatch):
    from jobwatch.interview.prep import enqueue, queued_posting_ids
    conn,bundle,config=world
    from jobwatch.interview import prep
    monkeypatch.setattr(prep.approved, 'evidence', lambda person: bundle)
    enqueue(conn,1,config)
    save_inputs(conn,1,InterviewInputs(invite='Changed before dispatch'),expected_revision=0)
    writer=writer_for(bundle)
    assert generate(conn,1,config,bundle=bundle,writer=writer,reviewer=Reviewer(),queued_only=True)['status']=='missing'
    assert not writer.calls and queued_posting_ids(conn,config)==()
    assert json.loads(conn.execute('select detail_json from interview_runs').fetchone()[0])['status']=='held'


def test_committed_interview_transition_is_recovered_without_repeating_after_input_change(world,monkeypatch):
    from jobwatch.interview.prep import queued_posting_ids
    conn,bundle,config=world
    ledger.upsert(conn,'applications','applications',{'posting_id':1,'status':'interview','created_at':'2026-10-11','updated_at':'2026-10-11'})
    context={'application':{'status':'interview','interview_event_id':7},'evaluation':{'global_score':4.0}}
    identity=['a'*64]
    monkeypatch.setattr('jobwatch.interview.prep.capture',lambda *a:(context,AD,identity[0]))
    from jobwatch.interview import prep
    monkeypatch.setattr(prep.approved, 'evidence', lambda person: bundle)
    assert queued_posting_ids(conn,config)==(1,)
    row=conn.execute('select * from interview_runs').fetchone()
    value=json.loads(row['detail_json']);assert value['trigger_event_id']==7
    value['status']='held'
    ledger.upsert(conn,'applications','interview_runs',{'run_key':row['run_key'],'detail_json':json.dumps(value)})
    assert queued_posting_ids(conn,config)==()
    identity[0]='b'*64
    assert queued_posting_ids(conn,config)==()
    context['application']['interview_event_id']=8
    assert queued_posting_ids(conn,config)==(1,)
