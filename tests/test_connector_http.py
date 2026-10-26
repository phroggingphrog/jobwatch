"""The loopback JSON front: auth, per-person binding, the digest staying out of the job fields, the review content
and submit safety."""
import pytest
from fastapi.testclient import TestClient

from pipeline.agentic import connector_http
from tests.test_mcp_server import PREPARED, reviewed, two_people, _requests  # noqa: F401

TOKEN = 'x' * 40
H = {'Authorization': 'Bearer ' + TOKEN}
FILLED = dict(PREPARED, attached_documents={'cv': 'a' * 64, 'letter': 'b' * 64}, review_answers=[
    {'key': 'k1', 'step': 'step-1', 'question': 'Right to work in Australia?', 'value': True, 'source': 'profile'},
    {'key': 'k2', 'step': 'step-1', 'question': 'Why this role', 'value': 'I like SQL.', 'source': 'agent_draft'},
    {'key': 'k3', 'step': 'step-1', 'question': 'Skipped', 'value': None, 'source': 'unknown'}])


@pytest.fixture
def client(two_people):
    return TestClient(connector_http.create_app(token=TOKEN, person='owner'))


@pytest.fixture
def filled(two_people, monkeypatch):
    from jobwatch.apply import prepare, submit_confirm
    monkeypatch.setattr(prepare, 'latest_preparation', lambda root, app_id: dict(FILLED))
    return submit_confirm.digest(FILLED)


def test_bearer_required_everywhere(client):
    for path in ('/connector/overview', '/connector/jobs/1', '/connector/jobs/1/status', '/connector/jobs/1/review'):
        assert client.get(path).status_code == 401
        assert client.get(path, headers={'Authorization': 'Bearer ' + 'y' * 40}).status_code == 401
    assert client.post('/connector/jobs/1/submit', json={'confirm_digest': 'a', 'shown_hash': 'b'}).status_code == 401


def test_refuses_to_start_without_a_long_token():
    with pytest.raises(Exception):
        connector_http.create_app(token='short', person='owner')


def test_reads_are_for_the_configured_person_only(client):
    jobs = client.get('/connector/overview', headers=H).json()['jobs']
    assert [j['employer'] for j in jobs] == ['Acme Pty']
    assert client.get('/connector/jobs/1/status', headers=H).json()['state'] == 'draft ready'


def test_job_detail_never_carries_a_digest(filled, client):
    body = client.get('/connector/jobs/1', headers=H).json()
    assert 'submit_digest' not in body and filled not in str(body)


def test_review_shows_the_exact_form_and_keeps_the_digest_apart(filled, client):
    body = client.get('/connector/jobs/1/review', headers=H).json()
    r = body['review']
    assert body['submit_digest'] == filled and filled not in str(r)
    assert r['ready'] and r['employer'] == 'Acme Pty' and r['title'] == 'Data Analyst'
    assert [(a['question'], a['answer']) for a in r['answers']] == [('Right to work in Australia?', 'Yes'), ('Why this role', 'I like SQL.')]
    assert [(d['label'], d['file']) for d in r['documents']] == [('CV', 'cv.pdf'), ('Cover letter', 'letter.pdf')]


def test_review_not_ready_has_no_digest_and_no_hash(two_people, client):
    body = client.get('/connector/jobs/1/review', headers=H).json()      # nothing prepared on disk for this tmp person
    assert body['submit_digest'] is None and body['review']['ready'] is False and 'shown_hash' not in body['review']
    missing = client.get('/connector/jobs/99/review', headers=H).json()
    assert missing['review']['found'] is False and missing['submit_digest'] is None


def test_review_is_not_ready_after_the_owner_edited_the_form(filled, client, monkeypatch):
    import pathlib
    real_exists = pathlib.Path.exists
    monkeypatch.setattr(pathlib.Path, 'exists', lambda self: True if self.name == 'owner-review.json' else real_exists(self))
    body = client.get('/connector/jobs/1/review', headers=H).json()
    assert body['review']['reason'] == 'edited_in_browser' and body['review']['ready'] is False and body['submit_digest'] is None


def test_submit_needs_digest_and_the_hash_of_what_was_shown(filled, client):
    body = client.get('/connector/jobs/1/review', headers=H).json()
    digest, shown = body['submit_digest'], body['review']['shown_hash']
    bad = [{'confirm_digest': '', 'shown_hash': shown}, {'confirm_digest': 'a' * 64, 'shown_hash': shown},
           {'confirm_digest': digest, 'shown_hash': 'f' * 64}, {'confirm_digest': digest, 'shown_hash': ''}]
    for payload in bad:
        assert client.post('/connector/jobs/1/submit', headers=H, json=payload).status_code == 400
    assert client.post('/connector/jobs/1/submit', headers=H, json={'confirm_digest': digest}).status_code == 422
    assert _requests('owner') == []
    ok = client.post('/connector/jobs/1/submit', headers=H, json={'confirm_digest': digest, 'shown_hash': shown})
    assert ok.status_code == 200 and ok.json()['status'] == 'queued'
    assert client.post('/connector/jobs/1/submit', headers=H, json={'confirm_digest': digest, 'shown_hash': shown}).status_code == 400
    assert len(_requests('owner')) == 1


def test_a_changed_answer_changes_the_shown_hash(filled, client, monkeypatch):
    from jobwatch.apply import prepare
    shown = client.get('/connector/jobs/1/review', headers=H).json()['review']['shown_hash']
    edited = dict(FILLED, review_answers=[dict(FILLED['review_answers'][0], value=False), *FILLED['review_answers'][1:]])
    monkeypatch.setattr(prepare, 'latest_preparation', lambda root, app_id: dict(edited))
    now = client.get('/connector/jobs/1/review', headers=H).json()
    assert now['review']['shown_hash'] != shown
    r = client.post('/connector/jobs/1/submit', headers=H, json={'confirm_digest': now['submit_digest'], 'shown_hash': shown})
    assert r.status_code == 400 and r.json() == {'error': 'review_changed'}


def test_unknown_approval_is_refused(client):
    r = client.post('/connector/decide', headers=H, json={'interaction_id': 'nope', 'decision': 'approve', 'binding': 'b'})
    assert r.status_code == 400 and r.json() == {'error': 'approval_not_found'}
