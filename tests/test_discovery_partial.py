import time

from fastapi.testclient import TestClient

from jobwatch import users
from pipeline.agentic import execution, incidents
from pipeline.agentic.api import Principal, create_api
from pipeline.agentic.api_store import APIStore
from pipeline.agentic.chat import job_connection
from tests.test_discovery_operations import world  # noqa: F401


def test_outer_deadline_retains_returned_discovery_summary_and_usage(world, monkeypatch):
    config, _ = world

    def return_summary(person, cfg, run_id, payload, **kwargs):
        with users.use(person), job_connection(cfg, write=True) as conn:
            incidents.begin_run(conn, run_id)
            incidents.end_run(conn, run_id, state='completed')
        current = execution.current()
        current.calls = 3
        current.charged_tokens = 1234
        current.actual_tokens = 1100
        current.deadline = time.monotonic() - 1
        return {'processed': 1, 'archived': 1, 'phase_seconds': {'assessment': .1}}

    monkeypatch.setattr('pipeline.agentic.discovery_ops.execute', return_summary)
    token = 'a' * 40
    headers = {'Authorization': 'Bearer ' + token}
    with TestClient(create_api(credentials={token: Principal('fixture-a')}, config=config)) as client:
        started = client.post('/api/agent/discovery/start', headers=headers,
                              json={'request_id': 'partial-deadline'})
        assert started.status_code == 202
        ident = started.json()['run_id']
        for _ in range(200):
            run = client.get('/api/agent/runs/' + ident, headers=headers).json()
            if run['state'] not in ('queued', 'running'):
                break
            time.sleep(.01)
        assert run['state'] == 'failed'
        assert run['error'] == 'deadline_exceeded'
        assert run['result'] == {
            'processed': 1,
            'archived': 1,
            'phase_seconds': {'assessment': .1},
            'usage': {'model_calls': 3, 'charged_tokens': 1234,
                      'actual_tokens': 1100, 'unknown_usage_calls': 0},
        }
        assert run['interactions'] == []
        assert run['artifacts'] == []

    with APIStore('fixture-a') as store:
        assert store.raw_run(ident)['state'] == 'failed'
    with users.use('fixture-a'), job_connection(config) as conn:
        state = conn.execute('SELECT state FROM agentic_invocations WHERE run_id=?', (ident,)).fetchone()
        assert state[0] == 'failed'
