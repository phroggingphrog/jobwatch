"""Reuse requires the synthetic evaluation and candidate artifacts to remain intact."""
import hashlib
import json
from pathlib import Path

import pytest

from pipeline.agentic import service
from pipeline.agentic.persistence import latest_result
from jobwatch.util.llm import LLM
from tests.test_agentic_service import SyntheticGateway
from tests.baseline_support import frozen, world  # noqa: F401
from tests.test_shortlist_scheduling import inputs


@pytest.fixture
def native_completed(world, monkeypatch):
    from tests.test_candidate_digest import inputs as digest_inputs, budget, transport
    from pipeline.agentic.candidate_digest import ensure_digest
    from pipeline.agentic.evaluator import evaluate_job

    conn, config, bundle, add = world
    config.settings['pipeline']['agentic']['autonomous_evaluation'] = True
    add(42)
    digest_conn, kwargs = digest_inputs(world)
    transport(monkeypatch, bundle)
    ensure_digest(digest_conn, **kwargs, budget=budget(), llm=object())

    def synthetic_evaluation(key, ad, budget, llm, **kwargs):
        for name in ('source_conn', 'posting', 'candidate_digest'):
            kwargs.pop(name)
        return evaluate_job(key, ad, budget, llm, **kwargs)

    monkeypatch.setattr('pipeline.agentic.autonomous.evaluate_posting', synthetic_evaluation)
    service.agentic_batch_run([42], config, conn, evidence_bundle=bundle,
        llm=LLM(transport=SyntheticGateway(bundle), keys=['synthetic']), operation='evaluate')
    cfg, policy = service._config(config), service.default_policy()
    captured = service._capture(conn, 42)
    reference = service.load_inputs(bundle, cfg)
    key = service._run_key(42, captured, bundle, policy, cfg, reference, conn=conn)
    return conn, captured, key, service.decision_policy_for(config)


def test_native_valid_evaluation_is_reused(native_completed):
    assert service._evaluation_current(native_completed[0], 42, *native_completed[1:])


def test_legacy_valid_evaluation_is_reused(frozen):
    assert current(frozen)


def current(frozen):
    captured, key, policy = inputs(frozen)
    return service._evaluation_current(frozen.conn, 42, captured, key, policy)


def artifact_row(frozen, kind):
    return frozen.conn.execute('SELECT path,run_key FROM agentic_artifacts WHERE kind=? AND run_key='
        '(SELECT run_key FROM agentic_runs WHERE posting_id=42 ORDER BY generation DESC LIMIT 1)', (kind,)).fetchone()


def replace_artifact(frozen, kind, payload):
    path, run_key = artifact_row(frozen, kind)
    raw = json.dumps(payload).encode()
    Path(path).write_bytes(raw)
    frozen.conn.execute('UPDATE agentic_artifacts SET sha256=? WHERE run_key=? AND kind=?',
                        (hashlib.sha256(raw).hexdigest(), run_key, kind))
    frozen.conn.commit()


@pytest.mark.parametrize('kind', ['evaluation', 'candidate'])
def test_missing_artifact_is_not_reused(frozen, kind):
    assert current(frozen)
    _, run_key = artifact_row(frozen, kind)
    frozen.conn.execute('DELETE FROM agentic_artifacts WHERE run_key=? AND kind=?', (run_key, kind))
    frozen.conn.commit()
    assert not current(frozen)


@pytest.mark.parametrize('kind', ['evaluation', 'candidate'])
def test_corrupt_artifact_is_not_reused(frozen, kind):
    assert current(frozen)
    path, _ = artifact_row(frozen, kind)
    Path(path).write_bytes(b'corrupt')
    assert not current(frozen)


@pytest.mark.parametrize('kind', ['evaluation', 'candidate'])
def test_valid_json_with_invalid_schema_is_not_reused(frozen, kind):
    assert current(frozen)
    replace_artifact(frozen, kind, {'invalid': True})
    assert not current(frozen)


def test_candidate_with_wrong_evidence_hash_is_not_reused(frozen):
    assert current(frozen)
    path, _ = artifact_row(frozen, 'candidate')
    payload = json.loads(Path(path).read_bytes())
    payload['evidence_hash'] = 'f' * 64
    replace_artifact(frozen, 'candidate', payload)
    assert not current(frozen)


@pytest.mark.parametrize('kind', ['evaluation', 'candidate'])
def test_valid_artifact_bound_to_another_run_is_not_reused(frozen, kind):
    assert current(frozen)
    path, _ = artifact_row(frozen, kind)
    payload = json.loads(Path(path).read_bytes())
    if kind == 'evaluation':
        payload['run_key']['posting_id'] += 1
    else:
        payload['run_key'] = 'f' * 64
    replace_artifact(frozen, kind, payload)
    assert not current(frozen)


@pytest.mark.parametrize('kind', ['evaluation', 'candidate'])
def test_evaluated_projection_requires_saved_artifacts(frozen, kind):
    assert latest_result(frozen.conn, 42)['status'] == 'evaluated'
    _, run_key = artifact_row(frozen, kind)
    frozen.conn.execute('DELETE FROM agentic_artifacts WHERE run_key=? AND kind=?', (run_key, kind))
    frozen.conn.commit()
    result = latest_result(frozen.conn, 42, parse=frozenset())
    assert result['stored_status'] == 'evaluated'
    assert (result['status'], result['reason']) == ('held', 'artifact_invalid')


@pytest.mark.parametrize('kind', ['evaluation', 'candidate'])
def test_evaluated_projection_refuses_invalid_schema(frozen, kind):
    replace_artifact(frozen, kind, {'invalid': True})
    result = latest_result(frozen.conn, 42, parse=frozenset())
    assert (result['status'], result['reason']) == ('held', 'artifact_invalid')


@pytest.mark.parametrize('kind', ['evaluation', 'candidate'])
def test_evaluated_projection_refuses_wrong_bindings(frozen, kind):
    path, _ = artifact_row(frozen, kind)
    payload = json.loads(Path(path).read_bytes())
    if kind == 'evaluation':
        payload['run_key']['posting_id'] += 1
    else:
        payload['evidence_hash'] = 'f' * 64
    replace_artifact(frozen, kind, payload)
    result = latest_result(frozen.conn, 42, parse=frozenset())
    assert (result['status'], result['reason']) == ('held', 'artifact_invalid')
