"""Real-schema, real Deep Agents and actual PDF end-to-end synthetic acceptance."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from conftest import make_config
from jobwatch import adtext, db, ledger
from jobwatch.candidate.evidence import snapshot_evidence
from jobwatch.llm import LLM
from pipeline.agentic.contracts import RequirementSet
from pipeline.agentic.persistence import PersistenceAdapter, latest_result
from pipeline.agentic.review import REQUIRED_CRITERIA
from pipeline.agentic.runtime import validate_model_payload
from pipeline.agentic.service import agentic_batch_run, run_agentic_job, snapshot_inventory
from pipeline.schemas import Stage


PROOF = ('Reconciled supplier ledgers in Excel, checked invoice references against purchase records, '
         'documented discrepancies for review, and prepared a clear weekly report for the finance team. '
         'Maintained an organised reconciliation workbook and explained each outstanding item with '
         'supporting records so a supervisor could check the calculations and follow up accurately.')


class SyntheticGateway:
    def __init__(self, bundle, *, score=4.3):
        self.bundle, self.score, self.calls = bundle, score, []
        item = bundle.items[0]
        self.citation = {'source_id': item.source_file, 'content_hash': item.source_hash, 'quote': item.quote}

    def __call__(self, url, headers, body, timeout):
        system = body['messages'][0]['content']
        context = json.loads(body['messages'][1]['content'])
        registry = json.loads(system.split('JSON response): ', 1)[1])
        terminal = next(t['name'] for t in registry if t['terminal'])
        self.calls.append(terminal)
        initial = len(body['messages']) == 2
        tool, args = terminal, {}
        if terminal == 'complete_candidate_assessment':
            if initial:
                tool, args = 'read_evidence', {'evidence_ids': [self.bundle.items[0].id]}
            else:
                args = {'strengths': [{'claim': 'Documented supplier reconciliation practice', 'citations': [self.citation]}],
                        'gaps': [], 'target_paths': [{'family': 'accounting', 'rationale': 'Related evidenced finance tasks',
                            'citations': [self.citation], 'next_steps': ['Develop supervised accounting practice']}]}
        elif terminal == 'complete_requirements':
            if initial:
                tool = 'read_full_ad'
            else:
                text = context['ad_text']
                h = hashlib.sha256(text.encode()).hexdigest()
                args = {'requirements': {'ad_hash': h, 'requirements': [{'id': 'r1', 'text': 'Reconcile supplier ledgers',
                    'tier': 'stated', 'importance': 'high', 'jd_signal': {'source_id': 'ad', 'content_hash': h,
                                                                         'quote': 'Reconcile supplier ledgers'}}]},
                    'facts': {'real_job': True, 'role_family': 'accounting', 'duties': ['Reconcile supplier ledgers'],
                        'required_skills': ['Excel'], 'preferred_skills': [], 'seniority': 'junior', 'min_years': None,
                        'hours': 'part_time_ok', 'program': False, 'work_rights': {'requirement': 'none_stated', 'quote': ''},
                        'screening_questions': []}, 'location_fit': 'melbourne',
                    'location_evidence': {'source_id': 'ad', 'content_hash': h, 'quote': 'based in Melbourne'},
                    'legitimacy': 'verified', 'uncertainties': []}
        elif terminal == 'complete_job_assessment':
            if initial:
                tool, args = 'read_candidate_evidence', {'evidence_ids': [self.bundle.items[0].id]}
            else:
                score = 2.7 if 'LOW_FIT' in context['ad_text'] else self.score
                requirements = validate_model_payload(RequirementSet, context['requirements'])
                args = {'requirements_hash': requirements.requirement_hash,
                    'matches': [{'requirement_id': 'r1', 'match': 'strong', 'evidence': [self.citation]}],
                    'archetype': 'junior accounting', 'global_score': score,
                    'dimensions': {name: {'score': score, 'reason': 'Synthetic evidence and job compared'}
                        for name in ('cv_match', 'north_star', 'compensation', 'culture', 'red_flags')},
                    'report': {key: 'Synthetic evidence supports reconciliation; compensation remains unknown.' for key in 'ABCDEFG'}}
        elif terminal == 'submit_draft':
            if initial:
                tool = 'read_job_ad'
            else:
                employer = context['posting']['company']
                claim = {'id': 'experience-one', 'text': PROOF, 'evidence_ids': [self.bundle.items[0].id],
                         'tier': 'stated', 'key_span': PROOF}
                framing = {'id': 'motivation', 'text': f'I am applying to {employer} because this junior role combines '
                    'supplier reconciliations with clear documentation. I would welcome the chance to contribute '
                    'careful record checking and learn your finance procedures through supervised practical work.',
                    'evidence_ids': [], 'tier': 'framing'}
                args = {'proposal': {'run_key': context['run_key'], 'evaluation_hash': context['evaluation_hash'],
                    'evidence_hash': self.bundle.bundle_hash, 'content': {'cv': {'summary': [claim]},
                    'letter': {'paragraphs': [[framing]]}, 'honest_gaps': []},
                    'screening_answers': []}}
        elif terminal == 'submit_review':
            assert context['draft']['content']['letter']
            args = {'verdict': 'approve', 'criteria': dict.fromkeys(REQUIRED_CRITERIA, True), 'feedback': []}
        else:
            raise AssertionError('Unknown synthetic role')
        return 200, {'choices': [{'message': {'content': json.dumps({'tool': tool, 'arguments': args})}}],
                     'usage': {'prompt_tokens': 20, 'completion_tokens': 10}}


@pytest.fixture
def world(tmp_path, monkeypatch):
    root = tmp_path / 'data'
    profile = root / 'profile'; profile.mkdir(parents=True)
    (profile / 'cv.md').write_text('# Synthetic Candidate\n\n## Experience\n- ' + PROOF + '\n')
    (profile / 'career_ops_profile.md').write_text('Pursue entry level accounting and finance practice in Melbourne.')
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(root)); monkeypatch.setenv('JOBWATCH_PROFILE_DIR', str(profile))
    config = make_config(tmp_path=tmp_path, settings={'pipeline': {'agentic': {'enabled': True, 'job_token_ceiling': 250_000}}})
    conn = db.connect(config.db_path)
    bundle = snapshot_evidence(profile)

    def add(ident, company='Synthetic Alpha', low=False):
        text = (f'Junior accounting analyst based in Melbourne at {company}. Part-time, 24 hours per week. '
                'Reconcile supplier ledgers and document payment differences in Excel. '
                'Join our finance team and provide clearly organised reports for review. ' + ('LOW_FIT ' if low else '')) * 3
        conn.execute('INSERT INTO postings(id,source,source_id,url,url_hash,dedupe_key,title,company,location,'
            'description,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (ident, 'synthetic', str(ident), f'https://example.invalid/jobs/{ident}', f'url{ident}', f'dedupe{ident}',
             'Junior Accounting Analyst', company, 'Melbourne VIC', text, db.ts(), db.ts()))
        adtext.save_text(conn, ident, text, 'synthetic-full'); conn.commit()
        return text

    # This fixture is an explicitly offline synthetic public-posting world.
    # Runtime gate tests below override this observer to exercise unavailable,
    # changed and closed sources; no fixture performs employer/network requests.
    from datetime import datetime, timezone
    import time
    from pipeline.agentic.liveness import PostingObservation
    from jobwatch.candidate.contracts import content_hash
    from jobwatch.models import canonical_url
    def synthetic_observation(posting, *, deadline):
        base = dict(posting_id=posting['id'], url_hash=content_hash(canonical_url(posting['url']).encode()),
                    checked_at=datetime.now(timezone.utc).isoformat())
        if deadline <= time.monotonic():
            return PostingObservation(**base, status='unknown', reason='posting_unavailable')
        text = adtext.get_text(conn, posting['id'])[0]
        return PostingObservation(**base, status='active', reason='visible_job_description',
            title=posting['title'], text=text, ad_hash=content_hash(text.encode()), source_url=posting['url'])
    monkeypatch.setattr('pipeline.agentic.service.observe_posting', synthetic_observation)
    return conn, config, bundle, add


def test_native_api_prepares_existing_pipeline_package(world, monkeypatch):
    """Authenticated HTTP -> real graph -> existing pipeline -> verified PDF download."""
    import time
    from fastapi.testclient import TestClient
    from jobwatch import users, model_choice
    from pipeline.agentic.api import create_api, Principal
    from pipeline.agentic.liveness import PostingObservation
    from jobwatch.candidate.contracts import content_hash
    from jobwatch.models import canonical_url
    from datetime import datetime, timezone

    conn, config, bundle, add = world
    text = add(42)
    def observation(posting, *, deadline):
        return PostingObservation(posting_id=posting['id'], url_hash=content_hash(canonical_url(posting['url']).encode()),
            checked_at=datetime.now(timezone.utc).isoformat(), status='active', reason='visible_job_description',
            title=posting['title'], text=text, ad_hash=content_hash(text.encode()), source_url=posting['url'])
    monkeypatch.setattr('pipeline.agentic.service.observe_posting', observation)
    monkeypatch.setattr(model_choice, 'get_model', lambda role: 'openai/sol')
    synthetic = SyntheticGateway(bundle)
    conversation_calls = []
    def transport(url, headers, body, timeout):
        if body['messages'][-1]['content'].startswith('Allowed tool schemas: '):
            value = {'tool':'prepare_application','arguments':{'posting_id':42}} if not conversation_calls else {'answer':'Prepared the application; final Submit remains human.'}
            conversation_calls.append(value)
            return 200, {'choices':[{'message':{'content':json.dumps(value)}}], 'usage':{'prompt_tokens':11,'completion_tokens':7}}
        return synthetic(url, headers, body, timeout)
    llm = LLM(transport=transport, keys=['synthetic'], base_url=model_choice.SERVER_URL)
    run_key, approve_key = 'synthetic-run-' + 'x'*40, 'synthetic-approve-' + 'y'*40
    app = create_api(config=config, llm_factory=lambda person:llm, credentials={
        run_key: Principal(users.DEFAULT_USER), approve_key: Principal(users.DEFAULT_USER, frozenset({'read','interact','approve'}))})
    headers = {'Authorization':'Bearer '+run_key, 'Idempotency-Key':'prepare-42'}
    def wait(client, ident):
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            result=client.get('/api/agent/runs/'+ident,headers=headers).json()
            if result['state'] not in ('queued','running'):return result
            time.sleep(.03)
        pytest.fail('Synthetic native pipeline did not finish')
    with TestClient(app) as client:
        thread=client.post('/api/agent/threads',headers=headers).json()['id']
        created=client.post('/api/agent/threads/'+thread+'/runs',headers=headers,json={'message':'Prepare job 42'}).json()
        pending=wait(client,created['id'])
        assert pending['state']=='waiting_for_approval',pending
        resumed=client.post('/api/agent/interactions/'+pending['interactions'][0]['id']+'/responses',
            headers={'Authorization':'Bearer '+approve_key},json={'decision':'approve'}).json()
        finished=wait(client,resumed['run_id'])
        assert finished['state']=='completed',finished
        assert finished['result']['outcomes'][0]['status']=='ready',finished
        assert {a['kind'] for a in finished['artifacts']}=={'cv','letter','form_map'}
        for artifact in finished['artifacts']:
            response=client.get(artifact['url'],headers=headers)
            assert response.status_code==200
            if artifact['kind']!='form_map':assert response.content.startswith(b'%PDF')
        assert finished['result']['usage']['model_calls']>1
        assert conn.execute("SELECT COUNT(*) FROM agentic_packages WHERE phase='complete'").fetchone()[0]==1
        print('NATIVE PACKAGE: authenticated approval -> cited evaluation -> CV/letter PDFs + form map; one immutable package, no Submit.')


def test_complete_real_pipeline_varied_jobs_pdf_ledger_and_idempotency(world):
    conn, config, bundle, add = world
    add(42); add(43, 'Synthetic Beta'); add(44, low=True); add(45, 'Synthetic Gamma')
    ledger.upsert(conn, 'applications', 'applications', {'id': 17, 'posting_id': 42, 'status': 'interested',
                                                       'created_at': db.ts(), 'updated_at': db.ts()})
    gateway = SyntheticGateway(bundle)
    llm = LLM(transport=gateway, keys=['synthetic'])
    summary = agentic_batch_run([42, 43, 44, 45], config, conn, evidence_bundle=bundle, llm=llm)
    assert summary['ready'] == 3 and summary['archived'] == 1, [latest_result(conn, p) for p in (42, 43, 44, 45)]
    current = latest_result(conn, 42)
    assert current['candidate']['structural_analysis']['reference_hash'] is not None
    receipt_path = conn.execute("SELECT path FROM agentic_artifacts WHERE run_key=? AND kind='structural_inputs'",
                                (current['run_key'],)).fetchone()[0]
    receipt = json.loads(Path(receipt_path).read_text())
    assert hashlib.sha256(receipt['reference_utf8'].encode()).hexdigest() == receipt['reference_hash']
    assert all(m['state'] == 'suggested' for m in receipt['mappings'])

    assert gateway.calls.count('complete_candidate_assessment') == 2  # read + terminal, shared across the batch
    assert conn.execute('SELECT COUNT(DISTINCT batch_id) FROM agentic_batches').fetchone()[0] == 1
    for pid, employer in ((42, 'Synthetic Alpha'), (43, 'Synthetic Beta'), (45, 'Synthetic Gamma')):
        result = latest_result(conn, pid)
        assert result['status'] == 'ready' and result['manifest']['run_key']['candidate_hash'] == result['candidate']['run_key']
        if pid == 42:
            assert result['application_id'] == 17
        assert Path(result['cv_pdf']).read_bytes().startswith(b'%PDF-')
        assert employer in (Path(result['package_dir']) / 'letter.md').read_text()
        assert json.loads((Path(result['package_dir']) / 'verify.json').read_text())['ok'] is True
        form = json.loads((Path(result['package_dir']) / 'form_map.json').read_text())
        assert form['fields'] == [] and form['owner_to_answer'] == 0
        state = conn.execute('SELECT data_json FROM pipeline_state WHERE posting_id=?', (pid,)).fetchone()[0]
        assert json.loads(state)['agentic']['form_ready'] is False
        assert json.loads(state)['agentic']['package_ready'] is True
    prior_calls = len(gateway.calls)
    assert run_agentic_job(42, config, conn, evidence_bundle=bundle, llm=llm) == Stage.READY, latest_result(conn, 42)['reason']
    assert len(gateway.calls) == prior_calls and conn.execute('SELECT COUNT(*) FROM drafts').fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM agentic_runs WHERE status='claimed'").fetchone()[0] == 0
    before = ledger.snapshot(conn); ledger.reindex(conn); assert ledger.snapshot(conn) == before


def test_interruption_resumes_saved_candidate_evaluation_and_package(world, monkeypatch):
    conn, config, bundle, add = world; add(42)
    gateway = SyntheticGateway(bundle); llm = LLM(transport=gateway, keys=['synthetic'])
    original = PersistenceAdapter.finalize_package

    def fail_before_publish(*args, **kwargs):
        raise OSError('private interrupted details')

    monkeypatch.setattr(PersistenceAdapter, 'finalize_package', fail_before_publish)
    assert run_agentic_job(42, config, conn, evidence_bundle=bundle, llm=llm) == Stage.DLQ
    first = latest_result(conn, 42)
    assert first['reason'] == 'execution_failed' and first['status'] == 'held'
    calls = len(gateway.calls)
    charge = conn.execute('SELECT charged FROM agentic_batches').fetchone()[0]
    # Recovery rechecks the public source and publishes within the existing
    # deadline, without purchasing another model call.
    monkeypatch.setattr(PersistenceAdapter, 'finalize_package', original)
    assert run_agentic_job(42, config, conn, evidence_bundle=bundle, llm=llm) == Stage.READY, latest_result(conn, 42)['reason']
    assert len(gateway.calls) == calls
    assert conn.execute('SELECT SUM(charged) FROM agentic_batches').fetchone()[0] == charge
    assert conn.execute('SELECT COUNT(*) FROM drafts').fetchone()[0] == 1


def test_board_projection_refuses_corrupt_verified_pdf(world):
    conn, config, bundle, add = world; add(42)
    llm = LLM(transport=SyntheticGateway(bundle), keys=['synthetic'])
    assert run_agentic_job(42, config, conn, evidence_bundle=bundle, llm=llm) == Stage.READY
    result = latest_result(conn, 42)
    Path(result['cv_pdf']).write_bytes(b'corrupt')
    checked = latest_result(conn, 42)
    assert checked['status'] == 'held' and checked['reason'] == 'artifact_invalid'


def test_snapshot_is_read_only_and_detects_changed_inputs(world):
    conn, config, bundle, add = world; add(42)
    before = conn.total_changes
    inventory = snapshot_inventory(conn, config, posting_ids=[42], evidence_bundle=bundle)
    assert conn.total_changes == before
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='agentic_runs'").fetchone()
    conn.execute("UPDATE postings SET company='Changed synthetic employer' WHERE id=42"); conn.commit()
    with pytest.raises(Exception, match='snapshot_changed'):
        run_agentic_job(42, config, conn, evidence_bundle=bundle, expected_run_key=inventory[0]['run_key'])


def test_failure_and_shared_token_limit_preserve_checkpoints_and_no_leases(world):
    conn, config, bundle, add = world; add(42); add(43)
    config.settings['pipeline']['agentic']['batch_token_ceiling'] = 100
    gateway = SyntheticGateway(bundle)
    summary = agentic_batch_run([42, 43], config, conn, evidence_bundle=bundle,
                               llm=LLM(transport=gateway, keys=['synthetic']))
    assert summary['held'] == 2 and not gateway.calls
    assert conn.execute("SELECT COUNT(*) FROM agentic_runs WHERE status='claimed'").fetchone()[0] == 0
    assert all(row[0] for row in conn.execute('SELECT checkpoint_json FROM agentic_runs'))


def test_timer_selection_refreshes_missing_ready_checks_without_starving_pending(world, monkeypatch):
    from pipeline import store
    from pipeline.agentic import service
    from pipeline.nodes import ingest
    conn, config, bundle, add = world
    store.ensure(conn)
    for pid in range(1, 23):
        add(pid)
        store.admit(conn, pid, str(pid), {}, Stage.READY if pid < 22 else Stage.INGESTED)
    conn.commit()
    monkeypatch.setattr(ingest, 'run', lambda *a, **k: {})
    selected = []
    monkeypatch.setattr(service, 'agentic_batch_run', lambda ids, *a, **k: selected.extend(ids) or {})
    service.after_collect(conn, config, max_seconds=60)
    assert selected[0] == 22 and len(selected) == 20
    assert set(selected[1:]).issubset(set(range(1,22)))


def test_cli_inventory_and_execution_share_bound_snapshot(world, tmp_path, monkeypatch, capsys):
    from pipeline.agentic import cli, service
    conn, config, bundle, add = world; add(42)
    monkeypatch.setattr(cli, 'load_config', lambda *a: config)
    snapshot = tmp_path / 'inventory.json'
    assert cli.main(['--db', str(config.db_path), '--posting-id', '42', '--dry-run', '--snapshot', str(snapshot)]) == 0
    inventory = json.loads(capsys.readouterr().out)
    assert inventory['mode'] == 'inventory' and inventory['postings'][0]['eligible_for_evaluation'] is True
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='agentic_runs'").fetchone()
    llm = LLM(transport=SyntheticGateway(bundle), keys=['synthetic'])
    monkeypatch.setattr(service, 'configured_llm', lambda config: llm)
    assert cli.main(['--db', str(config.db_path), '--snapshot', str(snapshot)]) == 0
    assert json.loads(capsys.readouterr().out)['ready'] == 1


def test_snapshot_change_between_inventory_and_batch_is_refused(world):
    conn, config, bundle, add = world; add(42)
    expected = snapshot_inventory(conn, config, posting_ids=[42], evidence_bundle=bundle)[0]['run_key']
    conn.execute("UPDATE postings SET company='Changed after inventory' WHERE id=42"); conn.commit()
    gateway = SyntheticGateway(bundle)
    with pytest.raises(Exception, match='snapshot_changed'):
        agentic_batch_run([42], config, conn, evidence_bundle=bundle,
                         llm=LLM(transport=gateway, keys=['synthetic']), expected_run_keys={42: expected})
    assert not gateway.calls


def test_real_config_and_legacy_pipeline_settings_select_same_runtime(world):
    from pipeline.agentic import service
    conn, config, bundle, add = world
    assert service.enabled(config)
    assert service.enabled(config.settings)
    assert service.enabled(config.settings['pipeline'])
    config.settings['pipeline']['agentic']['enabled'] = False
    config.settings['agentic'] = {'enabled': True}
    assert service.enabled(config) is False  # canonical nested flag wins
    assert service.enabled({}) is False
    assert run_agentic_job(42, config, conn, evidence_bundle=bundle) is None
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='agentic_runs'").fetchone()


def test_resumed_batch_summary_preserves_and_reports_original_budget(world, monkeypatch):
    from pipeline.agentic import service
    conn, config, bundle, add = world; add(42)
    gateway = SyntheticGateway(bundle); llm = LLM(transport=gateway, keys=['synthetic'])
    original = service.evaluate_job

    def interrupt_after_candidate(*args, **kwargs):
        raise OSError('synthetic interruption')

    monkeypatch.setattr(service, 'evaluate_job', interrupt_after_candidate)
    first = agentic_batch_run([42], config, conn, evidence_bundle=bundle, llm=llm)
    assert first['held'] == 1 and first['charged_tokens'] > 0
    monkeypatch.setattr(service, 'evaluate_job', original)
    second = agentic_batch_run([42], config, conn, evidence_bundle=bundle, llm=llm)
    assert second['ready'] == 1
    assert first['batch_id'] != second['batch_id']
    assert {b['batch_id'] for b in second['batches']} == {first['batch_id'], second['batch_id']}
    checkpoint = json.loads(conn.execute('SELECT checkpoint_json FROM agentic_runs').fetchone()[0])
    assert checkpoint['batch_id'] == first['batch_id']
    assert second['charged_tokens'] == conn.execute('SELECT SUM(charged) FROM agentic_batches').fetchone()[0]
    assert second['spent_tokens'] == second['charged_tokens'] - first['charged_tokens'] > 0


def test_manual_draft_uses_selected_runtime_and_flag_off_keeps_legacy_gate(world, monkeypatch):
    from jobwatch.web import actions
    from pipeline.agentic import service
    conn, config, bundle, add = world; add(42)
    called = []

    class ImmediateThread:
        def __init__(self, *, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(actions.threading, 'Thread', ImmediateThread)
    monkeypatch.setattr(actions, '_JOBS', {})
    monkeypatch.setattr(service, 'run_agentic_job', lambda ident, cfg, c: called.append((ident, cfg)) or Stage.READY)
    result = actions.start_draft(conn, config.db_path, 42, config=config)
    assert result['state'] == 'done' and called == [(42, config)]
    config.settings['pipeline']['agentic']['enabled'] = False
    with pytest.raises(actions.ActionError, match='Only matched jobs'):
        actions.start_draft(conn, config.db_path, 42, config=config)
    assert len(called) == 1


def test_gateway_credential_selection_is_explicit_and_never_falls_back(world, monkeypatch):
    from jobwatch import llm
    from pipeline.agentic import service
    _, config, _, _ = world
    monkeypatch.setattr(llm, 'load_keys', lambda: ['synthetic-first', 'synthetic-second'])
    monkeypatch.setattr(service, 'LLM', lambda *, keys: keys)
    config.settings['pipeline']['agentic']['credential_index'] = 1
    assert service.configured_llm(config) == ['synthetic-second']
    config.settings['pipeline']['agentic']['credential_index'] = 2
    with pytest.raises(Exception, match='credential_unavailable'):
        service.configured_llm(config)
    config.settings['pipeline']['agentic']['credential_index'] = True
    with pytest.raises(Exception, match='invalid_configuration'):
        service.configured_llm(config)


def _public_observation(posting, status='active', text=None):
    from datetime import datetime, timezone
    from pipeline.agentic.liveness import PostingObservation
    from jobwatch.candidate.contracts import content_hash
    from jobwatch.models import canonical_url
    values = dict(posting_id=posting['id'], url_hash=content_hash(canonical_url(posting['url']).encode()),
                  checked_at=datetime.now(timezone.utc).isoformat(), status=status,
                  reason={'active':'visible_job_description','closed':'posting_closed','unknown':'posting_unavailable'}[status])
    if status == 'active':
        values.update(title=posting['title'], text=text, ad_hash=content_hash(text.encode()), source_url=posting['url'])
    return PostingObservation(**values)


@pytest.mark.parametrize('status,stage,reason',[('closed',Stage.ARCHIVED,'posting_closed'),
                                              ('unknown',Stage.DLQ,'posting_unavailable')])
def test_liveness_stops_before_any_model_or_credential(world, monkeypatch, status, stage, reason):
    conn, config, bundle, add = world; add(42)
    monkeypatch.setattr('pipeline.agentic.service.observe_posting', lambda p, **kw: _public_observation(p,status))
    monkeypatch.setattr('pipeline.agentic.service.configured_llm', lambda *a: pytest.fail('credential loaded'))
    assert run_agentic_job(42,config,conn,evidence_bundle=bundle)==stage
    result=latest_result(conn,42)
    assert result['reason']==reason and result['liveness']['status']==status
    assert conn.execute('SELECT SUM(charged) FROM agentic_batches').fetchone()[0]==0
    assert conn.execute('SELECT COUNT(*) FROM agentic_artifacts').fetchone()[0]==0


def test_liveness_changed_whole_ad_is_saved_and_held_without_models(world,monkeypatch):
    conn,config,bundle,add=world; old=add(42)
    # Preserve the entire current JD, including content beyond legacy capture's20k limit.
    fresh=old+' Fresh duties. '*2000
    monkeypatch.setattr('pipeline.agentic.service.observe_posting',lambda p,**kw:_public_observation(p,text=fresh))
    monkeypatch.setattr('pipeline.agentic.service.configured_llm',lambda *a:pytest.fail('credential loaded'))
    before=snapshot_inventory(conn,config,posting_ids=[42],evidence_bundle=bundle)[0]
    assert run_agentic_job(42,config,conn,evidence_bundle=bundle)==Stage.DLQ
    assert latest_result(conn,42)['reason']=='snapshot_changed'
    assert adtext.get_text(conn,42)[0]==fresh
    after=snapshot_inventory(conn,config,posting_ids=[42],evidence_bundle=bundle)[0]
    assert before['run_key']!=after['run_key']
    assert conn.execute('SELECT SUM(charged) FROM agentic_batches').fetchone()[0]==0


@pytest.mark.parametrize('status,stage',[('closed',Stage.ARCHIVED),('unknown',Stage.DLQ),('active',Stage.READY)])
def test_cached_ready_rechecked_without_models_or_credentials(world,monkeypatch,status,stage):
    conn,config,bundle,add=world; text=add(42)
    gateway=SyntheticGateway(bundle)
    assert run_agentic_job(42,config,conn,evidence_bundle=bundle,llm=LLM(transport=gateway,keys=['synthetic']))==Stage.READY
    before=latest_result(conn,42); hashes=before['artifact_hashes']; calls=len(gateway.calls)
    checkpoint_before=conn.execute('SELECT checkpoint_json FROM agentic_runs').fetchone()[0]
    if status=='active':
        from pipeline.agentic.liveness import latest_observation
        stale=latest_observation(conn,42).model_copy(update={'checked_at':'2000-01-01T00:00:00+00:00'})
        conn.execute('INSERT INTO agentic_posting_observations(posting_id,run_key,generation,observation_json) VALUES(?,?,?,?)',
                     (42,before['run_key'],1,stale.model_dump_json()));conn.commit()
        projection=latest_result(conn,42)
        assert projection['status']=='held' and projection['reason']=='posting_check_required'
        assert projection['stored_status']=='ready'
    monkeypatch.setattr('pipeline.agentic.service.observe_posting',lambda p,**kw:_public_observation(p,status,text))
    monkeypatch.setattr('pipeline.agentic.service.configured_llm',lambda *a:pytest.fail('credential loaded'))
    assert run_agentic_job(42,config,conn,evidence_bundle=bundle)==stage
    result=latest_result(conn,42)
    assert result['artifact_hashes']==hashes and len(gateway.calls)==calls
    assert conn.execute('SELECT COUNT(*) FROM agentic_posting_observations').fetchone()[0]==(3 if status=='active' else 2)
    assert conn.execute('SELECT checkpoint_json FROM agentic_runs').fetchone()[0]==checkpoint_before
    assert conn.execute('SELECT stage FROM pipeline_state WHERE posting_id=42').fetchone()[0]==str(stage)
    if status in {'unknown','closed'}:
        checkpoint=json.loads(checkpoint_before);checkpoint['job_deadline']=1.0
        conn.execute('UPDATE agentic_runs SET checkpoint_json=?',(json.dumps(checkpoint),));conn.commit()
        monkeypatch.setattr('pipeline.agentic.service.observe_posting',lambda p,**kw:_public_observation(p,text=text))
        assert run_agentic_job(42,config,conn,evidence_bundle=bundle)==Stage.READY
        assert latest_result(conn,42)['status']=='ready'
        assert len(gateway.calls)==calls
        assert json.loads(conn.execute('SELECT checkpoint_json FROM agentic_runs').fetchone()[0])==checkpoint


def test_late_public_observation_cannot_overwrite_new_capture(world,monkeypatch):
    conn,config,bundle,add=world; text=add(42)
    def race(posting,**kw):
        conn.execute("UPDATE postings SET title='Replacement role' WHERE id=42");conn.commit()
        return _public_observation(posting,text=text+' new text')
    monkeypatch.setattr('pipeline.agentic.service.observe_posting',race)
    assert run_agentic_job(42,config,conn,evidence_bundle=bundle)==Stage.DLQ
    assert latest_result(conn,42)['reason']=='snapshot_changed'
    assert conn.execute('SELECT COUNT(*) FROM agentic_posting_observations').fetchone()[0]==0
    assert adtext.get_text(conn,42)[0]==text


def test_late_public_observation_cannot_overwrite_new_claim(world,monkeypatch):
    from pipeline.agentic import service
    conn,config,bundle,add=world; text=add(42)
    store=service.AgenticStore(conn);store.ensure()
    def race(posting,**kw):
        # Simulate a worker losing its lease while public browser was running.
        conn.execute('UPDATE agentic_runs SET lease_until=0');conn.commit()
        key=service._run_key(42,service._capture(conn,42),bundle,service.default_policy(),service._config(config))
        newer=store.claim(key,'newer-worker',60)
        store.release(newer,status='held',reason='newer_result')
        return _public_observation(posting,text=text+' old worker mutation')
    monkeypatch.setattr(service,'observe_posting',race)
    assert run_agentic_job(42,config,conn,evidence_bundle=bundle)==Stage.DLQ
    assert latest_result(conn,42)['reason']=='newer_result'
    assert conn.execute('SELECT COUNT(*) FROM agentic_posting_observations').fetchone()[0]==0
    assert adtext.get_text(conn,42)[0]==text


def test_expired_package_recovers_without_models_or_new_draft_admission(world,monkeypatch):
    conn,config,bundle,add=world;add(42)
    gateway=SyntheticGateway(bundle)
    original = PersistenceAdapter.finalize_package
    monkeypatch.setattr(PersistenceAdapter,'finalize_package',lambda *a,**kw: (_ for _ in ()).throw(OSError()))
    assert run_agentic_job(42,config,conn,evidence_bundle=bundle,llm=LLM(transport=gateway,keys=['synthetic']))==Stage.DLQ
    checkpoint=json.loads(conn.execute('SELECT checkpoint_json FROM agentic_runs').fetchone()[0])
    checkpoint['job_deadline']=1.0
    conn.execute('UPDATE agentic_runs SET checkpoint_json=?',(json.dumps(checkpoint),));conn.commit()
    calls=len(gateway.calls)
    charge = conn.execute('SELECT SUM(charged) FROM agentic_batches').fetchone()[0]
    config.settings['pipeline']['drafts_per_day'] = 0
    monkeypatch.setattr(PersistenceAdapter, 'finalize_package', original)
    assert run_agentic_job(42,config,conn,evidence_bundle=bundle)==Stage.READY
    assert len(gateway.calls)==calls
    assert conn.execute('SELECT SUM(charged) FROM agentic_batches').fetchone()[0] == charge
    assert conn.execute('SELECT COUNT(*) FROM agentic_draft_admissions').fetchone()[0] == 1


def test_timer_refreshes_only_missing_stale_or_source_mismatched_ready(world,monkeypatch):
    from datetime import datetime,timezone,timedelta
    from pipeline import store
    from pipeline.agentic import service
    from pipeline.nodes import ingest
    conn,config,bundle,add=world
    store.ensure(conn);service.AgenticStore(conn).ensure()
    for pid in range(1,5):
        text=add(pid)
        store.admit(conn,pid,str(pid),{},Stage.READY)
        if pid == 1: continue
        posting=service._posting(conn,pid)
        observation=_public_observation(posting,text=text)
        if pid==3:
            observation=observation.model_copy(update={'checked_at':(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()})
        conn.execute('INSERT INTO agentic_posting_observations(posting_id,run_key,generation,observation_json) VALUES(?,?,?,?)',
                     (pid,'synthetic-fixture',1,observation.model_dump_json()))
        if pid==4:conn.execute("UPDATE postings SET url=url||'/changed' WHERE id=?",(pid,))
    conn.commit()
    monkeypatch.setattr(ingest,'run',lambda *a,**kw:{})
    selected=[]
    monkeypatch.setattr(service,'agentic_batch_run',lambda ids,*a,**kw:selected.extend(ids) or {})
    service.after_collect(conn,config,max_seconds=60)
    assert selected==[1,3,4]


def test_blocker_gate_revision_invalidates_old_decision_identity(world, monkeypatch):
    from pipeline.agentic import service
    conn, config, bundle, add = world
    add(42)
    current = snapshot_inventory(conn, config, posting_ids=[42], evidence_bundle=bundle)[0]
    monkeypatch.setattr(service, 'IMPLEMENTATION_VERSION', 'deepagents-0.7.23-structured-output-20261011')
    old = snapshot_inventory(conn, config, posting_ids=[42], evidence_bundle=bundle)[0]
    assert current['run_key'] != old['run_key']
    assert current['candidate_hash'] == old['candidate_hash']


def test_location_reference_change_invalidates_decision_not_candidate(world, monkeypatch):
    from pipeline.agentic import service
    conn, config, bundle, add = world
    add(42)
    before = snapshot_inventory(conn, config, posting_ids=[42], evidence_bundle=bundle)[0]
    monkeypatch.setattr(service, 'LOCATION_REFERENCE_HASH', '0' * 64)
    after = snapshot_inventory(conn, config, posting_ids=[42], evidence_bundle=bundle)[0]
    assert before['run_key'] != after['run_key']
    assert before['candidate_hash'] == after['candidate_hash']


@pytest.mark.parametrize('research_role', ['complete_requirements', 'complete_job_assessment'])
def test_real_deepagents_research_checkpoints_on_file_database(world, monkeypatch, research_role):
    import threading
    from pipeline.agentic.store import AgenticStore
    conn, config, bundle, add = world
    add(46, low=True)
    config.settings['pipeline']['agentic']['research_enabled'] = True
    queries, checkpoint_errors = [], []
    main_thread = threading.get_ident()
    class Search:
        def search(self, query, **kwargs):
            queries.append((query, threading.get_ident()))
            return []
    monkeypatch.setattr('pipeline.agentic.service.LocalSearxSearch', Search)
    original_checkpoint = AgenticStore.checkpoint
    def checked_checkpoint(self, *args, **kwargs):
        try:
            return original_checkpoint(self, *args, **kwargs)
        except Exception as exc:
            checkpoint_errors.append((type(exc).__name__, threading.get_ident() == main_thread))
            raise
    monkeypatch.setattr(AgenticStore, 'checkpoint', checked_checkpoint)
    class ResearchGateway(SyntheticGateway):
        def __call__(self, url, headers, body, timeout):
            status, payload = super().__call__(url, headers, body, timeout)
            if self.calls[-1] == research_role and len(body['messages']) == 2:
                payload['choices'][0]['message']['content'] = json.dumps({
                    'tool': 'research_employer', 'arguments': {'intent': 'employer_identity'}})
            return status, payload
    summary = agentic_batch_run([46], config, conn, evidence_bundle=bundle,
                               llm=LLM(transport=ResearchGateway(bundle), keys=['synthetic']))
    assert checkpoint_errors == []
    assert summary['archived'] == 1 and summary['held'] == 0
    assert len(queries) == 1 and queries[0][1] != main_thread
    cp = json.loads(conn.execute('SELECT checkpoint_json FROM agentic_runs').fetchone()[0])
    assert cp['research_queries'] == 1 and cp['research_pages'] == 0
    assert latest_result(conn, 46)['evaluation']['research_available'] is True
