"""Trusted server enrollment; invented subjects, never real account/profile fixtures."""
import pytest
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from pipeline.agentic.api import create_api, Principal


@pytest.fixture(autouse=True)
def _owner_folder_profile(monkeypatch):
    monkeypatch.setenv("JOBWATCH_PROFILE_DIR", "")   # the owner's own data folder, not the conftest-pinned example profile

RUN, HUMAN, BRIDGE='r'*40,'h'*40,'b'*48

def setup(monkeypatch):
    monkeypatch.setenv('JOBWATCH_LIBRECHAT_IDENTITY_KEY',BRIDGE)
    monkeypatch.setenv('JOBWATCH_LIBRECHAT_OWNER_SUBJECT','synthetic-owner')
    return TestClient(create_api(credentials={RUN:Principal('owner'),HUMAN:Principal('owner',frozenset({'read','interact','approve'}))},config={}))

def enroll(c,subject,key=BRIDGE):
    return c.post('/api/agent/librechat/enroll',headers={'Authorization':'Bearer '+key},json={'subject':subject})


def test_concurrent_enrollment_is_idempotent_and_does_not_accept_identity_fields(monkeypatch):
    c=setup(monkeypatch)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows=list(pool.map(lambda _:enroll(c,'synthetic-owner').json(),range(4)))
    assert all(r==rows[0] for r in rows) and rows[0]['person']=='owner'
    assert enroll(c,'synthetic-friend').status_code==401
    assert enroll(c,'../owner').status_code==422
    assert c.post('/api/agent/librechat/enroll',headers={'Authorization':'Bearer '+BRIDGE},json={'subject':'friend','person':'owner'}).status_code==422


def test_standard_endpoint_binds_trusted_client_subject_without_human_scope(monkeypatch):
    monkeypatch.setenv('JOBWATCH_LIBRECHAT_ENABLED', 'true')
    c = setup(monkeypatch)
    owner = {'Authorization': 'Bearer ' + BRIDGE, 'X-Jobwatch-Client-Subject': 'synthetic-owner'}
    friend = {**owner, 'X-Jobwatch-Client-Subject': 'synthetic-friend'}
    assert c.get('/v1/models', headers=owner).status_code == 200
    assert c.get('/v1/models', headers=friend).status_code == 401
    assert enroll(c, 'synthetic-owner').json()['person'] == 'owner'
    assert enroll(c, 'synthetic-friend').status_code == 401
    assert c.get('/v1/models', headers={'Authorization': 'Bearer ' + BRIDGE}).status_code == 401
    assert c.get('/v1/models', headers={**friend, 'Authorization': 'Bearer ' + RUN}).status_code == 401
    assert c.get('/api/agent/capabilities', headers=owner).status_code == 401
    assert c.post('/api/agent/threads', headers=owner).status_code == 401


def test_trusted_chat_confirmation_cannot_approve_an_application_submit(monkeypatch):
    monkeypatch.setenv('JOBWATCH_LIBRECHAT_ENABLED', 'true')
    monkeypatch.setenv('JOBWATCH_UI_FORMAT', 'artifacts')
    monkeypatch.setenv('JOBWATCH_LIBRECHAT_IDENTITY_KEY', BRIDGE)
    monkeypatch.setenv('JOBWATCH_LIBRECHAT_OWNER_SUBJECT', 'synthetic-owner')
    calls = []
    def dispatch(**kwargs):
        calls.append(kwargs)
        return {'status': 'interrupted', 'checkpoint_id': 'synthetic-submit', 'interactions': [
            {'type': 'approval', 'operation': 'submit_application', 'posting_id': 1,
             'binding': {'synthetic': 'reviewed-employer-form'}}]}
    app = create_api(credentials={RUN: Principal('owner'),
        HUMAN: Principal('owner', frozenset({'read', 'interact', 'approve'}))}, config={}, dispatcher=dispatch)
    headers = {'Authorization': 'Bearer ' + BRIDGE, 'X-Jobwatch-Client-Subject': 'synthetic-owner',
        'X-Jobwatch-Conversation': 'synthetic-submit'}
    messages = [{'role': 'user', 'content': 'Submit the application.'}]
    with TestClient(app) as client:
        first = client.post('/v1/chat/completions', headers=headers,
            json={'model': 'jobwatch-agent', 'messages': messages}).json()
        response = client.post('/v1/chat/completions', headers=headers,
            json={'model': 'jobwatch-agent', 'messages': [*messages, first['choices'][0]['message'],
                {'role': 'user', 'content': 'yes'}]}).json()
        assert response['id'] == first['id']
        assert 'requires a verified human approval interface' in response['choices'][0]['message']['content']
        assert len(calls) == 1 and calls[0]['human_decision'] is False


def test_non_owner_credentials_are_rejected_at_startup(monkeypatch):
    from pipeline.agentic.runtime import RuntimeErrorSafe
    monkeypatch.delenv('JOBWATCH_LIBRECHAT_IDENTITY_KEY', raising=False)
    with pytest.raises(RuntimeErrorSafe, match='api_principal_not_owner'):
        create_api(credentials={RUN: Principal('fixture-b')}, config={})


def test_environment_and_credential_file_reject_non_owner_principals(tmp_path, monkeypatch):
    import json
    from pipeline.agentic.api import credentials_from_env
    from pipeline.agentic.runtime import RuntimeErrorSafe
    monkeypatch.setenv('JOBWATCH_AGENT_PERSON', 'fixture-b')
    monkeypatch.setenv('JOBWATCH_AGENT_TOKEN', 't' * 40)
    with pytest.raises(RuntimeErrorSafe, match='api_principal_not_owner'):
        credentials_from_env()
    monkeypatch.delenv('JOBWATCH_AGENT_PERSON')
    monkeypatch.delenv('JOBWATCH_AGENT_TOKEN')
    path = tmp_path / 'credentials.json'
    path.write_text(json.dumps([{'token': 'u' * 40, 'person': 'fixture-b', 'scopes': ['read']}]))
    path.chmod(0o600)
    monkeypatch.setenv('JOBWATCH_AGENT_CREDENTIALS_FILE', str(path))
    with pytest.raises(RuntimeErrorSafe, match='api_principal_not_owner'):
        credentials_from_env()
