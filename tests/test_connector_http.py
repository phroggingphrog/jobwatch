"""The loopback JSON front: auth, per-person binding, the digest staying out of the job fields, the review content
and submit safety."""
import pytest
from fastapi.testclient import TestClient

from pipeline.agentic import connector_http
from pipeline.agentic.runtime import RuntimeErrorSafe
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
    assert client.get('/connector/overview', headers=H).json()['jobs'] == []
    jobs = client.get('/connector/applications', headers=H).json()['jobs']
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


# --- review from the current form -------------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _no_native_browser(monkeypatch):
    monkeypatch.delenv('JOBWATCH_NATIVE_BROWSER_URL', raising=False)

LIVE_FIELDS = [
    {'label': 'Full name', 'type': 'text', 'value': 'Alex Example'},
    {'label': 'Right to work in Australia?', 'type': 'checkbox', 'value': 'Selected'},
    {'label': 'Why this role', 'type': 'textarea', 'value': 'I like SQL.\n\nSecond paragraph of a long answer.'},
    {'label': 'CV', 'type': 'file', 'value': 'Alex_CV.pdf'},
    {'label': 'Cover letter', 'type': 'file', 'value': 'Letter Acme.pdf'},
    {'label': 'Password', 'type': 'password', 'value': '[private]'}]
NAMED = dict(FILLED, document_names={'cv': 'Alex_CV.pdf', 'letter': 'Letter Acme.pdf'})

class FakeLive:
    """Stands in for the native browser's review (BrowserService.review) for one person: the live fields, the form
    state they hash to, and the owner-review overlay that a rebind writes."""
    def __init__(self, prepared_module):
        self.fields, self.form_state, self.blocked, self.rebound = [dict(f) for f in LIVE_FIELDS], 'f', None, []
        self.overlay = {}
        self.prepared_module = prepared_module

    def prepared(self, root=None, app_id=None):
        return dict(NAMED, **self.overlay)

    def digest(self):
        from jobwatch.apply import submit_confirm
        return submit_confirm.digest(dict(NAMED, form_state=self.form_state))

    def read(self, person, posting_id):
        from jobwatch import users
        assert users.current() == person, 'the live read must run as the configured person'
        if self.blocked:
            return {'status': 'blocked', 'reason': self.blocked}
        recorded = self.overlay.get('form_state', 'f')
        return {'fields': [dict(f) for f in self.fields], 'review_digest': self.digest(),
                'confirmed_digest': self.digest() if recorded == self.form_state else None}

    def rebind(self, person, posting_id, digest):
        from jobwatch import users
        assert users.current() == person, 'the rebind must run as the configured person, not the default one'
        if digest != self.digest():
            raise RuntimeErrorSafe('review_changed')
        self.rebound.append(digest)
        self.overlay = {'form_state': self.form_state}

    def edit(self, label, value):
        next(f for f in self.fields if f['label'] == label)['value'] = value
        self.form_state += '+'

@pytest.fixture
def live(two_people, monkeypatch):
    from jobwatch.apply import prepare
    from pipeline.agentic import chatgpt_connector
    fake = FakeLive(prepare)
    monkeypatch.setattr(prepare, 'latest_preparation', fake.prepared)
    monkeypatch.setattr(chatgpt_connector, '_live_form', lambda: fake)
    return fake

def _review(client):
    return client.get('/connector/jobs/1/review', headers=H).json()

def _submit(client, body, review):
    return client.post('/connector/jobs/1/submit', headers=H,
                       json={'confirm_digest': body['submit_digest'] if review is None else review['submit_digest'],
                             'shown_hash': (review or body)['review']['shown_hash']})

def test_review_shows_the_current_live_form_with_original_file_names(live, client):
    body = _review(client)
    r = body['review']
    assert r['ready'] and body['submit_digest'] == live.digest()
    answers = {a['question']: a for a in r['answers']}
    assert answers['Why this role']['answer'] == 'I like SQL.\n\nSecond paragraph of a long answer.'
    assert answers['Why this role']['source'] == 'agent_draft' and answers['Full name']['source'] == 'form'
    assert 'Password' not in answers and 'CV' not in answers and 'Cover letter' not in answers
    assert [(d['label'], d['file']) for d in r['documents']] == [('CV', 'Alex_CV.pdf'), ('Cover letter', 'Letter Acme.pdf')]

def test_file_names_are_part_of_the_shown_hash(live, client, monkeypatch):
    from jobwatch.apply import prepare
    first = _review(client)['review']['shown_hash']
    monkeypatch.setattr(prepare, 'latest_preparation',
                        lambda root, app_id: dict(NAMED, document_names={'cv': 'Other.pdf', 'letter': 'Letter Acme.pdf'}))
    second = _review(client)['review']
    assert second['documents'][0]['file'] == 'Other.pdf' and second['shown_hash'] != first

def test_old_preparations_without_names_show_the_generic_names(filled, client):
    r = client.get('/connector/jobs/1/review', headers=H).json()['review']
    assert [d['file'] for d in r['documents']] == ['cv.pdf', 'letter.pdf']

def test_an_edited_form_is_reviewed_again_and_submit_needs_the_fresh_hash(live, client):
    first = _review(client)
    live.edit('Why this role', 'EDITED in the browser')
    second = _review(client)
    assert second['review']['ready'] and 'reason' not in second['review']      # no dead end
    assert {a['question']: a['answer'] for a in second['review']['answers']}['Why this role'] == 'EDITED in the browser'
    assert second['review']['shown_hash'] != first['review']['shown_hash'] and second['submit_digest'] != first['submit_digest']
    # what the person saw before the edit is refused, and nothing is rebound or queued
    assert _submit(client, first, None).status_code == 400
    mixed = client.post('/connector/jobs/1/submit', headers=H, json={
        'confirm_digest': second['submit_digest'], 'shown_hash': first['review']['shown_hash']})
    assert mixed.status_code == 400 and live.rebound == [] and _requests('owner') == []
    ok = _submit(client, second, None)
    assert ok.status_code == 200 and ok.json()['status'] == 'queued'
    assert live.rebound == [second['submit_digest']] and len(_requests('owner')) == 1
    assert _submit(client, second, None).status_code == 400 and len(_requests('owner')) == 1     # never twice

def test_an_edit_between_review_and_submit_is_refused_and_queues_nothing(live, client):
    body = _review(client)
    live.edit('Full name', 'Someone Else')
    assert _submit(client, body, None).status_code == 400 and _requests('owner') == [] and live.rebound == []

def test_an_unedited_form_needs_no_rebind(live, client):
    body = _review(client)
    assert _submit(client, body, None).json()['status'] == 'queued' and live.rebound == []

def test_the_live_form_that_cannot_be_read_is_not_ready(live, client):
    live.blocked = 'application_changed'
    body = _review(client)
    assert body['review']['ready'] is False and body['review']['reason'] == 'application_changed' and body['submit_digest'] is None
    assert 'shown_hash' not in body['review']
    live.blocked = 'weird <script> text'
    assert _review(client)['review']['reason'] == 'browser_unavailable'

def test_a_refused_submit_records_no_confirmation_of_an_edited_form(live, client):
    """After one press is queued, an edit plus a fresh review must not be rebound (confirmed) by a Submit that is
    then refused as already queued."""
    first = _review(client)
    assert _submit(client, first, None).status_code == 200
    live.edit('Why this role', 'Edited after the press was queued')
    fresh = _review(client)
    assert fresh['review']['ready'] and fresh['review']['shown_hash'] != first['review']['shown_hash']
    refused = _submit(client, fresh, None)
    assert refused.status_code == 400 and refused.json()['error'] == 'submit_already_queued'
    assert live.rebound == [] and len(_requests('owner')) == 1

def test_live_read_and_rebind_run_as_the_configured_person_not_the_default(live, two_people):
    """guest is not the default user: the native browser key is chosen by users.current(), so both calls must be scoped."""
    guest = TestClient(connector_http.create_app(token=TOKEN, person='guest'))
    body = guest.get('/connector/jobs/1/review', headers=H).json()
    assert body['review']['ready'] and body['review']['employer'] == 'Secret Co'
    live.edit('Full name', 'Edited by guest')
    fresh = guest.get('/connector/jobs/1/review', headers=H).json()
    ok = guest.post('/connector/jobs/1/submit', headers=H,
                    json={'confirm_digest': fresh['submit_digest'], 'shown_hash': fresh['review']['shown_hash']})
    assert ok.status_code == 200 and live.rebound == [fresh['submit_digest']]


def test_preparation_requires_literal_consent_and_exact_typed_inputs(client, monkeypatch):
    calls = []
    monkeypatch.setattr(connector_http.cc, 'prepare_selected', lambda person, posting_id, **kw:
                        calls.append((person, posting_id, kw)) or {'posting_id': posting_id, 'state': 'queued'})
    args = {'expected_entry_id': 'entry', 'expected_run_key': 'run', 'request_id': 'request', 'confirmed': True}
    for bad in (False, 1, 'true', None):
        assert client.post('/connector/jobs/1/prepare', headers=H, json=dict(args, confirmed=bad)).status_code == 422
    assert not calls
    assert client.post('/connector/jobs/1/prepare', headers=H, json=args).status_code == 200
    assert calls == [('owner', 1, args)]
    assert client.post('/connector/jobs/1/prepare', headers=H, json=dict(args, person='guest')).status_code == 422
