"""Authenticated discovery MCP transport: typed inputs and server-selected identity."""
import sys
import types

import pytest
from fastapi.testclient import TestClient

from jobwatch import config as config_module, users
from pipeline import agentic
from pipeline.agentic import connector_http
from pipeline.agentic.api_store import Conflict
from pipeline.agentic.runtime import RuntimeErrorSafe

TOKEN = 'discovery-test-' + 'x' * 40
H = {'Authorization': 'Bearer ' + TOKEN}
P = '/connector/discovery'


@pytest.fixture
def transport(monkeypatch):
    calls, issued = [], {}

    def config():
        return {'configured_person': users.current()}

    def status(person, configured):
        calls.append(('status', person, users.current(), configured))
        return {'enabled': True, 'postings': 0, 'assessments_today': 0, 'charged_tokens_today': 0,
                'scope': None, 'incidents': [{'incident_id': person + '-incident'}],
                'latest_run': None, 'invocations': []}

    def start(person, configured, request_id, **retry):
        calls.append(('start', person, users.current(), configured, request_id, retry))
        key = (person, request_id)
        return issued.setdefault(key, {'run_id': person + '-' + request_id, 'state': 'queued'})

    module = types.ModuleType('pipeline.agentic.discovery_ops')
    module.status, module.start = status, start
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(agentic, 'discovery_ops', module, raising=False)
    monkeypatch.setattr(config_module, 'load_config', config)
    a = TestClient(connector_http.create_app(token=TOKEN, person='fixture-a'))
    b = TestClient(connector_http.create_app(token=TOKEN, person='fixture-b'))
    return a, b, calls, module


def test_discovery_status_and_start_use_authenticated_person_and_person_config(transport):
    a, b, calls, _ = transport
    for client, person in ((a, 'fixture-a'), (b, 'fixture-b')):
        status = client.get(P + '/status', headers=H)
        assert status.status_code == 200
        assert status.json()['incidents'] == [{'incident_id': person + '-incident'}]
        queued = client.post(P + '/start', headers=H, json={'request_id': 'same-request'})
        assert queued.status_code == 202 and queued.json() == {'run_id': person + '-same-request', 'state': 'queued'}
        again = client.post(P + '/start', headers=H, json={'request_id': 'same-request'})
        assert again.json() == queued.json()
    assert all(call[1] == call[2] == call[3]['configured_person'] for call in calls)
    assert calls[1][-1] == {}  # Starting a pass does not silently supply retry arguments.
    assert users.current() == users.DEFAULT_USER


def test_retry_forwards_only_the_selected_incident_and_context(transport):
    a, _, calls, _ = transport
    body = {'request_id': 'retry-1', 'incident_id': 'paused-one', 'posting_id': 42,
            'expected_context': 'a' * 64}
    response = a.post(P + '/retry', headers=H, json=body)
    assert response.status_code == 202, response.text
    assert calls == [('start', 'fixture-a', 'fixture-a', {'configured_person': 'fixture-a'}, 'retry-1',
                      {'incident_id': 'paused-one', 'posting_id': 42, 'expected_context': 'a' * 64})]


def test_discovery_routes_require_authentication_and_refuse_identity_or_budget_overrides(transport):
    a, _, calls, _ = transport
    retry = {'request_id': 'r', 'incident_id': 'i', 'posting_id': 1, 'expected_context': 'a' * 64}
    assert a.get(P + '/status').status_code == 401
    for route, body in (('/start', {'request_id': 'r'}), ('/retry', retry)):
        assert a.post(P + route, json=body).status_code == 401
        for name, value in (('person', 'fixture-b'), ('token_ceiling', 99999999), ('actor', 'person')):
            assert a.post(P + route, headers=H, json={**body, name: value}).status_code == 422
    assert calls == []


def test_discovery_schema_rejects_missing_or_wrong_typed_retry_values(transport):
    a, _, calls, _ = transport
    retry = {'request_id': 'r', 'incident_id': 'i', 'posting_id': 1, 'expected_context': 'a' * 64}
    for body in ({}, {'request_id': ''}, {'request_id': 7}):
        assert a.post(P + '/start', headers=H, json=body).status_code == 422
    for name in retry:
        assert a.post(P + '/retry', headers=H, json={k:v for k,v in retry.items() if k != name}).status_code == 422
    for name, value in (('posting_id', 0), ('posting_id', '1'), ('posting_id', True),
                        ('expected_context', 'changed'), ('incident_id', '')):
        assert a.post(P + '/retry', headers=H, json={**retry, name:value}).status_code == 422
    assert calls == []


def test_discovery_conflicts_and_safe_refusals_keep_fixed_error_codes(transport):
    a, _, _, module = transport

    def conflict(*args, **kwargs):
        raise Conflict('retry_context_changed')

    module.start = conflict
    body = {'request_id': 'r', 'incident_id': 'i', 'posting_id': 1, 'expected_context': 'a' * 64}
    response = a.post(P + '/retry', headers=H, json=body)
    assert response.status_code == 409 and response.json() == {'error': 'retry_context_changed'}

    def refused(*args, **kwargs):
        raise RuntimeErrorSafe('scope_required')

    module.start = refused
    response = a.post(P + '/start', headers=H, json={'request_id':'r'})
    assert response.status_code == 400 and response.json() == {'error': 'scope_required'}
