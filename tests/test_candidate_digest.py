"""Synthetic native traces, freshness, isolation and paid-response recovery."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_agentic_service import world
from pipeline.agentic import candidate_digest as cd, service
from pipeline.agentic.runtime import BatchBudget, JobBudget
from jobwatch.candidate.policy import default_policy


def inputs(world):
    conn, config, bundle, add = world
    cfg, policy = service._config(config), default_policy()
    structural = service.analyse_candidate(bundle, *service.load_inputs(bundle, cfg), policy)
    return conn, dict(config=config, cfg=cfg, bundle=bundle, policy=policy, structural=structural)


def budget():
    return JobBudget('a'*64, BatchBudget('synthetic', token_ceiling=2_000_000), token_ceiling=1_000_000)


def findings(bundle):
    item = bundle.items[0]
    cite = dict(source_id=item.source_file, content_hash=item.source_hash, quote=item.quote)
    return dict(strengths=[dict(claim='Synthetic documented reconciliation', citations=[cite])],
        gaps=[dict(gap='No additional proof in this snapshot', action='Ask the person for evidence')],
        target_paths=[dict(family='accounting', rationale='Evidenced reconciliation', citations=[cite],
                          next_steps=['Explore related roles'])], uncertainties=['Job-dependent predictions await a posting'],
        advisory_suggestions=['Discuss a new exclusion; do not activate it'],
        model_interpretation={key: 'Interpret actual readiness only' for key in cd.MODEL_TOOLS.values()})


def transport(monkeypatch, bundle, *, final=None, evidence=True):
    calls = []
    def native(llm, model, messages, **kwargs):
        calls.append(copy.deepcopy(messages))
        assert kwargs['native_response'] is True and kwargs['json_mode'] is False
        assert kwargs['tools']
        if len(messages) == 2:
            tools = [(name, {}) for name in cd.MODEL_TOOLS]
            if evidence:
                tools.append(('read_candidate_evidence', {'evidence_ids': [i.id for i in bundle.items]}))
        else:
            tools = [('complete_candidate_digest', final or findings(bundle))]
        return SimpleNamespace(data={'content': '', 'tool_calls': [dict(id=f'call-{n}', type='function',
            function=dict(name=name, arguments=json.dumps(args))) for n,(name,args) in enumerate(tools)]},
            usage={'prompt_tokens': 11, 'completion_tokens': 7})
    monkeypatch.setattr('pipeline.agentic.autonomous.call', native)
    return calls


def test_native_digest_all_models_exact_sources_and_zero_call_reuse(world, monkeypatch):
    conn, args = inputs(world)
    calls = transport(monkeypatch, args['bundle'])
    original = cd.evidence_records
    def read(*a, **kw):
        # The paid reply is durable before any evidence tool is dispatched.
        from jobwatch.apply.paths import data_dir
        import sqlite3
        with sqlite3.connect(data_dir() / 'candidate-understanding.sqlite') as private:
            assert private.execute("SELECT 1 FROM autonomous_results WHERE identity LIKE '%:response:%'").fetchone()
        return original(*a, **kw)
    monkeypatch.setattr(cd, 'evidence_records', read)
    paid = budget()
    result = cd.ensure_digest(conn, **args, budget=paid, llm=object())
    assert len(calls) == 2 and paid.charged_tokens == 36
    assert result.counts['purposes'] == {'candidate_digest': 2}
    assert result.counts['charged_tokens'] == 36 and result.counts['unknown_usage_calls'] == 0
    assert set(result.model_provenance) == set(cd.MODEL_TOOLS.values())
    assert result.model_provenance['response_time']['status'] == 'insufficient_history'
    assert result.model_provenance['jev']['status'] == 'unavailable'
    assert result.model_provenance['preferences']['prediction_status'] == 'posting_inputs_required'
    assert result.advisory_suggestions and 'new exclusion' not in json.dumps(result.screening_policy)
    assert 'max_required_years' not in result.approved_constraints
    assert cd.ensure_digest(conn, **args, budget=budget(), llm=object()) == result
    assert cd.current_digest(conn, **args) == result and len(calls) == 2
    monkeypatch.setattr('jobwatch.config.load_config', lambda: args['config'])
    dp = service.policy_for(service.users.current())
    assert cd.current_policy_digest(conn, dp) == result


def test_readonly_getters_create_no_tables(world):
    conn, args = inputs(world)
    before = conn.total_changes
    tables = list(conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    assert cd.current_digest(conn, **args) is None
    assert cd.current_policy_digest(conn, service.policy_for(service.users.current())) is None
    assert conn.total_changes == before
    assert list(conn.execute("SELECT name FROM sqlite_master WHERE type='table'")) == tables


def test_completed_response_replayed_after_digest_persistence_failure(world, monkeypatch):
    conn, args = inputs(world)
    calls = transport(monkeypatch, args['bundle'])
    original = cd._store
    def fail(*a, **kw):
        raise OSError('synthetic interruption after response journaling')
    monkeypatch.setattr(cd, '_store', fail)
    with pytest.raises(OSError):
        cd.ensure_digest(conn, **args, budget=budget(), llm=object())
    assert len(calls) == 2
    monkeypatch.setattr(cd, '_store', original)
    resumed = budget()
    assert cd.ensure_digest(conn, **args, budget=resumed, llm=object()).strengths
    assert len(calls) == 2 and resumed.charged_tokens == 0


def test_history_refresh_reuses_validated_primary_findings(world, monkeypatch):
    conn, args = inputs(world)
    calls = transport(monkeypatch, args['bundle'])
    first = cd.ensure_digest(conn, **args, budget=budget(), llm=object())
    world[3](100)
    conn.execute("INSERT INTO applications(id,posting_id,match_id,status,created_at,updated_at) VALUES(100,100,NULL,'applied','2026-01-01','2026-01-01')")
    conn.commit()
    assert cd.current_digest(conn, **args) is None
    calls = transport(monkeypatch, args['bundle'], evidence=False)
    second = cd.ensure_digest(conn, **args, budget=budget(), llm=object())
    assert first.identity != second.identity
    assert second.reviewed_evidence_ids == first.reviewed_evidence_ids
    assert json.loads(calls[0][1]['content'])['prior_evidence_findings']['strengths']


def test_identity_changes_for_person_profile_policy_model_and_skill(world, monkeypatch):
    from jobwatch import users
    conn, args = inputs(world)
    transport(monkeypatch, args['bundle'])
    first = cd.ensure_digest(conn, **args, budget=budget(), llm=object())
    for altered in ({**args, 'cfg': {**args['cfg'], 'evaluator_model':'synthetic-other'}},
                    {**args, 'approved_profile': None}):
        assert cd.current_digest(conn, **altered) is None
    with users.use('synthetic-other'):
        assert cd.current_digest(conn, **args, approved_profile=None) is None
    monkeypatch.setattr(cd, 'VERSION', 'synthetic-schema-change')
    assert cd.current_digest(conn, **args) is None
    assert first.identity


def test_fabricated_citation_and_unapproved_family_rejected(world, monkeypatch):
    conn, args = inputs(world)
    bad = findings(args['bundle'])
    bad['strengths'][0]['citations'][0]['quote'] = 'Invented degree or consent'
    calls = transport(monkeypatch, args['bundle'], final=bad)
    from pipeline.agentic.runtime import RuntimeErrorSafe
    with pytest.raises(RuntimeErrorSafe, match='invalid_citation'):
        cd.ensure_digest(conn, **args, budget=budget(), llm=object())
    assert len(calls) == 3
    assert cd.current_digest(conn, **args) is None


def test_configuration_extraction_retains_all_fields(world, monkeypatch):
    from pipeline.agentic.configuration import runtime_config
    conn, config, bundle, add = world
    cfg = runtime_config(config)
    assert service._config(config) == cfg
    assert set(cfg) == {'worker_model','evaluator_model','reviewer_model','answer_model','credential_index',
        'embedding_model','research_enabled','job_token_ceiling','batch_token_ceiling','job_seconds','batch_seconds',
        'occupation_reference_path','occupation_mappings_path'}
    assert cfg['job_token_ceiling'] == 250000
    config.settings['pipeline']['agentic']['autonomous_evaluation'] = 'yes'
    with pytest.raises(service.AgenticError, match='invalid_configuration'):
        runtime_config(config)


def test_direct_service_digest_precedes_personal_filter_and_binds_run_key(world, monkeypatch):
    from pipeline.agentic.persistence import PersistenceAdapter
    from jobwatch.prescreen.engine import Engine
    from pipeline.agentic.runtime import RuntimeErrorSafe
    conn, config, bundle, add = world
    config.settings['pipeline']['agentic']['autonomous_evaluation'] = True
    add(42)
    monkeypatch.setattr('jobwatch.config.load_config', lambda: config)
    calls = transport(monkeypatch, bundle)
    order = []
    original = Engine.evaluate
    def filtered(engine, *a, **kw):
        _, args = inputs(world)
        assert cd.current_digest(conn, **args) is not None
        order.append('personal_filter')
        return original(engine, *a, **kw)
    monkeypatch.setattr(Engine, 'evaluate', filtered)
    def native(key, ad, paid, llm, **kwargs):
        assert kwargs['candidate_digest']['identity']
        assert key.candidate_hash == kwargs['candidate_analysis'].run_key
        order.append('job_evaluation')
        raise RuntimeErrorSafe('synthetic_stop')
    monkeypatch.setattr('pipeline.agentic.autonomous.evaluate_posting', native)
    result = service.agentic_batch_run([42], config, conn, evidence_bundle=bundle, llm=object(), operation='evaluate')
    assert len(calls) == 2 and order == ['personal_filter', 'job_evaluation']
    assert result['held'] == 1
    _, args = inputs(world)
    first = service._run_key(42, service._capture(conn,42), bundle, args['policy'], args['cfg'], conn=conn)
    assert conn.execute('SELECT COUNT(*) FROM agentic_runs').fetchone()[0] == 1
    cost = cd.digest_costs(conn, cd.current_digest(conn, **args))
    assert cost['jobs_using_digest'] == 1 and cost['amortized_charged_tokens'] == 36
    add(100)
    conn.execute("INSERT INTO applications(posting_id,status,created_at,updated_at) VALUES(100,'applied','2026-01-01','2026-01-01')")
    conn.commit()
    changed = service._run_key(42, service._capture(conn,42), bundle, args['policy'], args['cfg'], conn=conn)
    assert first.value != changed.value and first.candidate_hash == changed.candidate_hash
    rows = conn.execute("SELECT run_key FROM agentic_artifacts WHERE kind='candidate_digest_counts'").fetchall()
    adapter = PersistenceAdapter(conn, service.AgenticStore(conn))
    costs = [adapter.load_artifact(r[0], 'candidate_digest_counts') for r in rows]
    assert sum(c['calls'] for c in costs) == 2 and sum(c['charged_tokens'] for c in costs) == 36


def test_reader_prepares_digest_before_ingest_and_shares_daily_ledger(world, monkeypatch):
    from pipeline.nodes import ingest
    from pipeline.agentic import discovery, execution
    conn, config, bundle, add = world
    config.settings['pipeline']['agentic']['autonomous_evaluation'] = True
    monkeypatch.setattr(service, 'configured_llm', lambda _: object())
    monkeypatch.setattr('jobwatch.config.load_config', lambda: config)
    calls = transport(monkeypatch, bundle)
    order = []
    def ingested(*a, **kw):
        from pipeline import store
        store.ensure(conn)
        assert cd.current_policy_digest(conn, service.policy_for(service.users.current())) is not None
        assert execution.current().charged_tokens == 0  # fake transport bypasses gateway's invocation layer
        order.append('ingest')
        return {}
    monkeypatch.setattr(ingest, 'run', ingested)
    monkeypatch.setattr(discovery, 'enforce_exclusions', lambda *a, **kw: order.append('exclusions') or [])
    monkeypatch.setattr(discovery, 'reconsider', lambda *a, **kw: None)
    monkeypatch.setattr(discovery, 'screen_step', lambda *a, **kw: {})
    monkeypatch.setattr(service, 'agentic_batch_run', lambda *a, **kw: {})
    monkeypatch.setattr(service, '_refresh_shortlist', lambda *a, **kw: {})
    result = service.after_collect(conn, config, max_seconds=600)
    assert order[:2] == ['ingest','exclusions'] and len(calls) == 2
    assert conn.execute("SELECT charged_tokens FROM discovery_spend WHERE purpose='candidate_digest'").fetchone()[0] == 36
    jobs, tokens = service._spent_today(conn, service._local_midnight(service._now()))
    assert tokens == 36


def test_collect_only_cannot_prepare_candidate_digest(world, monkeypatch):
    from jobwatch import pipeline
    conn, config, bundle, add = world
    config.settings['pipeline']['agentic']['autonomous_evaluation'] = True
    calls = []
    def forbidden(*a, **kw):
        calls.append(1)
        raise AssertionError('collect-only attempted paid candidate understanding')
    monkeypatch.setattr(cd, 'ensure_digest', forbidden)
    monkeypatch.setattr(service, 'after_collect', forbidden)
    monkeypatch.setattr(pipeline, 'tier_collectors', lambda *a: [])
    monkeypatch.setattr(pipeline, 'publish', lambda *a: {})
    pipeline.run(config, 'fast', assess=False, printer=lambda *a: None)
    assert calls == []
    assert not cd._exists(conn)


def test_digest_failure_is_held_with_specific_incident(world, monkeypatch):
    from pipeline.agentic import incidents
    conn, config, bundle, add = world
    config.settings['pipeline']['agentic']['autonomous_evaluation'] = True
    add(42)
    def unavailable(*a, **kw):
        raise service.AgenticError('candidate_digest_models_unread')
    monkeypatch.setattr(cd, 'ensure_digest', unavailable)
    service.agentic_batch_run([42], config, conn, evidence_bundle=bundle, llm=object(), operation='evaluate')
    failures = incidents.list_incidents(conn)
    assert any(f['reason'] == 'candidate_digest_models_unread' for f in failures)


def test_authenticated_discovery_endpoint_prepares_digest_with_shared_paid_accounting(world, monkeypatch):
    import time
    from fastapi.testclient import TestClient
    from jobwatch import users, model_choice
    from jobwatch.llm import LLM
    from pipeline.agentic.api import Principal, create_api
    from pipeline.agentic import discovery, execution
    from pipeline.nodes import ingest
    conn, config, bundle, add = world
    config.settings['pipeline']['agentic']['autonomous_evaluation'] = True
    seen, order = [], []
    def send(url, headers, body, timeout):
        seen.append(body)
        assert body['tools'] and 'response_format' not in body
        assert not url.endswith('/embeddings')
        if not any(m['role'] == 'tool' for m in body['messages']):
            tools = [(name, {}) for name in cd.MODEL_TOOLS]
            tools.append(('read_candidate_evidence', {'evidence_ids': [i.id for i in bundle.items]}))
        else:
            tools = [('complete_candidate_digest', findings(bundle))]
        message = {'content': None, 'tool_calls': [dict(id=f'call-{n}', type='function',
            function=dict(name=name, arguments=json.dumps(args))) for n,(name,args) in enumerate(tools)]}
        return 200, {'choices':[{'message': message}], 'usage':{'prompt_tokens':11,'completion_tokens':7}}
    llm = LLM(transport=send, keys=['synthetic'], base_url=model_choice.SERVER_URL)
    monkeypatch.setattr(service, 'configured_llm', lambda _: llm)
    monkeypatch.setattr('jobwatch.config.load_config', lambda: config)
    def personal_filter(worker_conn, *a, **kw):
        from pipeline import store
        store.ensure(worker_conn)
        result = cd.current_policy_digest(worker_conn, service.policy_for(users.current()))
        assert result is not None
        assert execution.current().calls == 2 and execution.current().charged_tokens == 36
        order.append('ingest_filter')
        return {}
    monkeypatch.setattr(ingest, 'run', personal_filter)
    monkeypatch.setattr(discovery, 'enforce_exclusions', lambda *a, **kw: [])
    monkeypatch.setattr(discovery, 'reconsider', lambda *a, **kw: None)
    monkeypatch.setattr(discovery, 'screen_step', lambda *a, **kw: {})
    monkeypatch.setattr(service, 'agentic_batch_run', lambda *a, **kw: {})
    monkeypatch.setattr(service, '_refresh_shortlist', lambda *a, **kw: {})
    token = 's'*40
    with TestClient(create_api(config=config, credentials={token: Principal(users.current())})) as client:
        response = client.post('/api/agent/discovery/start', headers={'Authorization':'Bearer '+token},
                               json={'request_id':'synthetic-digest-before-filter'})
        assert response.status_code == 202
        ident = response.json()['run_id']
        for _ in range(1000):
            state = client.get('/api/agent/runs/'+ident, headers={'Authorization':'Bearer '+token}).json()
            if state['state'] not in ('queued','running'):
                break
            time.sleep(.01)
        assert state['state'] == 'completed', state
    assert order == ['ingest_filter'] and len(seen) == 2
    assert conn.execute("SELECT charged_tokens FROM discovery_spend WHERE purpose='candidate_digest'").fetchone()[0] == 36


def test_evidence_policy_and_source_bindings_invalidate_without_paid_refresh(world, monkeypatch):
    from jobwatch.apply.paths import profile_dir
    from jobwatch.candidate.evidence import snapshot_evidence
    conn, args = inputs(world)
    calls = transport(monkeypatch, args['bundle'])
    cd.ensure_digest(conn, **args, budget=budget(), llm=object())
    path = profile_dir() / 'cv.md'
    path.write_text(path.read_text() + '\n- Synthetic additional primary reconciliation evidence.\n')
    changed = snapshot_evidence(profile_dir())
    structural = service.analyse_candidate(changed, *service.load_inputs(changed,args['cfg']), args['policy'])
    assert cd.current_digest(conn, **{**args,'bundle':changed,'structural':structural}) is None
    policy = args['policy'].model_copy(update={'version':'synthetic-new-policy'})
    structural = service.analyse_candidate(args['bundle'], *service.load_inputs(args['bundle'],args['cfg']), policy)
    assert cd.current_digest(conn, **{**args,'policy':policy,'structural':structural}) is None
    structural = args['structural'].model_copy(update={'reference_hash':'b'*64,'mapping_hash':'c'*64})
    assert cd.current_digest(conn, **{**args,'structural':structural}) is None
    assert len(calls) == 2


def test_unsubmitted_drafts_do_not_invalidate_current_digest(world, monkeypatch):
    conn, args = inputs(world)
    transport(monkeypatch, args['bundle'])
    result = cd.ensure_digest(conn, **args, budget=budget(), llm=object())
    world[3](100)
    conn.execute("INSERT INTO applications(posting_id,status,created_at,updated_at) VALUES(100,'draft','2026-01-01','2026-01-01')")
    conn.commit()
    assert cd.current_digest(conn, **args) == result


@pytest.mark.parametrize('raw', [
    {'credential_index':-1}, {'credential_index':True}, {'research_enabled':'true'},
    {'autonomous_evaluation':'true'}, {'job_token_ceiling':0}, {'occupation_reference_path':''},
])
def test_configuration_validation_equivalent_for_both_layouts(raw):
    from pipeline.agentic.configuration import runtime_config
    for config in ({'agentic':raw}, {'pipeline':{'agentic':raw}}):
        with pytest.raises(service.AgenticError, match='invalid_configuration'):
            runtime_config(config)


def test_config_pick_overrides_and_clamps_survive_extraction(monkeypatch):
    from pipeline.agentic.configuration import runtime_config
    monkeypatch.setattr('jobwatch.model_choice.chosen', lambda: {'evaluator':'synthetic-choice'})
    raw = dict(evaluator_model='synthetic-config', job_seconds=1000, batch_seconds=2000)
    root, nested = runtime_config({'agentic':raw}), runtime_config({'pipeline':{'agentic':raw}})
    assert root == nested
    assert root['evaluator_model'] == 'synthetic-choice'
    assert root['job_seconds'] == 900 and root['batch_seconds'] == 1800
