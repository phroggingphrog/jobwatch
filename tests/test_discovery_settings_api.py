"""Authenticated native controls for a person's operational token allowance."""
from fastapi.testclient import TestClient

from pipeline.agentic.api import Principal, create_api
from pipeline.agentic import discovery_ops as ops, incidents, service
from pipeline.agentic.api_store import Conflict
from pipeline.agentic.chat import job_connection
from jobwatch import users
import pytest
from tests.test_discovery_operations import world  # noqa: F401


def test_native_settings_persist_unlimited_without_accepting_client_identity(world):
    config, profile = world
    token_a, token_b = 'a'*40, 'b'*40
    headers_a, headers_b = {'Authorization': 'Bearer '+token_a}, {'Authorization': 'Bearer '+token_b}
    credentials = {token_a: Principal('fixture-a'), token_b: Principal('fixture-b')}
    with TestClient(create_api(credentials=credentials, config=config)) as client:
        path = '/api/agent/discovery/settings'
        assert client.get(path).status_code == 401
        assert client.get(path, headers=headers_a).json()['daily_token_ceiling'] == 2_000_000
        assert client.post(path, headers=headers_a, json={'daily_token_ceiling': None}).json()['daily_token_ceiling'] is None
        assert client.get(path, headers=headers_a).json()['daily_token_ceiling'] is None
        assert client.get(path, headers=headers_b).json()['daily_token_ceiling'] == 2_000_000
        for body in ({'daily_token_ceiling': -1}, {'daily_token_ceiling': False},
                     {'daily_token_ceiling': None, 'person': 'fixture-b'}):
            assert client.post(path, headers=headers_a, json=body).status_code == 422
    assert profile['version'] == 1


def test_queued_retry_refuses_changed_budget_configuration(world):
    config, _ = world
    with users.use('fixture-a'), job_connection(config, write=True) as conn:
        service.AgenticStore(conn).ensure()
        incident = incidents.report(conn, posting_id=42, run_id='previous', reason='model_unavailable')
    context = ops.status('fixture-a', config)['incidents'][0]['retry_context']
    payload = {'discovery': True, 'incident_id': incident['incident_id'], 'posting_id': 42,
               'expected_context': context}
    ops.set_settings('fixture-a', config, None)
    with pytest.raises(Conflict, match='retry_inputs_changed'):
        ops.execute('fixture-a', config, 'queued-before-setting-change', payload)
    with users.use('fixture-a'), job_connection(config, write=True) as conn:
        assert incidents.is_paused(conn, 42)
