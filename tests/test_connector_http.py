"""The loopback JSON front: auth, per-person binding, the digest staying out of the job fields, submit safety."""
import pytest
from fastapi.testclient import TestClient

from pipeline.agentic import connector_http
from tests.test_mcp_server import PREPARED, reviewed, two_people, _requests  # noqa: F401

TOKEN = 'x' * 40
H = {'Authorization': 'Bearer ' + TOKEN}


@pytest.fixture
def client(two_people):
    return TestClient(connector_http.create_app(token=TOKEN, person='owner'))


def test_bearer_required_everywhere(client):
    for path in ('/connector/overview', '/connector/jobs/1', '/connector/jobs/1/status'):
        assert client.get(path).status_code == 401
        assert client.get(path, headers={'Authorization': 'Bearer ' + 'y' * 40}).status_code == 401
    assert client.post('/connector/jobs/1/submit', json={'confirm_digest': 'a'}).status_code == 401


def test_refuses_to_start_without_a_long_token():
    with pytest.raises(Exception):
        connector_http.create_app(token='short', person='owner')


def test_reads_are_for_the_configured_person_only(client):
    jobs = client.get('/connector/overview', headers=H).json()['jobs']
    assert [j['employer'] for j in jobs] == ['Acme Pty']
    assert client.get('/connector/jobs/1/status', headers=H).json()['state'] == 'draft ready'


def test_digest_is_a_separate_field_and_submit_needs_it(reviewed, client):
    body = client.get('/connector/jobs/1', headers=H).json()
    assert body['submit_digest'] == reviewed and 'submit_digest' not in body['job'] and reviewed not in str(body['job'])
    for digest in ('', 'a' * 64):
        assert client.post('/connector/jobs/1/submit', headers=H, json={'confirm_digest': digest}).status_code == 400
    assert _requests('owner') == []
    ok = client.post('/connector/jobs/1/submit', headers=H, json={'confirm_digest': reviewed})
    assert ok.status_code == 200 and ok.json()['status'] == 'queued'
    assert client.post('/connector/jobs/1/submit', headers=H, json={'confirm_digest': reviewed}).status_code == 400
    assert len(_requests('owner')) == 1


def test_unknown_approval_is_refused(client):
    r = client.post('/connector/decide', headers=H, json={'interaction_id': 'nope', 'decision': 'approve', 'binding': 'b'})
    assert r.status_code == 400 and r.json() == {'error': 'approval_not_found'}
