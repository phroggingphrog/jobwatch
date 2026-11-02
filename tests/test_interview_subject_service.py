
from jobwatch.util import model_choice as model_choice
import json
import pytest
from test_interview_inputs import conn
from test_interview_service import world,AD,writer_for
from test_interview_prep import Reviewer
from jobwatch import ledger
from jobwatch.interview.ad import InterviewAd
from jobwatch.interview.inputs import InterviewInputs
from jobwatch.interview.subjects import create_subject, save_subject_inputs
from jobwatch.interview.prep import generate, load_report, enqueue, queued_subject_ids


def subject(conn):return create_subject(conn,InterviewAd('https://example.test/other','https://example.test/other','Analyst','Example',AD,'2026-10-11T00:00:00+00:00','browser'))

def test_subject_uses_existing_runtime_without_tracker_changes(world):
    conn,bundle,config=world;sid=subject(conn);writer=writer_for(bundle)
    before=conn.execute('SELECT COUNT(*) FROM postings').fetchone()[0]
    result=generate(conn,sid,config,bundle=bundle,writer=writer,reviewer=Reviewer())
    assert result['status']=='ready'
    assert 'browser' in next(s.text for s in result['report'].sources if s.source_id=='context')
    assert generate(conn,sid,config,bundle=bundle,writer=writer,reviewer=Reviewer())['status']=='ready'
    assert len(writer.calls)==2
    assert conn.execute('SELECT COUNT(*) FROM postings').fetchone()[0]==before
    assert conn.execute('SELECT COUNT(*) FROM applications').fetchone()[0]==0
    assert conn.execute('SELECT COUNT(*) FROM interview_runs').fetchone()[0]==0
    snapshot=ledger.snapshot(conn);ledger.reindex(conn);assert ledger.snapshot(conn)==snapshot
    assert load_report(conn,sid,config,bundle=bundle)['status']=='ready'


def test_subject_queue_durable_and_changed_notes_do_not_auto_dispatch(world, monkeypatch):
    conn,bundle,config=world;sid=subject(conn)
    from jobwatch.interview import prep
    monkeypatch.setattr(prep.approved, 'evidence', lambda person: bundle)
    assert enqueue(conn,sid,config)
    assert queued_subject_ids(conn,config)==(sid,)
    save_subject_inputs(conn,sid,InterviewInputs(invite='Changed'),expected_revision=1)
    assert queued_subject_ids(conn,config)==()
    writer=writer_for(bundle)
    assert generate(conn,sid,config,bundle=bundle,writer=writer,reviewer=Reviewer(),queued_only=True)['status']=='missing'
    assert not writer.calls
    assert json.loads(conn.execute('SELECT detail_json FROM interview_subject_runs').fetchone()[0])['status']=='held'


def test_subject_unknown_call_is_not_retried_and_budget_stays_reserved(world):
    conn,bundle,config=world;sid=subject(conn)
    class Failed:
        base_url = model_choice.SERVER_URL
        calls=0
        def chat_once(self,*args,**kw):self.calls+=1;raise RuntimeError('synthetic error')
    failed=Failed()
    generate(conn,sid,config,bundle=bundle,writer=failed,reviewer=Reviewer())
    before=json.loads(conn.execute('SELECT detail_json FROM interview_subject_runs').fetchone()[0])['checkpoint']
    generate(conn,sid,config,bundle=bundle,writer=failed,reviewer=Reviewer())
    after=json.loads(conn.execute('SELECT detail_json FROM interview_subject_runs').fetchone()[0])['checkpoint']
    assert failed.calls==1 and before==after


def test_matching_report_requires_current_ad_and_profile(world,monkeypatch):
    from test_agentic_contracts import _evaluation_base,key
    from pipeline.agentic.contracts import AgenticEvaluation,RequirementSet,Requirement,RequirementMatch,SourceCitation
    from jobwatch.candidate.contracts import content_hash
    from jobwatch.interview.prep import matching_posting
    conn,bundle,config=world;h=content_hash(AD.encode())
    reqs=RequirementSet(ad_hash=h,requirements=(Requirement(id='r1',text='SQL',tier='stated',importance='high',
        jd_signal=SourceCitation(source_id='ad',content_hash=h,quote='SQL')),))
    base=_evaluation_base(reqs);base['run_key']=key().model_copy(update={'posting_id':1,'ad_hash':h,'evidence_hash':bundle.bundle_hash})
    evaluation=AgenticEvaluation(**base,matches=(RequirementMatch(requirement_id='r1',match='partial',evidence=(),risk='gap',mitigation='practice'),))
    monkeypatch.setattr('jobwatch.interview.prep.latest_result',lambda *a:{'evaluation':evaluation.model_dump(mode='json')})
    url=conn.execute('SELECT url FROM postings WHERE id=1').fetchone()[0]
    assert matching_posting(conn,url,config,bundle=bundle)==1
    assert matching_posting(conn,'https://other.example/job',config,bundle=bundle,title='Synthetic role',company='Example')==1
    conn.execute('UPDATE ad_text SET text=? WHERE posting_id=1',(AD+' Changed.',));conn.commit()
    assert matching_posting(conn,url,config,bundle=bundle) is None
    conn.execute('UPDATE ad_text SET text=? WHERE posting_id=1',(AD,));conn.commit()
    changed=evaluation.model_copy(update={'run_key':evaluation.run_key.model_copy(update={'evidence_hash':'f'*64})})
    monkeypatch.setattr('jobwatch.interview.prep.latest_result',lambda *a:{'evaluation':changed.model_dump(mode='json')})
    assert matching_posting(conn,url,config,bundle=bundle) is None
