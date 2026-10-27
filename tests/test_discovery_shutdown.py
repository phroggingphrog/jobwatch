"""Offline worker shutdown and CLI failure visibility regressions."""
import threading
import time

import pytest
from fastapi.testclient import TestClient

from jobwatch import cli, users
from pipeline.agentic import discovery_ops, execution, incidents, service
from pipeline.agentic.api import Principal, create_api
from pipeline.agentic.api_store import APIStore
from pipeline.agentic.chat import job_connection
from tests.test_discovery_operations import world  # noqa: F401


@pytest.mark.parametrize('user_cancel', [False, True], ids=['shutdown', 'user-cancel'])
def test_active_discovery_cancellation_retains_posting_after_registry_closes(world, monkeypatch, user_cancel):
    config, _ = world
    started = threading.Event()
    def assess(conn, cfg, *, run_id, **kwargs):
        incidents.mark_phase(conn, run_id, 'assessment', posting_id=42)
        started.set()
        until = time.monotonic()+5
        while time.monotonic() < until:
            execution.current().check()
            time.sleep(.01)
        pytest.fail('Cancellation was not delivered')
    monkeypatch.setattr(service, 'after_collect', assess)
    token = 'a'*40
    headers = {'Authorization': 'Bearer '+token}
    with TestClient(create_api(credentials={token: Principal('fixture-a')}, config=config)) as client:
        response = client.post('/api/agent/discovery/start', headers=headers, json={'request_id': 'shutdown-check'})
        assert response.status_code == 202
        ident = response.json()['run_id']
        assert started.wait(3)
        if user_cancel:
            assert client.post('/api/agent/runs/'+ident+'/cancel', headers=headers).status_code == 202
            for _ in range(100):
                if client.get('/api/agent/runs/'+ident, headers=headers).json()['state'] == 'cancelled':
                    break
                time.sleep(.01)
            else:
                pytest.fail('User cancellation did not complete')
    with APIStore('fixture-a') as store:
        row = store.raw_run(ident)
        assert row['state'] == ('cancelled' if user_cancel else 'interrupted')
        assert row['error'] == ('cancelled' if user_cancel else 'worker_interrupted')
    with users.use('fixture-a'), job_connection(config, write=True) as conn:
        registry = conn.execute('SELECT state,posting_id FROM agentic_invocations WHERE run_id=?', (ident,)).fetchone()
        assert registry[0] == 'failed' and registry[1] == 42
        failures = incidents.list_incidents(conn)
        if user_cancel:
            assert failures == []
        else:
            assert len(failures) == 1
            assert failures[0]['reason'] == 'worker_interrupted' and failures[0]['posting_id'] == 42
            assert incidents.is_paused(conn, 42)


@pytest.mark.parametrize('command', ['read', 'run'])
def test_cli_outer_exception_marks_registry_failed(world, monkeypatch, command):
    from jobwatch import expiry, pipeline, profile_check
    config, _ = world
    monkeypatch.setattr(cli, 'load_config', lambda *a: config)
    monkeypatch.setattr(cli, '_extensions', lambda: [])
    monkeypatch.setattr(cli.discovery_gate, 'allowed', lambda cmd: True)
    monkeypatch.setattr(profile_check, 'check', lambda: [])
    def broken(*args, **kwargs):
        raise OSError('synthetic')
    monkeypatch.setattr(expiry, 'sweep', broken)
    monkeypatch.setattr(pipeline, 'run', broken)
    with users.use('fixture-a'), pytest.raises(OSError, match='synthetic'):
        cli._main([command])
    with users.use('fixture-a'), job_connection(config, write=True) as conn:
        assert conn.execute('SELECT state FROM agentic_invocations').fetchone()[0] == 'failed'
        assert len(incidents.list_incidents(conn)) == 1
