"""Job-independent evidence assessments survive separate discovery batches."""
from pathlib import Path
import sqlite3

from jobwatch.util.llm import LLM
from pipeline.agentic import service
from pipeline.agentic.persistence import PersistenceAdapter, latest_result
from pipeline.agentic.store import AgenticStore
from tests.test_agentic_service import SyntheticGateway, world  # noqa: F401


def test_separate_jobs_reuse_completed_candidate_assessment_without_repaying(world, monkeypatch):
    conn, config, bundle, add = world
    add(42); add(43)
    gateway = SyntheticGateway(bundle)
    llm = LLM(transport=gateway, keys=['synthetic'])
    service.run_agentic_job(42, config, conn, evidence_bundle=bundle, llm=llm, operation='evaluate')
    assert latest_result(conn, 42)['reason'] == 'evaluation_complete'
    before = dict(conn.execute('SELECT batch_id,charged FROM agentic_batches'))
    monkeypatch.setattr(service, 'evaluate_candidate',
        lambda *a, **k: (_ for _ in ()).throw(AssertionError('Candidate assessment repeated')))
    service.run_agentic_job(43, config, conn, evidence_bundle=bundle, llm=llm,
                            candidate_cache={}, operation='evaluate')
    assert latest_result(conn, 43)['reason'] == 'evaluation_complete'
    after = dict(conn.execute('SELECT batch_id,charged FROM agentic_batches'))
    assert all(after[ident] == charge for ident, charge in before.items())
    assert conn.execute("SELECT COUNT(*) FROM agentic_artifacts WHERE kind='candidate'").fetchone()[0] == 2


def test_reusable_candidate_refuses_stale_identity_and_corrupt_artifact(world):
    conn, config, bundle, add = world
    add(42); add(43)
    llm = LLM(transport=SyntheticGateway(bundle), keys=['synthetic'])
    service.run_agentic_job(42, config, conn, evidence_bundle=bundle, llm=llm, operation='evaluate')
    adapter = PersistenceAdapter(conn, AgenticStore(conn))
    policy = service.default_policy()
    key = service._run_key(43, service._capture(conn, 43), bundle, policy, service._config(config))
    assert service._reusable_candidate(adapter, key, bundle, policy) is not None
    assert service._reusable_candidate(adapter, key.model_copy(update={'candidate_hash': 'f'*64}), bundle, policy) is None
    with sqlite3.connect(':memory:') as other:
        store = AgenticStore(other)
        store.ensure()
        assert service._reusable_candidate(PersistenceAdapter(other, store), key, bundle, policy) is None
    path = conn.execute("SELECT path FROM agentic_artifacts WHERE kind='candidate'").fetchone()[0]
    Path(path).write_text('{}')
    assert service._reusable_candidate(adapter, key, bundle, policy) is None
