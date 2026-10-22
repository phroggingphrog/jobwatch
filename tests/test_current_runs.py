"""Stored evaluation reuse retains current canonical eligibility and approved identity."""
import pytest
from tests.test_agentic_service import SyntheticGateway
from tests.baseline_support import world
from jobwatch.llm import LLM
from jobwatch.candidate import intake
from jobwatch.preferences import PreferenceError
from pipeline.agentic import service
from jobwatch import preference_service, users


def evaluated(world):
    conn, config, bundle, add = world
    add(1)
    service.agentic_batch_run([1], config, conn, evidence_bundle=bundle,
        operation='evaluate', llm=LLM(transport=SyntheticGateway(bundle), keys=['synthetic']))
    return conn, config


def test_current_runs_reuses_stored_evaluation_without_a_model(world, monkeypatch):
    conn, config = evaluated(world)
    monkeypatch.setattr(service, 'configured_llm', lambda *a: pytest.fail('paid call'))
    identity, bundle, policy, runs = preference_service.current_runs(conn, config)
    assert len(identity) == 64 and len(runs) == 1
    row = runs[0]
    assert row.key.value == row.result['run_key'] == row.evaluation.run_key.value
    assert row.decision.route == 'draft' and row.posting['id'] == 1
    assert row.approved == intake.current_version(users.current())


def test_closed_postings_never_enter_the_preference_pool(world):
    conn, config = evaluated(world)
    conn.execute("UPDATE postings SET closed_at='2026-10-22T00:00:00Z' WHERE id=1")
    conn.commit()
    assert preference_service.current_runs(conn, config)[3] == []
    assert preference_service.pool(conn, config)[1] == []


def test_pool_held_is_explicit_and_opt_in(world, monkeypatch):
    conn, config = evaluated(world)
    original = service.gate_current
    def hold(*args, **kwargs):
        return original(*args, **kwargs).model_copy(update={'route':'hold','reason':'insufficient_evidence'})
    monkeypatch.setattr(service, 'gate_current', hold)
    assert preference_service.pool(conn, config)[1] == []
    choices = preference_service.pool(conn, config, statuses=('eligible','held'))[1]
    assert len(choices) == 1 and choices[0]['status'] == 'held' and choices[0]['eligible'] is False


def test_profile_change_during_snapshot_is_not_reused(world, monkeypatch):
    conn, config = evaluated(world)
    original = service._run_key
    old = intake.current_version(users.current())
    def change(*args, **kwargs):
        out = original(*args, **kwargs)
        monkeypatch.setattr(intake, 'current_version', lambda person: {**old, 'confirmed_at':'2099-01-01'})
        return out
    monkeypatch.setattr(service, '_run_key', change)
    with pytest.raises(PreferenceError, match='snapshot_changed'):
        preference_service.current_runs(conn, config)


def test_verification_failure_in_a_stored_artifact_is_not_an_alternative(world):
    from pathlib import Path
    conn,config=evaluated(world)
    row=preference_service.current_runs(conn,config)[3][0]
    Path(row.result['artifact_paths']['candidate']).write_text('{}')
    assert preference_service.current_runs(conn,config)[3] == []
