from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from conftest import make_config
from jobwatch import users
from pipeline.agentic import discovery_ops as ops, incidents, service
from pipeline.agentic.api import Principal, create_api
from pipeline.agentic.api_store import APIStore, Conflict
from pipeline.agentic.chat import job_connection


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path / 'data'))
    users.create_user_dirs('fixture-a')
    users.create_user_dirs('fixture-b')
    config = make_config(tmp_path=tmp_path)
    profile = {'version': 1, 'facts': []}
    scope = SimpleNamespace(daily_assessments=40, daily_token_ceiling=2_000_000,
        model_dump=lambda **k: {'basis': ['Synthetic accounting'], 'locations': ['Victoria'],
                               'daily_assessments': 40, 'daily_token_ceiling': 2_000_000})
    monkeypatch.setattr(ops.intake, 'current_version', lambda person: profile)
    monkeypatch.setattr(ops.intake, 'discovery_scope', lambda person: scope)
    monkeypatch.setattr(service, '_capture', lambda conn, pid: ({'id': pid}, 'Synthetic full advert', 'full'))
    monkeypatch.setattr(service, '_config', lambda cfg: {'batch_seconds': 600, 'job_seconds': 300,
        'job_token_ceiling': 250_000, 'batch_token_ceiling': 2_000_000})
    return config, profile


def test_discovery_queue_is_idempotent_person_bound_and_not_a_chat(world):
    config, _ = world
    first = ops.start('fixture-a', config, 'request-1')
    assert first == ops.start('fixture-a', config, 'request-1')
    with pytest.raises(Conflict, match='discovery_busy'):
        ops.start('fixture-a', config, 'request-2')
    second_person = ops.start('fixture-b', config, 'request-1')
    assert second_person['run_id'] != first['run_id']
    with APIStore('fixture-a') as store:
        assert store.raw_run(first['run_id'])['input_json'] == '{"discovery":true}'


def test_explicit_retry_rechecks_inputs_and_releases_only_selected_incident(world, monkeypatch):
    config, profile = world
    with users.use('fixture-a'), job_connection(config, write=True) as conn:
        service.AgenticStore(conn).ensure()
        chosen = incidents.report(conn, posting_id=42, run_id='failed-42', reason='deadline_exceeded', phase='evaluation')
        other = incidents.report(conn, posting_id=43, run_id='failed-43', reason='model_unavailable', phase='evaluation')
    item = next(i for i in ops.status('fixture-a', config)['incidents'] if i['posting_id'] == 42)
    with pytest.raises(Conflict, match='retry_inputs_changed'):
        ops.start('fixture-a', config, 'bad', incident_id=chosen['incident_id'], posting_id=42, expected_context='0'*64)
    queued = ops.start('fixture-a', config, 'retry', incident_id=chosen['incident_id'], posting_id=42,
        expected_context=item['retry_context'])
    seen = []
    def assess(ids, cfg, conn, **kwargs):
        seen.extend(ids)
        assert not incidents.is_paused(conn, 42)
        assert incidents.is_paused(conn, 43)
        assert kwargs['operation'] == 'evaluate'
        return {'processed': 1}
    monkeypatch.setattr(service, 'agentic_batch_run', assess)
    with APIStore('fixture-a') as store:
        import json
        payload = json.loads(store.raw_run(queued['run_id'])['input_json'])
    assert ops.execute('fixture-a', config, queued['run_id'], payload)['processed'] == 1
    assert seen == [42]
    assert [i['incident_id'] for i in ops.status('fixture-a', config)['incidents']] == [other['incident_id']]


def test_queued_retry_rejects_changed_profile_without_releasing_pause(world):
    config, profile = world
    with users.use('fixture-a'), job_connection(config, write=True) as conn:
        service.AgenticStore(conn).ensure()
        incident = incidents.report(conn, posting_id=42, run_id='failed-42', reason='deadline_exceeded')
    item = ops.status('fixture-a', config)['incidents'][0]
    payload = {'discovery': True, 'incident_id': incident['incident_id'], 'posting_id': 42,
               'expected_context': item['retry_context']}
    profile['version'] = 2
    with pytest.raises(Conflict, match='retry_inputs_changed'):
        ops.execute('fixture-a', config, 'retry', payload)
    with users.use('fixture-a'), job_connection(config, write=True) as conn:
        assert incidents.is_paused(conn, 42)


def test_native_api_worker_executes_discovery_without_chat(world, monkeypatch):
    config, _ = world
    calls = []
    def execute(person, cfg, run_id, payload, **kwargs):
        calls.append((person, payload))
        return {'processed': 1, 'phase_seconds': {'assessment': .1}}
    monkeypatch.setattr(ops, 'execute', execute)
    token = 'a'*40
    headers = {'Authorization': 'Bearer '+token}
    with TestClient(create_api(credentials={token: Principal('fixture-a')}, config=config,
            dispatcher=lambda **kw: pytest.fail('Discovery must not enter a chatbot'))) as client:
        response = client.post('/api/agent/discovery/start', headers=headers, json={'request_id': 'native-request'})
        assert response.status_code == 202
        ident = response.json()['run_id']
        import time
        for _ in range(100):
            run = client.get('/api/agent/runs/'+ident, headers=headers).json()
            if run['state'] not in ('queued', 'running'):
                break
            time.sleep(.01)
        assert run['state'] == 'completed' and run['result']['processed'] == 1
        assert calls == [('fixture-a', {'discovery': True})]
        assert client.get('/api/agent/discovery/status').status_code == 401
        assert client.post('/api/agent/discovery/start', headers=headers,
            json={'request_id': 'x', 'person': 'fixture-b'}).status_code == 422
