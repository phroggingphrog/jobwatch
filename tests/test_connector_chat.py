"""Direct MCP onboarding over authenticated HTTP, using real canonical intake operations."""
import time

import pytest
from fastapi.testclient import TestClient

from jobwatch.util import model_choice as model_choice
from jobwatch import users
from jobwatch.candidate import intake
from pipeline.agentic import chatgpt_connector, connector_http, connector_onboarding
from tests.test_profile_api import CV, FakeLLM

TOKEN = 'x' * 40
H = {'Authorization': 'Bearer ' + TOKEN}
P = '/connector/onboarding'


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(model_choice, 'SERVER_URL', 'http://127.0.0.1:20128/v1')
    monkeypatch.setattr(model_choice, 'get_model', lambda role: 'claude/sonnet')
    for person in ('fixture-a', 'fixture-b'):
        users.create_user_dirs(person)
        model_choice.set_models({'reader': 'claude/sonnet'}, person)
    fake = FakeLLM()
    fake.next = {'facts': [{'section': 'experience', 'value': 'Accounts Assistant, Ledger Co', 'basis': 'evidence',
                            'upload': 1, 'sources': [{'line': 5, 'quote': 'Ledger Co, Accounts Assistant, 2021 - 2023'}]}],
                 'questions': [{'section': 'work_rights', 'text': 'What are your work rights?', 'why': 'Matching.'}]}
    config = {'agentic': {'enabled': False, 'batch_token_ceiling': 2000000}}
    monkeypatch.setattr(connector_onboarding, 'load_config', lambda: config)
    monkeypatch.setattr(connector_onboarding.service, 'configured_llm', lambda cfg: fake)
    monkeypatch.setattr(chatgpt_connector, 'dispatch', lambda **kw: pytest.fail('Onboarding must not call chat dispatch'))
    with users.use('fixture-a'):
        upload = intake.save_upload('fixture-a', 'cv.txt', CV, 'cv')
    client = TestClient(connector_http.create_app(token=TOKEN, person='fixture-a'))
    other = TestClient(connector_http.create_app(token=TOKEN, person='fixture-b'))
    return client, other, upload, config, fake


def draft(world):
    client, _, upload, _, _ = world
    reply = client.post(P + '/start', headers=H, json={'upload_ids': [upload['upload_id']]})
    assert reply.status_code == 200, reply.text
    assert reply.json()['status'] == 'parsing'
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        body = client.get(P + '/status', headers=H).json()
        if body['status'] != 'parsing':
            assert body['status'] == 'draft' and not body['proposal']['parse_error'], body
            return body['proposal']
        time.sleep(.01)
    pytest.fail('Synthetic parsing did not finish')


def review(world, proposal):
    response = world[0].post(P + '/review', headers=H, json={'proposal_id': proposal['id']})
    assert response.status_code == 200, response.text
    return response.json()


def approval(shown):
    return {'proposal_id': shown['proposal']['id'], 'proposal_digest': shown['proposal_digest'],
            'scope_digest': shown['scope_digest'], 'confirmed': True}


def test_direct_onboarding_reads_edits_answers_reviews_and_confirms_without_chat(world):
    client, _, _, _, fake = world
    assert client.get(P + '/status', headers=H).json()['status'] == 'not_started'
    prop = draft(world)
    count = len(fake.calls)
    edit = client.post(P + '/update', headers=H, json={'proposal_id': prop['id'], 'expected_revision': prop['revision'],
        'edits': [{'op': 'add', 'section': 'career_focus', 'value': 'Accounting'},
                  {'op': 'add', 'section': 'location', 'value': 'Victoria'}]})
    assert edit.status_code == 200, edit.text
    prop = edit.json()['proposal']
    qid = next(q['id'] for q in prop['questions'] if q['section'] == 'work_rights')
    answered = client.post(P + '/answer', headers=H, json={'proposal_id': prop['id'],
        'expected_revision': prop['revision'], 'question_id': qid, 'text': 'Citizen'})
    assert answered.status_code == 200 and qid not in [q['id'] for q in answered.json()['proposal']['questions']]
    shown = review(world, answered.json()['proposal'])
    assert shown['scope']['basis'] == ['Accounting'] and shown['scope']['locations'] == ['Victoria']
    assert shown['proposal']['facts'] and shown['does_not_authorise'] == ['document_preparation', 'employer_messages', 'submission']
    confirmed = client.post(P + '/confirm', headers=H, json=approval(shown))
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()
    assert result['status'] == 'confirmed' and result['version'] == 1 and result['discovery_enabled'] is True
    assert result['discovery'] == shown['scope']
    current = client.get(P + '/status', headers=H).json()
    assert current['status'] == 'confirmed' and current['proposal'] is None and current['current_version']['version'] == 1
    assert len(fake.calls) == count
    assert intake.current_version('fixture-b') is None


def test_confirm_requires_explicit_true_and_exact_draft_and_scope(world):
    client = world[0]
    prop = draft(world)
    shown = review(world, prop)
    body = approval(shown)
    for value in (False, 1, 'true', None):
        assert client.post(P + '/confirm', headers=H, json={**body, 'confirmed': value}).status_code == 422
    assert client.post(P + '/confirm', headers=H, json={k:v for k,v in body.items() if k != 'confirmed'}).status_code == 422
    assert client.post(P + '/confirm', headers=H, json={**body, 'person': 'fixture-a'}).status_code == 422
    stale = client.post(P + '/confirm', headers=H, json={**body, 'proposal_digest': '0' * 64})
    assert stale.status_code == 409 and stale.json() == {'error': 'proposal_changed'}
    scope = client.post(P + '/confirm', headers=H, json={**body, 'scope_digest': '0' * 64})
    assert scope.status_code == 409 and scope.json() == {'error': 'scope_changed'}
    client.post(P + '/update', headers=H, json={'proposal_id': prop['id'], 'expected_revision': prop['revision'],
        'edits': [{'op': 'add', 'section': 'location', 'value': 'Melbourne'}]})
    changed = client.post(P + '/confirm', headers=H, json=body)
    assert changed.status_code == 409 and changed.json() == {'error': 'proposal_changed'}
    assert intake.current_version('fixture-a') is None


def test_scope_configuration_change_invalidates_the_review(world):
    client, _, _, config, _ = world
    shown = review(world, draft(world))
    config['agentic']['batch_token_ceiling'] += 1
    response = client.post(P + '/confirm', headers=H, json=approval(shown))
    assert response.status_code == 409 and response.json() == {'error': 'scope_changed'}
    assert intake.current_version('fixture-a') is None


def test_auth_account_isolation_and_removed_chat_routes(world):
    client, other, upload, _, _ = world
    prop = draft(world)
    shown = review(world, prop)
    assert client.get(P + '/status').status_code == 401
    assert other.get(P + '/status', headers=H).json()['status'] == 'not_started'
    for route, body in [('/start', {'upload_ids': [upload['upload_id']]}),
                        ('/review', {'proposal_id': prop['id']}), ('/confirm', approval(shown)),
                        ('/update', {'proposal_id': prop['id'], 'expected_revision': prop['revision'],
                                     'edits': [{'op':'add','section':'location','value':'Sydney'}]})]:
        response = other.post(P + route, headers=H, json=body)
        assert response.status_code == 404, (route, response.text)
    for route in ('start', 'continue', 'decide'):
        assert client.post('/connector/chat/' + route, headers=H, json={}).status_code == 404
