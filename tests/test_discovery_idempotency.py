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
    with APIStore('fixture-a'):
        pass
    expected_skill = skill_version()
    barrier = threading.Barrier(2)
    def enqueue():
        with APIStore('fixture-a') as store:
            barrier.wait(timeout=30)
            return store.enqueue_discovery({'discovery':True}, 'same-concurrent-request', expected_skill)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = list(pool.map(lambda _: enqueue(), range(2)))
    assert one == two
    with APIStore('fixture-a') as store:
        assert store.conn.execute('SELECT COUNT(*) FROM api_runs').fetchone()[0] == 1


def test_retry_setup_failure_after_release_repauses_only_the_selected_job(world, monkeypatch):
    config, _ = world
    with users.use('fixture-a'), job_connection(config, write=True) as conn:
        service.AgenticStore(conn).ensure()
        selected = incidents.report(conn, posting_id=42, run_id='selected-failure', reason='deadline_exceeded')
        incidents.report(conn, posting_id=43, run_id='other-failure', reason='model_unavailable')
    item = next(row for row in ops.status('fixture-a', config)['incidents'] if row['posting_id'] == 42)
    reached = []

    def failed_setup(ids, config, conn, **kwargs):
        assert ids == [42] and not incidents.is_paused(conn, 42)
        assert incidents.is_paused(conn, 43)
        reached.append('setup_before_model')
        raise RuntimeError('Synthetic assessment setup failed')

    monkeypatch.setattr(service, 'agentic_batch_run', failed_setup)
    monkeypatch.setattr(service, 'configured_llm', lambda *a, **kw: pytest.fail('Setup failure must not dispatch a model'))
    payload = {'discovery': True, 'incident_id': selected['incident_id'], 'posting_id': 42,
               'expected_context': item['retry_context']}
    with pytest.raises(RuntimeError, match='Synthetic assessment setup failed'):
        ops.execute('fixture-a', config, 'setup-error', payload)
    assert reached == ['setup_before_model']
    with users.use('fixture-a'), job_connection(config, write=True) as conn:
        assert incidents.is_paused(conn, 42) and incidents.is_paused(conn, 43)
        new = next(row for row in incidents.list_incidents(conn) if row['run_id'] == 'setup-error')
        assert new['posting_id'] == 42 and new['reason'] == 'execution_failed' and new['state'] == 'paused'
        assert conn.execute('SELECT state FROM agentic_invocations WHERE run_id=?', ('setup-error',)).fetchone()[0] == 'failed'
