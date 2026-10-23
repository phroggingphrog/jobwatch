"""Trusted server enrollment; invented subjects, never real account/profile fixtures."""
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from pipeline.agentic.api import create_api, Principal

RUN, HUMAN, BRIDGE='r'*40,'h'*40,'b'*48

def setup(monkeypatch):
    monkeypatch.setenv('JOBWATCH_LIBRECHAT_IDENTITY_KEY',BRIDGE)
    monkeypatch.setenv('JOBWATCH_LIBRECHAT_OWNER_SUBJECT','synthetic-owner')
    return TestClient(create_api(credentials={RUN:Principal('owner'),HUMAN:Principal('owner',frozenset({'read','interact','approve'}))},config={}))

def enroll(c,subject,key=BRIDGE):
    return c.post('/api/agent/librechat/enroll',headers={'Authorization':'Bearer '+key},json={'subject':subject})

def test_trusted_enrollment_preserves_owner_and_isolates_friends(monkeypatch):
    c=setup(monkeypatch)
    assert enroll(c,'synthetic-friend',RUN).status_code==401
    owner=enroll(c,'synthetic-owner');assert owner.status_code==200
    assert owner.json()=={'person':'owner','chat_key':RUN,'human_key':HUMAN}
    first=enroll(c,'synthetic-friend');assert first.status_code==200
    friend=first.json();assert friend['person']!='owner' and friend['chat_key']!=friend['human_key']
    assert enroll(c,'synthetic-friend').json()==friend
    assert enroll(c,'synthetic-second').json()['person']!=friend['person']
    headers={'Authorization':'Bearer '+friend['chat_key']}
    thread=c.post('/api/agent/threads',headers=headers);assert thread.status_code==201
    assert c.get('/api/agent/threads/'+thread.json()['id'],headers={'Authorization':'Bearer '+RUN}).status_code==404
    assert c.get('/api/agent/capabilities',headers={'Authorization':'Bearer '+friend['human_key']}).json()['scopes']==['approve','interact','read']

def test_concurrent_enrollment_is_idempotent_and_does_not_accept_identity_fields(monkeypatch):
    c=setup(monkeypatch)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows=list(pool.map(lambda _:enroll(c,'synthetic-parallel').json(),range(4)))
    assert all(r==rows[0] for r in rows)
    assert enroll(c,'../owner').status_code==422
    assert c.post('/api/agent/librechat/enroll',headers={'Authorization':'Bearer '+BRIDGE},json={'subject':'friend','person':'owner'}).status_code==422
