"""Offline regressions for discovery fairness, refresh and collection boundaries."""
from types import SimpleNamespace

import numpy as np

from conftest import make_config
from jobwatch import db, pipeline as collection, users
from jobwatch.candidate import intake
from jobwatch.candidate.policy import build_policy
from jobwatch.occupations import hypotheses, loaders
from jobwatch.occupations.embeddings import VectorStore
from jobwatch.occupations.plan import load_plan, save_plan, search_plan
from pipeline import store
from pipeline.agentic import discovery, service
from pipeline.schemas import Stage

from .fixtures import approved_llm, fact, hash_transport, make_policy, toy_reference, write_approved
from .test_relevance import env, add


def test_ordering_keeps_five_oldest_after_fifteen_closest(env, monkeypatch):
    conn, _, _, context = env
    pending = list(range(1, 31))  # The collector supplies oldest first.
    vectors = {pid: np.array([pid / 31, np.sqrt(1 - (pid / 31) ** 2)]) for pid in range(6, 31)}
    requests = []

    def cached_vectors(connection, ctx, posting_ids, *, limit):
        requests.append((list(posting_ids), limit))
        return vectors

    monkeypatch.setattr(discovery, 'ensure_ad_vectors', cached_vectors)
    result = discovery.order_pending(conn, {}, pending, context=context)
    assert result[:15] == list(range(30, 15, -1))
    assert result[15:20] == [1, 2, 3, 4, 5]  # Unvectored old jobs still get assessment slots.
    assert len(result) == len(set(result)) == 30
    assert set(result) == set(pending)
    assert requests == [(pending, 40)]


def test_semantic_duplicate_embedding_limit_resumes_backlog_across_calls(env, monkeypatch):
    conn, _, _, context = env
    for pid in range(1, 8):
        # Distinct ads from one source must remain separate vacancies.
        add(conn, pid, text=f'Reconcile supplier ledgers for synthetic requisition {pid}.')

    def capture(connection, pid):
        return ({}, connection.execute('SELECT description FROM postings WHERE id=?', (pid,)).fetchone()[0], 'full')

    monkeypatch.setattr(service, '_capture', capture)
    for expected in (3, 6, 7):
        assert discovery.semantic_duplicates(conn, {}, context=context, limit=3) == 0
        checked = {r[0] for r in conn.execute('SELECT posting_id FROM near_dup_checked')}
        assert checked == set(range(1, expected + 1))
        assert len(context.embedder.calls) == expected
    assert discovery.semantic_duplicates(conn, {}, context=context, limit=3) == 0
    assert len(context.embedder.calls) == 7
    assert conn.execute("SELECT COUNT(*) FROM pipeline_state WHERE stage='ingested'").fetchone()[0] == 7


def test_reconsider_reaches_changed_rule_after_twenty_still_excluded_jobs(env, monkeypatch):
    conn, _, _, _ = env
    policy = build_policy({'version': 1, 'facts': [fact('exclusion', {'kind': 'employer', 'value': 'Acme'}, fid='employer')]})
    monkeypatch.setattr(discovery, '_current_plan', lambda person: (policy, None))
    for pid in range(1, 22):
        add(conn, pid, company='Acme' if pid <= 20 else 'Another Employer')
        store.move(conn, pid, 'synthetic_exclusion', Stage.INGESTED, Stage.ARCHIVED,
                   reason='excluded_by_rule', output={'rule_id': 'old-rule'})
        conn.execute('UPDATE pipeline_state SET updated_at=? WHERE posting_id=?', (f'2026-01-{pid:02d}', pid))
    conn.commit()
    config = {'pipeline': {'agentic': {'decision_policy': 'profile'}, 'discovery': {'reconsider_per_run': 20}}}
    assert discovery.reconsider(conn, config) == 1
    states = dict(conn.execute('SELECT posting_id, stage FROM pipeline_state'))
    assert states[21] == 'ingested'
    assert all(states[pid] == 'archived' for pid in range(1, 21))


def test_dry_run_collection_uses_unpaid_scope_but_never_refreshes_discovery(tmp_path, monkeypatch):
    config = make_config(settings={'pipeline': {'agentic': {'enabled': True, 'search_plan': True}},
                                  'tiers': {'fast': [], 'slow': []}}, tmp_path=tmp_path)
    called = []

    def forbidden(*args, **kwargs):
        raise AssertionError('dry-run reached paid discovery refresh')

    original = discovery.prepare_run
    def prepare(conn, config):
        called.append('unpaid scope')
        return original(conn, config)
    monkeypatch.setattr(discovery, 'prepare_run', prepare)
    monkeypatch.setattr(discovery, 'refresh', forbidden)
    monkeypatch.setattr(collection, 'tier_collectors', lambda *args: [])
    result = collection.run(config, 'fast', dry_run=True, printer=lambda *args: None)
    assert called == ['unpaid scope']
    assert result['collectors'] == [] and result['ai'] == {}


def test_prepare_run_uses_unpaid_confirmed_scope_when_reference_changes(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path / 'data'))
    person = 'boundary-person'
    policy = make_policy()
    config = make_config(settings={'pipeline': {'agentic': {'enabled': True, 'search_plan': True,
        'embedding_model': 'openrouter/qwen/qwen3-embedding-8b'}}}, tmp_path=tmp_path)
    current_reference = [toy_reference()]
    monkeypatch.setattr(loaders, 'load_reference_records', lambda **kwargs: current_reference[0])
    monkeypatch.setattr(hypotheses, 'policy_for', lambda person: policy)
    monkeypatch.setattr(discovery, 'policy_for', lambda person: policy)
    monkeypatch.setattr(intake, 'discovery_scope', lambda person: SimpleNamespace(basis=('supplier reconciliation',), locations=(), daily_token_ceiling=1_000_000))
    monkeypatch.setattr(hypotheses, 'reference_store', lambda model=None: VectorStore(tmp_path / 'reference', model))
    monkeypatch.setattr(discovery, 'effective_mode', lambda cfg: 'agentic')
    calls = []
    llm = approved_llm(hash_transport(calls))
    refreshed = []
    original_refresh = discovery.refresh

    def refresh(person, cfg, **kwargs):
        refreshed.append(person)
        return original_refresh(person, cfg, llm=llm, **kwargs)

    with users.use(person):
        write_approved(person, [fact('experience', 'Reconcile supplier ledgers', fid='ledger')])
        connection = db.connect(config.db_path)
        try:
            fields = hypotheses.field_hypotheses(person, config=config, llm=llm, policy=policy, conn=connection)
            original_plan = search_plan(policy, fields)
            save_plan(person, original_plan)
            before = len(calls)
            current_reference[0] = current_reference[0].model_copy(update={'versions': {'anzsco2022': 'toy-2', 'onet': 'toy-1'}})
            assert hypotheses.cached_hypotheses(person, config=config) is None
            assert load_plan(person) == original_plan
            monkeypatch.setattr(discovery, 'refresh', refresh)
            prepared = discovery.prepare_run(connection, config)
            assert refreshed == []
            assert len(calls) == before
            assert hypotheses.cached_hypotheses(person, config=config) is None
            assert prepared.extra['search_plan'].profile_version == original_plan.profile_version
            assert prepared.extra['search_plan'].policy_hash == original_plan.policy_hash
        finally:
            connection.close()
