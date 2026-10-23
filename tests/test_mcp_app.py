"""Synthetic MCP app boundaries; no candidate data, credentials or paid calls."""
import hashlib
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from pipeline.agentic.api import Principal, create_api
from pipeline.agentic.api_store import APIStore
from pipeline.agentic.mcp_app import create_server

RUN, HUMAN, OTHER = 'r'*40, 'h'*40, 'o'*40
CREDS={RUN:Principal('app-one'),HUMAN:Principal('app-one',frozenset({'read','interact','approve'})),
       OTHER:Principal('app-two')}
ORIGIN='https://libre.example.com'


@pytest.fixture
def native(monkeypatch):
    monkeypatch.setenv('JOBWATCH_LIBRECHAT_ENABLED','true')
    monkeypatch.setenv('JOBWATCH_MCP_APP_ENABLED','true')
    monkeypatch.setenv('JOBWATCH_APP_ORIGIN',ORIGIN)
    app=create_api(credentials=CREDS,config={'pipeline':{'execution_mode':'agentic'}})
    with TestClient(app) as client:
        yield client,app


def bearer(key=RUN):return {'Authorization':'Bearer '+key}


def test_upload_exact_bytes_scope_replay_and_native_cap(native):
    client,_=native
    data=b'Synthetic fixture evidence.\n'*7000  # exceeds normal API JSON cap
    spec={'filename':'synthetic.txt','kind':'evidence','sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
    path='/api/agent/client/upload-ticket'
    assert client.post(path,headers=bearer(),json=spec).status_code==403
    cap=client.post(path,headers=bearer(HUMAN),json=spec).json()
    headers={'Authorization':'JobwatchUpload '+cap['ticket'],'Origin':'null','Content-Type':'application/octet-stream'}
    assert client.post('/api/agent/client/upload',headers=headers,content=data+b'x').status_code==409
    response=client.post('/api/agent/client/upload',headers=headers,content=data)
    assert response.status_code==201
    assert response.headers['access-control-allow-origin']=='null'
    assert response.json()['sha256']==spec['sha256']
    assert client.post('/api/agent/client/upload',headers=headers,content=data).status_code==401
    assert client.post('/api/agent/client/upload',content=data).status_code==401
    assert 'access-control-allow-origin' not in client.get('/api/agent/client/models',headers=bearer()).headers
    assert client.options('/api/agent/client/upload',headers={'Origin':'https://evil.example'}).status_code==403
    assert client.options('/api/agent/client/upload',headers={'Origin':'null'}).status_code==200
    too_large={**spec,'bytes':10*1024*1024+1}
    assert client.post(path,headers=bearer(HUMAN),json=too_large).status_code==422
    # An expired capability is never accepted, even before body buffering.
    cap=client.post(path,headers=bearer(HUMAN),json=spec).json()
    from pipeline.agentic.client_api import _db
    with _db() as conn:conn.execute('UPDATE tickets SET expires=?',(time.time()-1,))
    assert client.post('/api/agent/client/upload',headers={**headers,'Authorization':'JobwatchUpload '+cap['ticket']},content=data).status_code==401


def test_ticket_upload_accepts_native_ten_mib_boundary(native):
    client,_=native
    data=b'synthetic text\n'+b' '* (10*1024*1024-15)
    assert len(data)==10*1024*1024
    spec={'filename':'boundary.txt','kind':'cv','sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
    cap=client.post('/api/agent/client/upload-ticket',headers=bearer(HUMAN),json=spec).json()
    h={'Origin':'null','Content-Type':'text/plain'}
    assert client.post('/api/agent/client/upload',headers=h,content=cap['ticket'].encode()+b'\n'+data).status_code==201


def rpc(client,key,method,params=None):
    response=client.post('/mcp',headers={**bearer(key),'Accept':'application/json, text/event-stream'},
        json={'jsonrpc':'2.0','id':1,'method':method,'params':params or {}})
    if response.status_code!=200:return response
    raw=response.text
    if raw.startswith('event:'):
        raw=next(s[6:] for s in raw.splitlines() if s.startswith('data: '))
    return json.loads(raw)


def test_actual_mcp_http_auth_resource_and_app_only_scope(native):
    _,api=native
    with APIStore('app-one') as store:
        thread=store.create_thread('synthetic')['id']; run=store.enqueue(thread,{'message':'synthetic'},'fixture')
    server=create_server(credentials=CREDS,origin=ORIGIN,transport=httpx.ASGITransport(app=api))
    with TestClient(server.http_app(path='/mcp',stateless_http=True)) as client:
        tools=rpc(client,RUN,'tools/list')['result']['tools']
        action=next(t for t in tools if t['name']=='jobwatch_action')
        assert action['_meta']['ui']['visibility']==['app']
        view=next(t for t in tools if t['name']=='jobwatch_view')
        assert view['_meta']['ui']['resourceUri']=='ui://jobwatch/panel.html'
        args={'name':'jobwatch_view','arguments':{'run_id':run}}
        assert not rpc(client,RUN,'tools/call',args)['result'].get('isError')
        assert rpc(client,OTHER,'tools/call',args)['result']['isError']
        a={'name':'jobwatch_action','arguments':{'action':'upload_ticket','arguments':{
            'filename':'fixture.txt','kind':'cv','sha256':'a'*64,'bytes':10}}}
        assert rpc(client,RUN,'tools/call',a)['result']['isError']
        result=rpc(client,HUMAN,'tools/call',a)['result']
        assert not result.get('isError')
        assert result['_meta']['jobwatch']['ticket']
        assert 'ticket' not in str(result.get('content'))
        page=rpc(client,HUMAN,'resources/read',{'uri':'ui://jobwatch/panel.html'})['result']['contents'][0]
        assert page['mimeType']=='text/html;profile=mcp-app'
        assert HUMAN not in page['text'] and RUN not in page['text']
        state=rpc(client,HUMAN,'resources/read',{'uri':'jobwatch://runs/'+run})['result']
        assert json.loads(state['contents'][0]['text'])['run']['id']==run
        assert rpc(client,'bad','tools/list').status_code==401


def test_simple_browser_upload_binds_capability_without_preflight(native):
    client,_=native
    data=b'Synthetic browser document.'
    spec={'filename':'browser.txt','kind':'cv','sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
    cap=client.post('/api/agent/client/upload-ticket',headers=bearer(HUMAN),json=spec).json()
    h={'Origin':'null','Content-Type':'text/plain'}
    body=cap['ticket'].encode()+b'\n'+data
    response=client.post('/api/agent/client/upload',headers=h,content=body)
    assert response.status_code==201
    assert response.json()['sha256']==spec['sha256']
    assert client.post('/api/agent/client/upload',headers=h,content=body).status_code==401
    assert client.post('/api/agent/client/upload',headers=h,content=b'bad\n'+data).status_code==401


def test_panel_follows_canonical_selection_when_child_is_dispatched(monkeypatch):
    monkeypatch.setenv('JOBWATCH_LIBRECHAT_ENABLED','true')
    monkeypatch.setenv('JOBWATCH_MCP_APP_ENABLED','true')
    monkeypatch.setenv('JOBWATCH_APP_ORIGIN',ORIGIN)
    api=create_api(credentials=CREDS,config={'pipeline':{'execution_mode':'agentic'}})
    selected={'id':'selection-fixture','state':'pending_dispatch','run_id':None}
    child={'id':'child-fixture','state':'completed','artifacts':[{'id':'doc-fixture','kind':'cv'}]}
    seen=[]
    class Routed(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            if request.url.path=='/api/agent/selections/selection-fixture':
                seen.append(request.headers['authorization'])
                assert request.method=='GET'
                return httpx.Response(200,json=selected)
            return await httpx.ASGITransport(app=api).handle_async_request(request)
    with APIStore('app-one') as store:
        thread=store.create_thread('synthetic')['id']
        run=store.enqueue(thread,{'message':'synthetic'},'selection-fixture')
        store.finish(run,{'outcomes':[{'status':'selected','selection_id':'selection-fixture','run_id':None}]})
    server=create_server(credentials=CREDS,origin=ORIGIN,transport=Routed())
    with TestClient(server.http_app(path='/mcp',stateless_http=True)) as client:
        def read():
            result=rpc(client,HUMAN,'resources/read',{'uri':'jobwatch://runs/'+run})['result']
            return json.loads(result['contents'][0]['text'])
        assert read()['selections'][0]['run_id'] is None
        selected.update(state='completed',run_id=child['id'],run=child)
        assert read()['selections'][0]['run']['artifacts']==child['artifacts']
        assert seen==['Bearer '+HUMAN]*2
