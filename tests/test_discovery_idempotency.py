"""A lost admission response must be recoverable after its reviewed inputs change."""
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from jobwatch import users
from pipeline.agentic import discovery_ops as ops, incidents, service
from pipeline.agentic.api_store import APIStore, Conflict
from pipeline.agentic.chat import job_connection, skill_version
from tests.test_discovery_operations import world  # noqa: F401


def test_retry_replay_returns_admitted_run_after_release_and_profile_change(world, monkeypatch):
    config, profile = world
    with users.use('fixture-a'), job_connection(config, write=True) as conn:
        service.AgenticStore(conn).ensure()
        incident = incidents.report(conn, posting_id=42, run_id='failed-job', reason='deadline_exceeded')
    item = ops.status('fixture-a', config)['incidents'][0]
    args = dict(incident_id=incident['incident_id'], posting_id=42, expected_context=item['retry_context'])
    first = ops.start('fixture-a', config, 'lost-retry-response', **args)
    with users.use('fixture-a'), job_connection(config, write=True) as conn:
        incidents.release(conn, incident['incident_id'], 42)
    with APIStore('fixture-a') as store:
        store.finish(first['run_id'], {'processed': 1})
    profile['version'] = 2
    monkeypatch.setattr(ops.intake, 'discovery_scope', lambda person: None)
    repeated = ops.start('fixture-a', config, 'lost-retry-response', **args)
    assert repeated == {'run_id': first['run_id'], 'state': 'completed'}
    with APIStore('fixture-a') as store:
        assert store.conn.execute('SELECT COUNT(*) FROM api_runs').fetchone()[0] == 1
    with pytest.raises(Conflict, match='idempotency_conflict'):
        ops.start('fixture-a', config, 'lost-retry-response', **{**args, 'posting_id':43})
    with pytest.raises(Conflict, match='profile_not_ready'):
        ops.start('fixture-a', config, 'new-retry-request', **args)


def test_normal_start_replay_does_not_require_a_still_confirmed_profile(world, monkeypatch):
    config, _ = world
    first = ops.start('fixture-a', config, 'normal-start')
    monkeypatch.setattr(ops.intake, 'discovery_scope', lambda person: None)
    assert ops.start('fixture-a', config, 'normal-start') == first
    with pytest.raises(Conflict, match='idempotency_conflict'):
        ops.start('fixture-a', config, 'normal-start', incident_id='different-operation',
                  posting_id=42, expected_context='a' * 64)


def test_discovery_admission_remains_atomic_for_concurrent_identical_requests(world):
    barrier = threading.Barrier(2)
    def enqueue():
        with APIStore('fixture-a') as store:
            barrier.wait(timeout=5)
            return store.enqueue_discovery({'discovery':True}, 'same-concurrent-request', skill_version())
    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = list(pool.map(lambda _: enqueue(), range(2)))
    assert one == two
    with APIStore('fixture-a') as store:
        assert store.conn.execute('SELECT COUNT(*) FROM api_runs').fetchone()[0] == 1
