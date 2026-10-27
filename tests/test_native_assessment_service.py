"""Native service dispatch must bypass the paid legacy candidate evaluator."""
from test_agentic_service import world
from jobwatch.candidate.contracts import AnalysisResult
from pipeline.agentic.runtime import RuntimeErrorSafe


def test_native_service_uses_deterministic_candidate_context(world, monkeypatch):
    from pipeline.agentic import service
    conn, config, bundle, add = world
    config.settings['pipeline']['agentic']['autonomous_evaluation'] = True
    add(42)
    called = []

    def forbidden(*args, **kwargs):
        raise AssertionError('legacy paid evaluator reached')

    def native(key, ad, budget, llm, **kwargs):
        structural = kwargs['candidate_analysis']
        assert type(structural) is AnalysisResult
        assert structural.run_key == key.candidate_hash
        assert structural.evidence_hash == bundle.bundle_hash
        called.append(key)
        raise RuntimeErrorSafe('synthetic_stop')

    monkeypatch.setattr(service, 'evaluate_candidate', forbidden)
    monkeypatch.setattr(service, 'evaluate_job', forbidden)
    monkeypatch.setattr('pipeline.agentic.autonomous.evaluate_posting', native)
    service.agentic_batch_run([42], config, conn, evidence_bundle=bundle,
                             llm=object(), operation='evaluate')
    assert len(called) == 1
    row = conn.execute('SELECT checkpoint_json FROM agentic_runs ORDER BY rowid DESC LIMIT 1').fetchone()
    import json
    assert not any(json.loads(row[0])['role_turns'].values())


def test_embedding_cache_reuses_person_bound_primary_vectors(tmp_path, monkeypatch):
    import sqlite3
    from types import SimpleNamespace
    from pipeline.agentic.autonomous import CachedEmbeddings
    from pipeline.agentic.runtime import BatchBudget, JobBudget
    from jobwatch import users
    calls = []

    class SyntheticEmbeddings:
        def __init__(self, llm, model, budget):
            self.budget = budget
        def embed_documents(self, texts):
            calls.append(texts)
            rid = self.budget.reserve('evaluator', 10, 1)
            self.budget.dispatched(rid)
            self.budget.settle(rid, 3)
            return [[1., 0.] for _ in texts]
        def embed_queries(self, texts, kind):
            return self.embed_documents(texts)

    monkeypatch.setattr('pipeline.agentic.gateway.PaidGatewayEmbeddings', SyntheticEmbeddings)
    conn = sqlite3.connect(tmp_path / 'synthetic.sqlite')
    def run(person):
        return SimpleNamespace(conn=conn, person=person,
            budget=JobBudget('a'*64, BatchBudget('synthetic', token_ceiling=10000)),
            counts={'calls':0,'tokens':0,'seconds':0.,'purposes':{}}, save_counts=lambda:None)
    first = run('owner')
    embedding = CachedEmbeddings(first, None, 'synthetic-model', 'evidence1')
    assert embedding.embed_documents(['Synthetic primary evidence']) == [[1., 0.]]
    assert embedding.embed_documents(['Synthetic primary evidence']) == [[1., 0.]]
    assert len(calls) == 1 and first.counts['calls'] == 1 and first.counts['tokens'] == 3
    second = run('owner')
    CachedEmbeddings(second,None,'synthetic-model','evidence1').embed_documents(['Synthetic primary evidence'])
    assert len(calls) == 1 and second.counts['calls'] == 0
    CachedEmbeddings(run('another-person'),None,'synthetic-model','evidence1').embed_documents(['Synthetic primary evidence'])
    CachedEmbeddings(run('owner'),None,'synthetic-model','changed-evidence').embed_documents(['Synthetic primary evidence'])
    assert len(calls) == 3


def test_public_classifier_is_counted_and_keeps_unknown_usage_charged(monkeypatch):
    from types import SimpleNamespace
    from jobwatch import openrouter_extras as extras
    from pipeline.agentic import execution
    from pipeline.agentic.runtime import BatchBudget, JobBudget
    monkeypatch.setattr(extras, '_key', lambda _: 'synthetic')
    monkeypatch.setattr(extras.requests, 'post', lambda *a, **kw:
                        SimpleNamespace(status_code=200,json=lambda:{'answers':{}}))
    job=JobBudget('a'*64,BatchBudget('synthetic',token_ceiling=10000))
    scope=execution.Execution('synthetic')
    with execution.use(scope):
        extras._post(extras.DEFAULTS,'systemone',{'public':'synthetic ad'},budget=job)
    assert scope.calls == 1 and scope.unknown_usage_calls == 1
    assert job.snapshot().role_turns['evaluator'] == 1 and job.charged_tokens > 0


def test_screening_snapshot_keeps_remote_and_hours(world):
    from pipeline.agentic import service
    from jobwatch.prescreen.engine import fields_of_row
    conn, config, bundle, add = world
    add(42)
    conn.execute("UPDATE postings SET remote=1,work_type='part time' WHERE id=42")
    conn.commit()
    captured=service._capture(conn,42)
    fields=fields_of_row(captured[0],captured[1])
    assert fields.remote is True and fields.hours == 'part time'


def test_native_run_identity_binds_prescreen_without_inventory_writes(world):
    from pipeline.agentic import service
    conn, config, bundle, add = world
    add(42)
    config.settings['pipeline']['agentic']['autonomous_evaluation']=True
    from jobwatch.prescreen.engine import Engine
    from jobwatch.candidate.policy import policy_for
    Engine.load(conn,policy_for('owner'))
    first=service.snapshot_inventory(conn,config,posting_ids=[42],evidence_bundle=bundle)
    conn.execute("UPDATE prescreen_terms SET enabled=0 WHERE id=(SELECT MIN(id) FROM prescreen_terms)")
    conn.commit()
    changed=service.snapshot_inventory(conn,config,posting_ids=[42],evidence_bundle=bundle)
    assert first[0]['run_key'] != changed[0]['run_key']
    before=conn.total_changes
    assert service.snapshot_inventory(conn,config,posting_ids=[42],evidence_bundle=bundle)==changed
    assert conn.total_changes == before
