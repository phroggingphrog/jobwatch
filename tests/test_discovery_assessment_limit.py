"""Invocation limits bound assessment selection without changing person settings."""
import copy
import json
import time

import pytest
from fastapi.testclient import TestClient

from jobwatch import users
from jobwatch.candidate import intake
from pipeline import store as pipeline_store
from pipeline.agentic import discovery, discovery_ops, discovery_settings, execution, service
from pipeline.agentic.api import Principal, create_api
from pipeline.agentic.api_store import APIStore, Conflict
from pipeline.agentic.contracts import AgenticError
from pipeline.nodes import ingest
from tests.test_agentic_service import world  # noqa: F401


@pytest.fixture
def reader(world, monkeypatch):
    conn, config, bundle, add = world
    pipeline_store.ensure(conn)
    for ident in (42, 43, 44):
        add(ident)
        pipeline_store.admit(conn, ident, str(ident), {})
    conn.commit()
    calls = []
    monkeypatch.setattr(ingest, 'run', lambda *a, **kw: calls.append(('ingest', users.current())))
    monkeypatch.setattr(discovery, 'enforce_exclusions', lambda *a, **kw: [])
    monkeypatch.setattr(discovery, 'reconsider', lambda *a, **kw: None)
    monkeypatch.setattr(discovery, 'screen_step', lambda *a, **kw: {})
    monkeypatch.setattr(service, '_near_duplicates', lambda *a, **kw: None)
    monkeypatch.setattr(service, '_without_completed', lambda c, cfg, ids: ids)
    monkeypatch.setattr(service, '_target_first', lambda c, cfg, ids: ids)
    monkeypatch.setattr(service, '_refresh_shortlist', lambda *a, **kw: {})

    def assess(ids, cfg, c, **kwargs):
        calls.append(('assessment', users.current(), list(ids)))
        return {'processed': len(ids)}

    monkeypatch.setattr(service, 'agentic_batch_run', assess)
    return conn, config, calls


def test_one_assessment_defers_remaining_without_changing_unlimited_or_profile(reader):
    conn, config, calls = reader
    person = users.current()
    discovery_settings.set_settings(person, config, None, job_token_ceiling=None,
                                   job_seconds=None, job_max_turns=None)
    before_limits = discovery_settings.get_settings(person, config)
    before_profile = copy.deepcopy(intake.current_version(person))
    before_states = [tuple(row) for row in conn.execute('SELECT * FROM pipeline_state ORDER BY posting_id')]
    result = service.after_collect(conn, config, max_assessments=1)
    assert calls == [('ingest', person), ('assessment', person, [42])]
    assert result['processed'] == 1 and result['assessment_limit_deferred'] == [43, 44]
    assert discovery_settings.get_settings(person, config) == before_limits
    assert before_limits['daily_token_ceiling'] is None and before_limits['job_max_turns'] is None
    assert intake.current_version(person) == before_profile
    assert [tuple(row) for row in conn.execute('SELECT * FROM pipeline_state ORDER BY posting_id')] == before_states


@pytest.mark.parametrize('controls', [{}, {'max_assessments': 20}])
def test_default_selection_and_supported_upper_bound(reader, controls):
    conn, config, calls = reader
    result = service.after_collect(conn, config, **controls)
    assert calls[-1][2] == [42, 43, 44]
    assert result['processed'] == 3 and 'assessment_limit_deferred' not in result


def test_assessment_limit_and_daily_allowance_deferrals_stay_distinct(reader, monkeypatch):
    conn, config, calls = reader
    scope = intake.discovery_scope(users.current())
    monkeypatch.setattr(intake, 'scope_state', lambda person: (scope.model_copy(update={'daily_assessments': 2}), 'ok'))
    result = service.after_collect(conn, config, max_assessments=1)
    assert calls[-1][2] == [42]
    assert result['assessment_limit_deferred'] == [43]
    assert result['daily_budget_deferred'] == [44]


def test_native_reader_retains_limit_when_creating_invocation(reader, monkeypatch):
    conn, config, calls = reader
    config.settings['pipeline']['agentic']['autonomous_evaluation'] = True
    monkeypatch.setattr('pipeline.agentic.candidate_digest.current_digest', lambda *a, **kw: object())
    monkeypatch.setattr(service, 'configured_llm', lambda *a, **kw: pytest.fail('Warm digest must not dispatch'))
    assert execution.current() is None
    result = service.after_collect(conn, config, max_assessments=1)
    assert result['assessment_limit_deferred'] == [43, 44]
    assert calls[-1][2] == [42]
    assert execution.current() is None


@pytest.mark.parametrize('limit', [0, -1, 21, True, False, 1.0, '1'])
def test_invalid_reader_limit_dispatches_no_work(reader, limit):
    conn, config, calls = reader
    with pytest.raises(AgenticError, match='invalid_max_assessments'):
        service.after_collect(conn, config, max_assessments=limit)
    with pytest.raises(AgenticError, match='invalid_max_assessments'):
        discovery_ops.start(users.current(), config, 'invalid-direct', max_assessments=limit)
    with pytest.raises(AgenticError, match='invalid_max_assessments'):
        discovery_ops.execute(users.current(), config, 'invalid-queued',
                              {'discovery': True, 'max_assessments': limit})
    assert calls == []


def test_limit_is_bound_to_receipt_and_person(reader):
    _, config, _ = reader
    person = users.current()
    first = discovery_ops.start(person, config, 'bounded-receipt', max_assessments=1)
    assert discovery_ops.start(person, config, 'bounded-receipt', max_assessments=1) == first
    for limit in (None, 2):
        with pytest.raises(Conflict, match='idempotency_conflict'):
            discovery_ops.start(person, config, 'bounded-receipt', max_assessments=limit)
    with APIStore(person) as queue:
        assert json.loads(queue.raw_run(first['run_id'])['input_json']) == {'discovery': True, 'max_assessments': 1}
        queue.finish(first['run_id'], {'processed': 1})
    replay = discovery_ops.start(person, config, 'bounded-receipt', max_assessments=1)
    assert replay == {'run_id': first['run_id'], 'state': 'completed'}
    assert discovery_ops.start(person, config, 'unbounded-receipt')['run_id'] != first['run_id']
    other = 'synthetic-other'
    users.create_user_dirs(other)
    with users.use(other):
        from tests.test_agentic_service import confirm_discovery
        confirm_discovery(config)
    second = discovery_ops.start(other, config, 'bounded-receipt', max_assessments=2)
    assert second['run_id'] != first['run_id']


def test_authenticated_bounded_queue_reaches_reader_with_all_invocation_costs(reader, monkeypatch):
    conn, config, calls = reader
    person = users.current()
    token = 's' * 40
    headers = {'Authorization': 'Bearer ' + token}

    def charge(tokens):
        invocation = execution.current()
        reserve = invocation.reserve('deepseek-flash', 'evaluator', 1, tokens)
        invocation.settle(reserve, {'prompt_tokens': tokens, 'completion_tokens': 0})

    def prepare(*a, **kw):
        calls.append(('ingest', users.current()))
        charge(11)

    def assess(ids, cfg, c, **kw):
        calls.append(('assessment', users.current(), list(ids)))
        charge(17)
        return {'processed': len(ids)}

    monkeypatch.setattr(ingest, 'run', prepare)
    monkeypatch.setattr(service, 'agentic_batch_run', assess)
    other_token = 'b' * 40
    with TestClient(create_api(config=config, credentials={token: Principal(person),
                                                          other_token: Principal('synthetic-other')})) as client:
        assert client.post('/api/agent/discovery/start', json={'request_id': 'unauth', 'max_assessments': 1}).status_code == 401
        for limit in (0, -1, 21, True, '1', 1.0):
            assert client.post('/api/agent/discovery/start', headers=headers,
                json={'request_id': 'invalid', 'max_assessments': limit}).status_code == 422
        assert calls == []
        assert client.post('/api/agent/discovery/start', headers=headers,
            json={'request_id': 'invalid-person', 'max_assessments': 1, 'person': 'synthetic-other'}).status_code == 422
        response = client.post('/api/agent/discovery/start', headers=headers,
            json={'request_id': 'bounded-http', 'max_assessments': 1})
        assert response.status_code == 202
        run_id = response.json()['run_id']
        assert client.get('/api/agent/runs/' + run_id,
            headers={'Authorization': 'Bearer ' + other_token}).status_code == 404
        for _ in range(500):
            run = client.get('/api/agent/runs/' + run_id, headers=headers).json()
            if run['state'] not in ('queued', 'running'):
                break
            time.sleep(.01)
        assert run['state'] == 'completed', run
        assert run['result']['processed'] == 1
        assert run['result']['assessment_limit_deferred'] == [43, 44]
        assert run['result']['usage'] == {'model_calls': 2, 'actual_tokens': 28,
                                        'charged_tokens': 28, 'unknown_usage_calls': 0}
        assert client.post('/api/agent/discovery/start', headers=headers,
            json={'request_id': 'bounded-http', 'max_assessments': 2}).status_code == 409
    assert calls == [('ingest', person), ('assessment', person, [42])]
