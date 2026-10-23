"""Native browser frontend uses canonical synthetic form review and one-use Submit."""
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jobwatch import users
from jobwatch.config import Config, DEFAULT_CONFIG_DIR, DEFAULT_SETTINGS, _merge
from jobwatch.apply import browser as workflow, prepare
from jobwatch.apply import submit_confirm
from pipeline.agentic.api import Principal, create_api
from tests.test_browser_session import manager, submission_site  # noqa: F401
from tests.test_submit_confirm import _ready
from tests.web.test_agentic import _client

CHAT, HUMAN, FRIEND = 'a'*40, 'b'*40, 'c'*40


def auth(key=HUMAN):
    return {'Authorization':'Bearer '+key}


@pytest.fixture
def native(tmp_path,monkeypatch,manager,submission_site):
    monkeypatch.setenv('JOBWATCH_LIBRECHAT_ENABLED','true')
    monkeypatch.setenv('JOBWATCH_MCP_APP_ENABLED','true')
    monkeypatch.setenv('JOBWATCH_APP_ORIGIN','https://chat.example.test')
    manager.data_root=None
    seed=_client(tmp_path,monkeypatch)
    cfg=Config(config_dir=DEFAULT_CONFIG_DIR,settings=_merge(DEFAULT_SETTINGS,{'db_path':str(seed.data/'jobwatch.db')}),
               rules={},searches={},feeds={},employers=[])
    manifest={'pdfs':{'cv':'a'*64,'letter':'b'*64},'verification':{'review':True}}
    package={'run_key':'c'*64,'status':'ready','manifest':manifest,'cv_pdf':'/synthetic/cv.pdf',
             'letter_pdf':'/synthetic/letter.pdf','candidate':None,'evaluation':None}
    monkeypatch.setattr(workflow,'latest_result',lambda *a:package)
    monkeypatch.setattr(workflow,'package_is_current',lambda *a:True)
    prepared=_ready(manager,submission_site[0],tmp_path,'1')
    prepared['package_hash']=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    run_dir=seed.data/'browser'/hashlib.sha256(b'1').hexdigest()/prepared['run_id']
    run_dir.mkdir(parents=True,mode=0o700)
    prepare._write_json(run_dir/'prepared.json',prepared)
    from jobwatch.apply.paths import safe_write_text
    safe_write_text(run_dir.parent/'latest.json',json.dumps({'run_id':prepared['run_id']}))
    app=create_api(credentials={CHAT:Principal('owner'),HUMAN:Principal('owner',frozenset({'read','approve','interact'})),
                   FRIEND:Principal('friend',frozenset({'read','approve','interact'}))},config=cfg,browser_sessions=manager)
    client=TestClient(app)
    return client,manager,submission_site,prepared


def test_live_review_changed_form_and_final_submit(native):
    client,manager,(base,seen),prepared=native
    path='/api/agent/applications/1'
    assert client.get(path+'/review',headers=auth(CHAT)).status_code==403
    shown=client.get(path+'/review',headers=auth())
    assert shown.status_code==200,shown.text
    shown=shown.json()
    assert shown['fields'][0]['value']=='Synthetic'
    assert shown['confirmed_digest']==submit_confirm.digest(prepared)
    # Changing actual form content invalidates the exact review. No POST reached employer.
    manager.with_page('1',lambda page:page.locator('#name').fill('Human correction'))
    assert client.post(path+'/submit',headers={**auth(),'Idempotency-Key':'first'},json={'digest':shown['confirmed_digest']}).status_code==409
    changed=client.get(path+'/review',headers=auth()).json()
    assert changed['confirmed_digest'] is None and changed['fields'][0]['value']=='Human correction'
    rebound=client.post(path+'/review',headers=auth(),json={'digest':changed['review_digest']})
    assert rebound.status_code==200,rebound.text
    digest=rebound.json()['confirmed_digest']
    response=client.post(path+'/submit',headers={**auth(),'Idempotency-Key':'corrected'},json={'digest':digest})
    assert response.status_code==202,response.text
    assert seen==[('GET','/')]
    # Same request is idempotent; another request while queued is refused.
    assert client.post(path+'/submit',headers={**auth(),'Idempotency-Key':'corrected'},json={'digest':digest}).status_code==202
    assert client.post(path+'/submit',headers={**auth(),'Idempotency-Key':'duplicate'},json={'digest':digest}).status_code==409
    with users.use('owner'):
        client.app.state.application_service('owner').process_submit_requests()
    manager.with_page('1',lambda page:page.wait_for_url(base+'submit'))
    assert seen==[('GET','/'),('POST','/submit')]


def test_browser_capability_cannot_press_submit_and_is_person_bound(native):
    client,manager,(base,seen),prepared=native
    cap=client.post('/api/agent/client/browser/control',headers=auth(),json={'posting_id':1})
    assert cap.status_code==200,cap.text
    cap=cap.json()
    box=manager.with_page('1',lambda page:page.locator('#submit').bounding_box())
    body=cap['ticket']+'\n'+json.dumps({'kind':'click','x':box['x']+5,'y':box['y']+5})
    refused=client.post('/api/agent/client/browser/action',content=body,headers={'Content-Type':'text/plain','Origin':'null'})
    assert refused.status_code==409,refused.text
    assert seen==[('GET','/')]
    assert client.post('/api/agent/client/browser/control',headers=auth(CHAT),json={'posting_id':1}).status_code==403
    with users.use('friend'):
        from jobwatch.web.browser_session import BrowserSessionError
        with pytest.raises(BrowserSessionError,match='browser_session_not_open'):
            manager.status('1')
    # A principal cannot add a claimed person to a grant.
    assert client.post('/api/agent/client/browser/control',headers=auth(),json={'posting_id':1,'person':'friend'}).status_code==422


def test_accounts_and_expired_browser_grants_are_isolated(native,monkeypatch):
    client,manager,_,prepared=native
    users.create_user_dirs('friend')
    for suffix in ('','/frame','/review'):
        assert client.get('/api/agent/applications/1'+suffix,headers=auth(FRIEND)).status_code==404
    assert client.get('/api/agent/applications',headers=auth(FRIEND)).json()=={'applications':[]}
    assert client.get('/api/agent/applications/1/frame',headers=auth()).headers['content-type']=='image/jpeg'
    assert client.post('/api/agent/client/browser/control',headers=auth(FRIEND),json={'posting_id':1}).status_code==404
    cap=client.post('/api/agent/client/browser/control',headers=auth(),json={'posting_id':1}).json()
    from pipeline.agentic.client_api import _db
    with _db() as conn:
        conn.execute('UPDATE tickets SET expires=0')
    response=client.post('/api/agent/client/browser/action',headers={'Content-Type':'text/plain','Origin':'null'},
                        content=cap['ticket']+'\n'+json.dumps({'kind':'type','text':'Never inserted'}))
    assert response.status_code==401
    assert manager.with_page('1',lambda page:page.locator('#name').input_value())=='Synthetic'


def test_website_adapter_uses_shared_native_session_not_pages(native,monkeypatch):
    client,manager,_,prepared=native
    from jobwatch.apply.browser_remote import RemoteBrowserSessions,RemoteBrowserService
    import requests
    monkeypatch.setenv('JOBWATCH_NATIVE_BROWSER_URL','http://127.0.0.1:18914')
    monkeypatch.setenv('JOBWATCH_AGENT_TOKEN',CHAT)
    monkeypatch.setenv('JOBWATCH_AGENT_APPROVAL_TOKEN',HUMAN)
    monkeypatch.setenv('JOBWATCH_AGENT_PERSON','owner')
    sent=[]
    def post(self,url,**kwargs):
        assert url=='http://127.0.0.1:18914/api/agent/browser/website'
        sent.append(kwargs['headers']['Authorization'])
        response=client.post('/api/agent/browser/website',headers=kwargs['headers'],json=kwargs['json'])
        response.ok=response.is_success
        return response
    monkeypatch.setattr(requests.Session,'post',post)
    sessions=RemoteBrowserSessions()
    assert sessions.status('1')['target_id']==prepared['session_id']
    assert sessions.snapshot('1').jpeg.startswith(b'\xff\xd8')
    assert RemoteBrowserService().preparation_context(1)['prepared']['run_id']==prepared['run_id']
    sessions.close_all()  # stopping the website must not close the native browser
    assert sessions.status('1')['state']=='ready'
    assert sent and all(value=='Bearer '+HUMAN for value in sent)
    with users.use('friend'):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            sessions.status('1')
        assert exc.value.status_code==503  # no fallback to owner's credential


def test_unreadable_custom_form_stays_blocked(native):
    client,manager,(_,seen),_=native
    manager.with_page('1',lambda page:page.evaluate("const e=document.createElement('div');e.contentEditable='true';document.querySelector('form').appendChild(e)"))
    review=client.get('/api/agent/applications/1/review',headers=auth())
    assert review.status_code==200 and review.json()['status']=='blocked'
    assert review.json()['reason']=='unsupported_form_review'
    assert client.post('/api/agent/applications/1/submit',headers={**auth(),'Idempotency-Key':'unsupported'},json={'digest':'a'*64}).status_code==409
    assert seen==[('GET','/')]
