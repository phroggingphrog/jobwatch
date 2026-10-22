import stat

import numpy as np
import pytest

from jobwatch import db
from jobwatch.occupations.embeddings import (VectorCache, VectorStore, discovery_budget, discovery_tokens_since,
    embed_cached, make_embedder, normalise, text_key)
from pipeline.agentic.contracts import AgenticError
from pipeline.agentic.execution import QWEN_EMBEDDING_MODEL
from pipeline.agentic.gateway import PaidGatewayEmbeddings, QUERY_INSTRUCTIONS
from pipeline.agentic.runtime import BatchBudget, JobBudget
from .fixtures import approved_llm, hash_transport, make_config


def job(ceiling=100000):
    return JobBudget('a' * 64, BatchBudget('synthetic', token_ceiling=ceiling), token_ceiling=ceiling)


def adapter(calls=None, *, fail_after=None, budget=None):
    return PaidGatewayEmbeddings(approved_llm(hash_transport(calls, fail_after=fail_after)), QWEN_EMBEDDING_MODEL, budget or job())


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path / 'data'))
    out = db.connect(tmp_path / 'db.sqlite')
    yield out
    out.close()


def test_default_query_instruction_and_documents_are_unchanged():
    calls = []
    a = adapter(calls)
    a.embed_queries(['reconcile accounts'])
    a.embed_documents(['exact document'])
    assert calls[0]['input'] == [f"Instruct: {QUERY_INSTRUCTIONS['requirement']}\nQuery:reconcile accounts"]
    assert calls[1]['input'] == ['exact document']


def test_field_kind_and_unknown_kind():
    calls = []
    a = adapter(calls)
    a.embed_queries(['ledgers'], kind='field_from_evidence')
    assert calls[0]['input'][0].startswith('Instruct: Given a statement of a person')
    with pytest.raises(AgenticError, match='invalid_request'):
        a.embed_queries(['x'], kind='nope')
    assert len(calls) == 1


def test_vector_cache_is_per_model_and_prunes(conn):
    c = VectorCache(conn, 'm1')
    c.put_many({'k': normalise([[1, 0]])[0]})
    assert 'k' in c.get_many(['k'])
    assert VectorCache(conn, 'm2').get_many(['k']) == {}
    conn.execute("UPDATE text_embeddings SET created_at='2000-01-01T00:00:00+00:00'")
    assert c.prune(1) == 1


def test_embed_cached_pays_once(conn):
    calls = []
    a = adapter(calls)
    cache = VectorCache(conn, QWEN_EMBEDDING_MODEL)
    first = embed_cached(a, cache, {'a': 'ledger', 'b': 'coffee'})
    second = embed_cached(a, cache, {'a': 'ledger', 'b': 'coffee'})
    assert len(calls) == 1
    assert all(np.array_equal(first[k], second[k]) for k in first)


def test_reference_store_is_private_and_resumable(tmp_path):
    store = VectorStore(tmp_path / 'ref', QWEN_EMBEDDING_MODEL)
    texts = {str(i): f'text {i}' for i in range(40)}
    with pytest.raises(AgenticError):
        embed_cached(adapter(fail_after=1), store, texts)
    assert len(store.get_many(list(texts))) == 32
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in (tmp_path / 'ref').rglob('*.f32'))
    calls = []
    embed_cached(adapter(calls), store, texts)
    assert len(calls[0]['input']) == 8
    assert len(store.get_many(list(texts))) == 40


def test_discovery_spend_counts_including_errors(conn):
    with discovery_budget(conn, 'test', token_ceiling=100000) as budget:
        adapter(budget=budget).embed_documents(['one ledger'])
    assert discovery_tokens_since(conn, 0) == 10
    with pytest.raises(AgenticError):
        with discovery_budget(conn, 'fail', token_ceiling=100000) as budget:
            adapter(fail_after=0, budget=budget).embed_documents(['one ledger'])
    assert discovery_tokens_since(conn, 0) > 10


def test_budget_ceiling_stops_embedding(conn):
    calls = []
    with discovery_budget(conn, 'test', token_ceiling=50) as budget:
        with pytest.raises(AgenticError, match='token_limit'):
            adapter(calls, budget=budget).embed_documents(['x' * 4000])
    assert calls == []


@pytest.mark.parametrize('bad', [[], [0., 0.], [float('nan'), 1], [float('inf'), 1]])
def test_invalid_vectors_are_refused(bad):
    with pytest.raises(ValueError, match='invalid_vector'):
        normalise([bad])


def test_corrupt_files_and_rows_are_refused(tmp_path, conn):
    store = VectorStore(tmp_path, 'test-model')
    store.put_many({'a': [1., 0.]})
    next(tmp_path.rglob('*.f32')).write_bytes(b'bad')
    with pytest.raises(ValueError, match='invalid_vector'):
        store.get_many(['a'])
    cache = VectorCache(conn, 'm')
    cache.put_many({'a': [1., 0.]})
    conn.execute("UPDATE text_embeddings SET dims=3")
    with pytest.raises(ValueError, match='invalid_vector'):
        cache.get_many(['a'])


def test_make_embedder_refuses_wrong_gateway(conn):
    from jobwatch.llm import LLM
    with discovery_budget(conn, 'test', token_ceiling=100000) as budget:
        with pytest.raises(AgenticError, match='gateway_not_allowed'):
            make_embedder(LLM(transport=hash_transport(), keys=['s'], base_url='http://127.0.0.1:9/v1'), make_config(), budget)


def test_settings_do_not_change_run_key(monkeypatch):
    from pipeline.agentic import service
    monkeypatch.setattr('jobwatch.model_choice.chosen', lambda: {})
    off = make_config({'pipeline': {'agentic': {'enabled': True}}})
    on = make_config({'pipeline': {'agentic': {'enabled': True, 'relevance': 'on', 'search_plan': True,
        'dedupe': 'semantic', 'ordering': 'hypotheses'}, 'discovery': {'similar_at': .7}}})
    assert service._config(off) == service._config(on)


def test_text_key_is_content_addressed():
    assert len(text_key('a')) == 64 and text_key('a') != text_key('b')


def test_daily_ceiling_shared_across_discovery_contexts(conn, monkeypatch):
    from types import SimpleNamespace
    from jobwatch.candidate import intake
    monkeypatch.setattr(intake, 'discovery_scope', lambda person: SimpleNamespace(daily_token_ceiling=130))
    calls = []
    with discovery_budget(conn, 'one', token_ceiling=1000) as budget:
        adapter(calls, budget=budget).embed_documents(['ledger'])
    assert discovery_tokens_since(conn, 0) == 10
    with discovery_budget(conn, 'two', token_ceiling=1000) as budget:
        with pytest.raises(AgenticError, match='token_limit'):
            adapter(calls, budget=budget).embed_documents(['x' * 1000])
    assert len(calls) == 1


def test_spent_day_stops_before_discovery_dispatch(conn, monkeypatch):
    from types import SimpleNamespace
    from jobwatch.candidate import intake
    from jobwatch.occupations import DiscoveryError
    monkeypatch.setattr(intake, 'discovery_scope', lambda person: SimpleNamespace(daily_token_ceiling=1))
    conn.execute("INSERT INTO discovery_spend(at, purpose, charged_tokens) VALUES(strftime('%s','now'),'spent',1)")
    conn.commit()
    with pytest.raises(DiscoveryError, match='daily_budget'):
        with discovery_budget(conn, 'blocked', token_ceiling=1000):
            pytest.fail('spent day admitted')


def test_invocation_ceiling_and_cancellation_still_bound_discovery(conn):
    from pipeline.agentic import execution
    calls = []
    with execution.use(execution.Execution('synthetic', token_ceiling=1)):
        with discovery_budget(conn, 'invocation', token_ceiling=10000) as budget:
            with pytest.raises(AgenticError, match='invocation_budget_exhausted'):
                adapter(calls, budget=budget).embed_documents(['ledger'])
    assert calls == []
    with execution.use(execution.Execution('cancelled', cancelled=lambda: True)):
        with pytest.raises(AgenticError, match='cancelled'):
            with discovery_budget(conn, 'cancelled', token_ceiling=10000):
                pytest.fail('cancelled invocation admitted')


def test_discovery_spend_is_in_existing_daily_total(conn):
    from pipeline.agentic import service, store
    store.AgenticStore(conn).ensure()
    with discovery_budget(conn, 'accounted', token_ceiling=100000) as budget:
        adapter(budget=budget).embed_documents(['ledger'])
    assert service._spent_today(conn, 0)[1] == discovery_tokens_since(conn, 0) == 10


def test_vector_store_refuses_symlink_to_another_person(tmp_path):
    store = VectorStore(tmp_path / 'first', 'm')
    store.put_many({'a': [1., 0.]})
    path = next((tmp_path / 'first').rglob('*.f32'))
    other = tmp_path / 'other.f32'
    other.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(other)
    with pytest.raises(OSError):
        store.get_many(['a'])


@pytest.mark.parametrize('seconds', [0, -1, float('inf'), float('nan'), True, '5'])
def test_invalid_budget_deadline_is_refused(conn, seconds):
    from jobwatch.occupations import DiscoveryError
    with pytest.raises(DiscoveryError, match='invalid_configuration'):
        with discovery_budget(conn, 'bad', token_ceiling=1000, seconds=seconds):
            pytest.fail('invalid deadline admitted')


def test_daily_limit_includes_existing_agentic_spend(conn, monkeypatch):
    from types import SimpleNamespace
    from jobwatch.candidate import intake
    from pipeline.agentic import store
    store.AgenticStore(conn).ensure()
    # Simulate the current authoritative batch accounting without dispatching a model.
    monkeypatch.setattr('pipeline.agentic.service._spent_today', lambda c, start: (0, 130))
    monkeypatch.setattr(intake, 'discovery_scope', lambda person: SimpleNamespace(daily_token_ceiling=130))
    from jobwatch.occupations import DiscoveryError
    with pytest.raises(DiscoveryError, match='daily_budget'):
        with discovery_budget(conn, 'blocked', token_ceiling=1000):
            pytest.fail('daily agentic spend was ignored')
