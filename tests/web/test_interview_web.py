
from jobwatch import model_choice
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from jobwatch import db
from jobwatch.candidate.evidence import snapshot_evidence
from jobwatch.config import Config, DEFAULT_CONFIG_DIR, DEFAULT_SETTINGS, _merge
from jobwatch.web.app import create_app
from test_web import seed, OK
from test_interview_prep import Writer, Reviewer, proposal
from test_interview_service import AD


@pytest.fixture
def prep_client(tmp_path, monkeypatch):
    data=tmp_path/'data'; profile=data/'profile'; profile.mkdir(parents=True)
    (profile/'cv.md').write_text('# Synthetic Candidate\n\n## Skills\n- Reconciled ledgers.\n')
    monkeypatch.setenv('JOBWATCH_DATA_DIR',str(data)); monkeypatch.setenv('JOBWATCH_PROFILE_DIR',str(profile)); monkeypatch.delenv('JOBWATCH_DB',raising=False)
    config=Config(config_dir=DEFAULT_CONFIG_DIR,settings=_merge(DEFAULT_SETTINGS,{'db_path':str(data/'test.db'),'pipeline':{'agentic':{'enabled':True,'worker_model':'claude/sonnet','reviewer_model':'claude/haiku','research_enabled':False}}}),rules={},searches={},feeds={},employers=[])
    conn=db.connect(config.db_path); pid=seed(conn,1,'Accounts role',company='Example',arm='accounting')
    conn.execute("INSERT INTO ad_text(posting_id,text,source,fetched_at) VALUES(?,?,'cached',?)",(pid,AD,datetime.now(UTC).isoformat())); conn.commit(); conn.close()
    bundle=snapshot_evidence(profile); writer=Writer(bundle,payload=proposal(bundle,AD)); reviewer=Reviewer(verdicts=('approve',)*10)
    class Combo:
        base_url = model_choice.SERVER_URL
        def chat_once(self,model,*args,**kwargs):
            return (writer if model=='claude/sonnet' else reviewer).chat_once(model,*args,**kwargs)
    monkeypatch.setattr('jobwatch.interview_prep.configured_llm',lambda _:Combo())
    with TestClient(create_app(config),base_url='http://localhost',headers=OK) as client:
        client.pid=pid; client.writer=writer; client.profile=profile; client.config=config
        yield client


def test_generation_download_cache_and_no_application(prep_client):
    c=prep_client; url=f'/jobs/{c.pid}/interview-prep'
    assert 'Generate interview preparation' in c.get(url).text
    result=c.post(url)
    assert result.status_code==200 and 'Your reviewed interview preparation' in result.text
    assert 'JD-derived inference' in result.text and 'I reconciled ledgers.' in result.text
    assert 'Evidence: ad' in result.text and 'Unknown' in result.text
    download=c.get(url+'/download')
    assert download.status_code==200 and 'private, no-store'==download.headers['cache-control']
    assert 'I reconciled ledgers.' in download.text and 'Source' in download.text
    c.post(url); assert len(c.writer.calls)==2
    conn=db.connect(c.config.db_path)
    assert conn.execute('SELECT count(*) FROM applications').fetchone()[0]==0
    conn.close()


def test_notes_revision_escape_staleness_and_origin(prep_client):
    c=prep_client; url=f'/jobs/{c.pid}/interview-prep'; c.post(url)
    updated=c.post(url+'/inputs',data={'revision':'0','invite':'<script>private example</script>'})
    assert '&lt;script&gt;private example&lt;/script&gt;' in updated.text
    assert 'Your reviewed interview preparation' not in updated.text
    assert c.get(url+'/download').status_code==409
    assert c.post(url+'/inputs',data={'revision':'0','invite':'overwrite'}).status_code==409
    assert 'private example' in c.get(url).text
    assert c.post(url,headers={'origin':'https://outside.example'}).status_code==403
    assert c.post(url+'/inputs',data={'revision':1},headers={'origin':'https://outside.example'}).status_code==403


def test_private_readiness_and_not_found(prep_client):
    c=prep_client; url=f'/jobs/{c.pid}/interview-prep'; (c.profile/'cv.md').unlink()
    assert 'Check interview readiness' in c.get(url).text
    assert c.post(url).status_code==409 and not c.writer.calls
    assert c.get('/jobs/9999/interview-prep').status_code==404


def test_held_requires_explicit_retry(prep_client,monkeypatch):
    c=prep_client; url=f'/jobs/{c.pid}/interview-prep'
    import jobwatch.interview_prep as service
    original=service.configured_llm
    class Failed:
        base_url = model_choice.SERVER_URL
        def chat_once(self,*a,**kw): raise RuntimeError('private exception')
    monkeypatch.setattr(service,'configured_llm',lambda _:Failed())
    assert 'Preparation held for verification' in c.post(url).text
    monkeypatch.setattr(service,'configured_llm',original)
    assert 'Preparation held for verification' in c.post(url).text and not c.writer.calls
    assert 'Your reviewed interview preparation' in c.post(url,data={'retry':'true'}).text


@pytest.mark.parametrize('path', ['/api/job/{pid}/status'])
def test_explicit_interview_status_checks_eligibility(prep_client,monkeypatch,path):
    c=prep_client; checks=[]
    def eligible(conn,pid,config):
        checks.append(conn.execute('SELECT status FROM applications WHERE posting_id=?',(pid,)).fetchone()[0])
        return True
    monkeypatch.setattr('jobwatch.interview_prep.should_prepare_after_interview',eligible)
    assert c.post(path.format(pid=c.pid),json={'status':'interview'}).status_code==200
    assert checks==['interview'] and len(c.writer.calls)==2
    c.post(path.format(pid=c.pid),json={'status':'interview'})
    assert len(c.writer.calls)==2


def test_owner_outcome_approval_queues_interview(prep_client,monkeypatch):
    c=prep_client
    c.post(f'/api/job/{c.pid}/status',json={'status':'applied'})
    conn=db.connect(c.config.db_path)
    aid=conn.execute('SELECT id FROM applications WHERE posting_id=?',(c.pid,)).fetchone()[0]
    conn.execute("INSERT INTO outcome_proposals(application_id,source_message_id,proposed_status) VALUES(?,'synthetic-invite','interview')",(aid,))
    proposal_id=conn.execute('SELECT id FROM outcome_proposals').fetchone()[0]; conn.commit(); conn.close()
    checks=[]
    def eligible(conn,pid,config):
        checks.append(conn.execute('SELECT status FROM applications WHERE posting_id=?',(pid,)).fetchone()[0])
        return True
    monkeypatch.setattr('jobwatch.interview_prep.should_prepare_after_interview',eligible)
    assert c.post(f'/api/inbox/{proposal_id}/approve').status_code==200
    assert checks==['interview'] and len(c.writer.calls)==2


def test_ineligible_interview_transition_does_not_generate(prep_client):
    c=prep_client
    assert c.post(f'/api/job/{c.pid}/status',json={'status':'interview'}).status_code==200
    assert not c.writer.calls  # No current source-bound evaluation in this fixture.


def test_report_text_is_escaped_and_poll_is_fragment(prep_client,monkeypatch):
    c=prep_client; url=f'/jobs/{c.pid}/interview-prep'
    c.writer.payload['sections'][0]['items'][0]['text']='<script>example</script>'
    page=c.post(url)
    assert '&lt;script&gt;example&lt;/script&gt;' in page.text
    assert '<script>example</script>' not in page.text
    monkeypatch.setattr('jobwatch.interview_prep.load_report',lambda *a,**kw:{'status':'running','report':None})
    poll=c.get(url,headers={'hx-request':'true'})
    assert 'hx-trigger="every 3s"' in poll.text and '<html' not in poll.text


def test_source_link_filter_only_public_https(prep_client):
    # Retrieve the actual app-owned filter through the template environment.
    c=prep_client; response=c.get(f'/jobs/{c.pid}/interview-prep')
    filter_url=response.template.environment.filters['interview_source_url']
    assert filter_url('https://example.com/interviews')=='https://example.com/interviews'
    for bad in ('javascript:alert(1)','http://example.com','https://127.0.0.1/test',
                'https://user:password@example.com','https://localhost/test','https://example.com:8080',
                'https://example.com/\nprivate'):
        assert not filter_url(bad)


def test_interview_transition_saves_queue_before_dispatch(prep_client,monkeypatch):
    from fastapi import BackgroundTasks
    c=prep_client; scheduled=[]
    monkeypatch.setattr('jobwatch.interview_prep.should_prepare_after_interview',lambda *a:True)
    monkeypatch.setattr(BackgroundTasks,'add_task',lambda self,fn,*a,**kw:scheduled.append(fn))
    assert c.post(f'/api/job/{c.pid}/status',json={'status':'interview'}).status_code==200
    conn=db.connect(c.config.db_path)
    from jobwatch.interview_prep import queued_posting_ids
    assert queued_posting_ids(conn,c.config)==(c.pid,)
    conn.close()
    assert len(scheduled)==1 and not c.writer.calls
    assert 'Researching, preparing and reviewing' in c.get(f'/jobs/{c.pid}/interview-prep').text


def test_startup_recovers_durable_queue_once(prep_client,monkeypatch):
    import threading
    import jobwatch.interview_prep as service
    c=prep_client; conn=db.connect(c.config.db_path)
    assert service.enqueue(conn,c.pid,c.config); conn.close()
    completed=threading.Event(); original=service.generate
    def tracked(*a,**kw):
        try: return original(*a,**kw)
        finally: completed.set()
    monkeypatch.setattr(service,'generate',tracked)
    with TestClient(create_app(c.config),base_url='http://localhost',headers=OK) as recovered:
        assert completed.wait(10), 'Startup did not recover queued work'
        assert 'Your reviewed interview preparation' in recovered.get(f'/jobs/{c.pid}/interview-prep').text
    assert len(c.writer.calls)==2
    with TestClient(create_app(c.config),base_url='http://localhost',headers=OK): pass
    assert len(c.writer.calls)==2


def test_startup_never_retries_held_unknown_dispatch(prep_client,monkeypatch):
    import jobwatch.interview_prep as service
    c=prep_client
    class Failed:
        base_url = model_choice.SERVER_URL
        def chat_once(self,*a,**kw): raise RuntimeError('uncertain private call')
    monkeypatch.setattr(service,'configured_llm',lambda _:Failed())
    assert 'Preparation held for verification' in c.post(f'/jobs/{c.pid}/interview-prep').text
    def forbidden(*a,**kw): pytest.fail('Startup retried held work')
    monkeypatch.setattr(service,'generate',forbidden)
    with TestClient(create_app(c.config),base_url='http://localhost',headers=OK): pass
    assert not c.writer.calls


def test_queue_write_failure_is_private_unavailable(prep_client,monkeypatch):
    from pipeline.agentic.contracts import AgenticError
    c=prep_client
    def failed(*a,**kw): raise AgenticError('private_queue_failure')
    monkeypatch.setattr('jobwatch.interview_prep.enqueue',failed)
    result=c.post(f'/jobs/{c.pid}/interview-prep')
    assert result.status_code==409 and 'private_queue_failure' not in result.text
    assert not c.writer.calls


def test_worker_drains_new_owner_queued_snapshot(prep_client,monkeypatch):
    import jobwatch.interview_prep as service
    from jobwatch.interview_inputs import InterviewInputs, save_inputs
    c=prep_client; original=service.generate; generated=[]
    def changed(conn,pid,config,**kwargs):
        generated.append(kwargs)
        result=original(conn,pid,config,**kwargs)
        if len(generated)==1:
            save_inputs(conn,pid,InterviewInputs(invite='New owner-supplied invite'),expected_revision=0)
            assert service.enqueue(conn,pid,config)
        return result
    monkeypatch.setattr(service,'generate',changed)
    result=c.post(f'/jobs/{c.pid}/interview-prep')
    assert 'Your reviewed interview preparation' in result.text
    assert len(generated)==2 and all(g['queued_only'] for g in generated)
    assert len(c.writer.calls)==4


def test_worker_does_not_dispatch_unqueued_changed_source(prep_client,monkeypatch):
    import jobwatch.interview_prep as service
    from jobwatch.interview_inputs import InterviewInputs, save_inputs
    c=prep_client; original=service.generate; calls=[]
    def changed_before_start(conn,pid,config,**kwargs):
        calls.append(kwargs)
        save_inputs(conn,pid,InterviewInputs(invite='Changed before worker start'),expected_revision=0)
        return original(conn,pid,config,**kwargs)
    monkeypatch.setattr(service,'generate',changed_before_start)
    result=c.post(f'/jobs/{c.pid}/interview-prep')
    assert 'Generate interview preparation' in result.text
    assert len(calls)==1 and calls[0]['queued_only'] is True
    assert not c.writer.calls


def test_recovery_scan_cannot_enqueue_changed_sources(prep_client,monkeypatch):
    import jobwatch.interview_prep as service
    from jobwatch.interview_inputs import InterviewInputs, save_inputs
    c=prep_client; conn=db.connect(c.config.db_path)
    assert service.enqueue(conn,c.pid,c.config);conn.close()
    original=service.queued_posting_ids
    def changed_after_scan(conn,config):
        pending=original(conn,config)
        if pending:save_inputs(conn,c.pid,InterviewInputs(invite='Changed during recovery scan'),expected_revision=0)
        return pending
    monkeypatch.setattr(service,'queued_posting_ids',changed_after_scan)
    with TestClient(create_app(c.config),base_url='http://localhost',headers=OK):pass
    assert not c.writer.calls
    conn=db.connect(c.config.db_path)
    assert conn.execute('SELECT count(*) FROM interview_runs').fetchone()[0]==1
    conn.close()


def test_one_persons_active_interview_does_not_block_anothers_same_posting_id(prep_client,monkeypatch):
    import jobwatch.interview_prep as service
    from jobwatch import users
    from jobwatch.web.auth_routes import set_password
    c=prep_client; ran=[]
    monkeypatch.setattr(service,'capture',lambda *a,**kw:None)
    monkeypatch.setattr(service,'enqueue',lambda *a,**kw:True)
    monkeypatch.setattr(service,'is_queued',lambda *a,**kw:False)
    monkeypatch.setattr('jobwatch.candidate.evidence.snapshot_evidence',lambda *_:None)
    def generate(conn,pid,config,**kw):
        ran.append(users.current())
        if len(ran)>1:return
        # the owner's run is still active here: a friend asks for the same bare posting id
        monkeypatch.setenv('JOBWATCH_SESSION_SECRET','s3cret'); set_password('friend','longenough1'); users.create_user_dirs('friend')
        fc=db.connect(users.db_path('friend')); assert seed(fc,1,'Friend role')==pid; fc.close()
        friend=TestClient(c.app,base_url='http://localhost',headers=OK)
        assert friend.post('/login',data={'username':'friend','password':'longenough1'},follow_redirects=False).status_code==303
        assert friend.post(f'/jobs/{pid}/interview-prep',follow_redirects=False).status_code==303
    monkeypatch.setattr(service,'generate',generate)
    assert c.post(f'/jobs/{c.pid}/interview-prep',follow_redirects=False).status_code==303
    assert ran==['owner','friend']
