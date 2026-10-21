"""Default-off real career-ops orchestration with immutable resumable artifacts."""
from __future__ import annotations

import base64
import json
import sqlite3
import threading
from pathlib import Path
import time
import uuid
from typing import Any

from jobwatch import adtext
from jobwatch.apply.paths import profile_dir
from jobwatch.candidate.analysis import analyse_candidate
from jobwatch.candidate.inputs import load_inputs
from jobwatch.candidate.assessment import (CandidateAssessment, assessment_run_key, evaluate_candidate,
                                          validate_assessment)
from jobwatch.candidate.contracts import TargetPolicy, content_hash, digest
from jobwatch.candidate.evidence import career_profile_text, snapshot_evidence, verify_evidence_snapshot
from jobwatch.candidate.policy import default_policy
from jobwatch.llm import LLM
from jobwatch.openrouter_extras import (KNOCKOUT_REASONS, extras_settings, jev_screen, rank_by_target,
                                       same_vacancy, vectors)
from pipeline import store as pipeline_store
from pipeline.schemas import Stage
from pipeline.agentic.contracts import AgenticError, AgenticEvaluation, DraftProposal, PackageManifest, ReviewVerdict, RunKey
from pipeline.agentic.evaluator import evaluate_job
from pipeline.agentic.gate import decide
from pipeline.agentic.location import LOCATION_REFERENCE_HASH, km_from_home
from pipeline.agentic.draft import DraftArtifacts, draft_and_review, profile_from_snapshot
from pipeline.agentic import jev_skills
from pipeline.agentic.forms import build_form_map
from pipeline.agentic.persistence import PersistenceAdapter, latest_result
from pipeline.agentic.runtime import BatchBudget, JobBudget, validate_model_payload
from pipeline.agentic.store import AgenticStore
from pipeline.agentic.liveness import observe_posting, latest_observation, observation_current
from pipeline.agentic.research import LocalSearxSearch, PublicSnapshot, ResearchCapability, SafeFetcher
from jobwatch.settings import DEFAULT_MODEL


RUBRIC_VERSION = 'career-ops-v1'
MODEL_PASS_SECONDS = 120   # the judging pass of a job (evaluator, 3-10 model turns) is not started with less than this left;
#   102 of 104 model holds were a job started with 30-180 s left, cut off by the clock. It goes first in the next run instead.
MIN_READ_SECONDS = 20   # less than this left in the batch: do not start another job (a Seek page read needs 7-15 s)
IMPLEMENTATION_VERSION = 'deepagents-0.7.23-qwen-retrieval-20261021'


def settings(config) -> dict:
    return config.settings if hasattr(config, 'settings') else config


def agentic_settings(config) -> dict:
    """Read the deployed Config shape, retaining callers using pipeline settings."""
    root = settings(config)
    pipeline = root.get('pipeline')
    raw = pipeline.get('agentic', {}) if isinstance(pipeline, dict) and 'agentic' in pipeline else root.get('agentic', {})
    return raw if isinstance(raw, dict) else {}


def enabled(config) -> bool:
    from jobwatch.execution_mode import effective_mode
    return effective_mode(config) == 'agentic'


def _config(config):
    raw = agentic_settings(config)
    credential_index = raw.get('credential_index', 0)
    if type(credential_index) is not int or credential_index < 0:
        raise AgenticError('invalid_configuration')
    if type(raw.get('research_enabled', False)) is not bool:
        raise AgenticError('invalid_configuration')
    from jobwatch.model_choice import chosen   # the person's own pick wins over config/jobwatch.yaml
    pick = chosen()
    values = {'worker_model': pick.get('writer') or raw.get('worker_model', DEFAULT_MODEL),
              'evaluator_model': pick.get('evaluator') or raw.get('evaluator_model', DEFAULT_MODEL),
              'reviewer_model': pick.get('reviewer') or raw.get('reviewer_model', DEFAULT_MODEL),
              'answer_model': pick.get('answers') or raw.get('answer_model', DEFAULT_MODEL),
              'credential_index': credential_index,
              'embedding_model': raw.get('embedding_model'),
              'research_enabled': raw.get('research_enabled', False),
              'job_token_ceiling': int(raw.get('job_token_ceiling', 250_000)),
              'batch_token_ceiling': int(raw.get('batch_token_ceiling', 2_000_000)),
              'job_seconds': min(900, float(raw.get('job_seconds', 900))),
              'batch_seconds': min(1800, float(raw.get('batch_seconds', 1800)))}
    if values['embedding_model'] is not None:
        from pipeline.agentic.execution import embedding_model_allowed
        if not embedding_model_allowed(values['embedding_model']):
            raise AgenticError('invalid_configuration')
    for name in ('occupation_reference_path', 'occupation_mappings_path'):
        value = raw.get(name)
        if value is not None and (type(value) is not str or not value.strip()):
            raise AgenticError('invalid_configuration')
        values[name] = value
    if any(values[k] <= 0 for k in ('job_token_ceiling', 'batch_token_ceiling', 'job_seconds', 'batch_seconds')):
        raise AgenticError('invalid_configuration')
    return values


def _draft_limits(config):
    root = settings(config)
    raw = root.get('pipeline', root)
    limits = tuple(raw.get(name, default) for name, default in
                   (('drafts_per_run', 3), ('drafts_per_day', 10)))
    if any(type(value) is not int or value < 0 for value in limits):
        raise AgenticError('invalid_configuration')
    return limits


def _research(posting, budget, cfg):
    if not cfg['research_enabled']:
        return None
    try:
        public = PublicSnapshot(posting['company'], posting['title'], posting['url'])
    except (KeyError, ValueError, TypeError):
        return None
    return ResearchCapability(public, search_provider=LocalSearxSearch(), fetcher=SafeFetcher(),
                              budget=budget, deadline=time.time() + max(0, budget.remaining_seconds()))


def configured_llm(config):
    """Use exactly the configured existing gateway credential, without fallback."""
    from jobwatch.llm import load_keys
    from jobwatch.model_choice import own_key
    selected = 0 if own_key() else _config(config)['credential_index']
    keys = load_keys()
    if selected >= len(keys):
        raise AgenticError('credential_unavailable')
    return LLM(keys=[keys[selected]])


def _posting(conn, posting_id):
    cursor = conn.execute('SELECT * FROM postings WHERE id=?', (posting_id,))
    row = cursor.fetchone()
    return dict(zip((d[0] for d in cursor.description), row)) if row else None


def _capture(conn, posting_id):
    posting = _posting(conn, posting_id)
    if posting is None:
        return None
    text, kind = adtext.local_text(conn, posting)
    identity = {k: posting.get(k) or '' for k in ('title', 'company', 'location', 'url', 'source')}
    return identity, text, kind


def _run_key(posting_id, captured, bundle, policy, cfg, inputs=None, structural=None):
    posting, text, _ = captured
    reference, mappings = load_inputs(bundle, cfg) if inputs is None else inputs
    structural = structural or analyse_candidate(bundle, reference, mappings, policy)
    candidate_hash = assessment_run_key(bundle.bundle_hash, content_hash(career_profile_text(bundle).encode()),
                                        digest(policy.model_dump(mode='json')), structural.run_key, cfg['evaluator_model'])
    return RunKey(posting_id=posting_id, ad_hash=content_hash(text.encode()), evidence_hash=bundle.bundle_hash,
                  rubric_version=RUBRIC_VERSION, candidate_hash=candidate_hash,
                  config_hash=digest({'policy': policy.model_dump(mode='json'), 'runtime': cfg,
                                      'implementation': IMPLEMENTATION_VERSION,
                                      'location_reference': LOCATION_REFERENCE_HASH, 'posting': posting}))


def snapshot_inventory(conn, config, *, posting_ids=None, limit=20, evidence_bundle=None, policy=None):
    """Read-only inventory: no schema creation, profile writes, gateway, or fetching."""
    if type(limit) is not int or not 1 <= limit <= 20:
        raise AgenticError('invalid_limit')
    cfg, pol = _config(config), policy or default_policy()
    bundle = evidence_bundle or snapshot_evidence(profile_dir())
    verify_evidence_snapshot(bundle)
    if posting_ids is not None:
        ids = list(dict.fromkeys(posting_ids))
    else:
        # Newest first, but reserve part of every batch for postings whose last run could only end
        # "unknown" (`posting_unavailable` and friends). Newest-only selection meant a failed read was
        # never retried and the posting was stranded: 874 of them by 2026-10-13, while a re-read of a
        # sampled few now succeeds. This does not relax any gate; it only gives them another read.
        retry = max(1, limit // 4)
        newest = [r[0] for r in conn.execute(
            'SELECT id FROM postings ORDER BY last_seen_at DESC,id DESC LIMIT ?', (limit - retry,))]
        stale = []
        # The inventory must not assume the pipeline's own tables exist yet (a fresh database has none).
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agentic_runs'").fetchone():
            stale = [r[0] for r in conn.execute(
                'SELECT r.posting_id FROM agentic_runs r '
                'WHERE r.rowid IN (SELECT MAX(rowid) FROM agentic_runs GROUP BY posting_id) '
                "AND r.reason IN ('posting_unavailable','posting_identity_unverified','posting_check_required','deadline_exceeded') "
                'ORDER BY r.rowid ASC LIMIT ?', (retry,))]
        ids = list(dict.fromkeys(newest + stale))
    inputs = load_inputs(bundle, cfg)
    structural = analyse_candidate(bundle, *inputs, pol)
    result = []
    for ident in ids[:limit]:
        captured = _capture(conn, ident)
        if captured is None:
            continue
        key = _run_key(ident, captured, bundle, pol, cfg, inputs, structural)
        result.append({'posting_id': ident, 'run_key': key.value, 'ad_hash': key.ad_hash,
                       'evidence_hash': key.evidence_hash, 'candidate_hash': key.candidate_hash,
                       'text_kind': captured[2], 'eligible_for_evaluation': captured[2] == 'full'})
    return result


def _make_batch(store, cfg, *, seconds=None, batch_id=None):
    ident = batch_id or 'agentic-' + uuid.uuid4().hex
    row = store.conn.execute('SELECT token_ceiling,charged,deadline,state FROM agentic_batches WHERE batch_id=?',
                             (ident,)).fetchone()
    if row is None:
        deadline = time.time() + min(cfg['batch_seconds'], seconds if seconds is not None else cfg['batch_seconds'])
        store.create_batch(ident, cfg['batch_token_ceiling'], deadline)
        row = (cfg['batch_token_ceiling'], 0, deadline, 'active')
    batch = BatchBudget(ident, token_ceiling=row[0], deadline=row[2])
    batch._state.charged_tokens = row[1]
    batch._state.circuit_open = row[3] != 'active'
    return batch


def _budget(store, claim, cfg, batch, batch_registry=None, invocation_deadline=None):
    if invocation_deadline is None:
        invocation_deadline = batch.deadline if batch is not None else time.time() + cfg['batch_seconds']
    offset = store.resume_quota_clock(claim)
    prior = store.load_checkpoint(claim)
    if prior is not None and prior.job_deadline <= time.time() - offset:
        # An old run's deadline has passed: every resume would fail at once ("posting_unavailable"), so start fresh.
        store.discard_checkpoint(claim)
        prior = None
    if prior is not None and (batch is None or prior.batch_id != batch.batch_id):
        batch = (batch_registry or {}).get(prior.batch_id) or _make_batch(store, cfg, batch_id=prior.batch_id)
    elif batch is None:
        batch = _make_batch(store, cfg)
    if batch_registry is not None:
        batch_registry[batch.batch_id] = batch

    owner_thread = threading.get_ident()
    database_path = next((row[2] for row in store.conn.execute("PRAGMA database_list")
                          if row[1] == "main"), "")

    def persist(value, **kwargs):
        # Deep Agents executes tools on worker threads. Each worker checkpoint
        # owns its SQLite connection; fences and transition checks stay in the
        # same store implementation, without disabling SQLite thread safety.
        worker_conn = None
        target = store
        try:
            if threading.get_ident() != owner_thread:
                if not database_path:
                    raise AgenticError('checkpoint_unavailable')
                worker_conn = sqlite3.connect(Path(database_path).as_uri() + '?mode=rw',
                                              uri=True, timeout=30)
                worker_conn.execute("PRAGMA foreign_keys=ON")
                worker_conn.execute("PRAGMA busy_timeout=30000")
                target = AgenticStore(worker_conn, clock=store.clock)
            actual = target.checkpoint(claim, value, **kwargs)
            batch._state.charged_tokens = actual.batch_charged
            if batch._state.circuit_open:
                target.conn.execute("UPDATE agentic_batches SET state='paused' WHERE batch_id=?", (batch.batch_id,))
                target.conn.commit()
            return actual
        finally:
            if worker_conn is not None:
                worker_conn.close()

    if prior is not None:
        job = JobBudget.restore(prior, batch=batch, persist=persist, clock=lambda: time.time() - offset)
    else:
        job = JobBudget(claim.run_key, batch, persist=persist, token_ceiling=cfg['job_token_ceiling'],
                        deadline=min(time.time() + cfg['job_seconds'], batch.deadline))
        job._commit('snapshot')
    job._invocation_deadline = invocation_deadline
    return job


def _restore_package(value, evaluation):
    try:
        return DraftArtifacts(validate_model_payload(PackageManifest, value['manifest']), evaluation,
            validate_model_payload(DraftProposal, value['proposal']), validate_model_payload(ReviewVerdict, value['review']),
            value['verify'], base64.b64decode(value['cv'], validate=True), base64.b64decode(value['letter'], validate=True),
            value['cv_markdown'], value['letter_markdown'])
    except Exception:
        pass
    raise AgenticError('artifact_invalid') from None


def _package_payload(value):
    return {'manifest': value.manifest.model_dump(mode='json'), 'proposal': value.proposal.model_dump(mode='json'),
            'review': value.review.model_dump(mode='json'), 'verify': value.verify_report,
            'cv': base64.b64encode(value.cv_bytes).decode('ascii'),
            'letter': base64.b64encode(value.letter_bytes).decode('ascii'),
            'cv_markdown': value.cv_markdown, 'letter_markdown': value.letter_markdown}


def run_agentic_job(posting_id: int, config, conn: sqlite3.Connection, *, policy: TargetPolicy | None = None,
                    evidence_bundle=None, llm=None, llm_drafter=None, llm_reviewer=None,
                    batch: BatchBudget | None = None, candidate_cache: dict | None = None,
                    expected_run_key: str | None = None, _batch_registry: dict | None = None,
                    _invocation_deadline: float | None = None, operation: str = 'prepare',
                    _skip_reasons=None, collector_run_id=None) -> Stage | None:
    if operation not in ('evaluate', 'prepare'):
        raise AgenticError('invalid_operation')
    def skip(reason, next_eligible_at=None):
        if _skip_reasons is not None:
            _skip_reasons.append({'posting_id': posting_id, 'reason': reason, 'next_eligible_at': next_eligible_at})
    if not enabled(config):
        skip('agentic_disabled')
        return None
    cfg, pol = _config(config), policy or default_policy()
    draft_limits = _draft_limits(config)
    invocation_id = batch.batch_id if batch is not None else 'agentic-' + uuid.uuid4().hex
    if _invocation_deadline is None:
        _invocation_deadline = batch.deadline if batch is not None else time.time() + cfg['batch_seconds']
    bundle = evidence_bundle or snapshot_evidence(profile_dir())
    verify_evidence_snapshot(bundle)
    captured = _capture(conn, posting_id)
    if captured is None:
        skip('posting_missing')
        return None
    reference, mappings = load_inputs(bundle, cfg)
    key = _run_key(posting_id, captured, bundle, pol, cfg, (reference, mappings))
    if expected_run_key is not None and key.value != expected_run_key:
        raise AgenticError('snapshot_changed')
    store = AgenticStore(conn)
    store.ensure(); pipeline_store.ensure(conn)
    adapter = PersistenceAdapter(conn, store)
    adapter.reconcile()
    previous = latest_result(conn, posting_id)
    cached_ready = bool(previous and previous['run_key'] == key.value
                        and previous.get('package_phase') == 'complete'
                        and ((previous['stored_status'] == 'ready' and
                              (previous['status'] == 'ready' or previous['reason'] == 'posting_check_required'))
                             or previous['reason'] in {'posting_unavailable','posting_identity_unverified','posting_closed'}))
    # Rule archives are re-checked against today's gate on the saved evaluation (no new model call), so an owner
    # rule change applies to jobs already judged (2026-10-12: Morrows kept its old 4.0 verdict after the 3.5 ruling).
    if (previous and previous['run_key'] == key.value and previous['status'] == 'archived'
            and previous['reason'] not in {'posting_closed', 'score_below_threshold', 'hard_gate'}):
        return Stage.ARCHIVED
    # Lease outlasts the whole bounded role execution, including PDF and journaling.
    claim = store.claim(key, 'agentic-' + uuid.uuid4().hex, cfg['job_seconds'] + 180)
    if claim is None:
        lease = conn.execute('SELECT lease_until FROM agentic_runs WHERE run_key=?', (key.value,)).fetchone()
        skip('lease_conflict', lease[0] if lease else None)
        return None
    from pipeline.agentic.execution import current
    scope = current()
    trace_id = scope.run_id if scope else invocation_id
    def activity(event, code=None):
        conn.execute('INSERT INTO agentic_activity(run_key,posting_id,collector_run_id,batch_id,invocation_id,event,at,reason) '
                     'VALUES(?,?,?,?,?,?,?,?)', (key.value, posting_id, collector_run_id,
                     batch.batch_id if batch else invocation_id, trace_id, event, time.time(), code))
        conn.commit()
        if scope:
            scope.event('job_' + event, posting_id=posting_id, run_key=key.value, reason=code)
    activity('started')
    budget = None
    stage, reason, final_status = Stage.DLQ, 'execution_failed', 'held'
    try:
        # Cached READY rechecks are public-only and do not renew exhausted model budgets.
        saved_package = adapter.load_artifact(key.value, 'package_bundle')
        if cached_ready or saved_package is not None:
            remaining = min(60, cfg['job_seconds'], _invocation_deadline-time.time())
        else:
            budget = _budget(store, claim, cfg, batch, _batch_registry, _invocation_deadline)
            remaining = min(60, budget.remaining_seconds())  # Atlassian pages need ~35 s
        if remaining < MIN_READ_SECONDS:
            raise AgenticError('deadline_exceeded')
        observation = observe_posting({'id': posting_id, **captured[0]}, deadline=time.monotonic()+max(0,remaining))
        changed = adapter.record_observation(claim, observation, captured)
        try:
            from jobwatch import expiry
            expiry.record(conn, posting_id, observation)
        except Exception:  # noqa: BLE001 - expiry bookkeeping never changes a run's result
            pass
        if observation.status != 'active':
            reason = observation.reason
            if observation.status == 'closed':
                stage, final_status = Stage.ARCHIVED, 'archived'
            return stage
        if changed:
            raise AgenticError('snapshot_changed')
        if cached_ready:
            for kind in ('manifest', 'cv', 'letter', 'proposal', 'review', 'evaluation', 'candidate', 'form_map'):
                if adapter.load_artifact(key.value, kind) is None:
                    raise AgenticError('artifact_invalid')
            if _capture(conn, posting_id) != captured:
                raise AgenticError('snapshot_changed')
            adapter.set_stage(claim, Stage.READY, 'agentic_package_ready', key.ad_hash,
                              application_id=previous['application_id'], draft_id=previous['draft_id'])
            stage, reason, final_status = Stage.READY, 'agentic_package_ready', 'ready'
            return stage
        if saved_package is None:
            budget.ensure_live()
        posting, ad_text, text_kind = captured
        snapshot = {'run_key': key.model_dump(mode='json'), 'posting': posting, 'full_ad': ad_text,
                    'text_kind': text_kind, 'sources': dict(bundle.sources),
                    'contents': {name: raw.decode('utf-8') for name, raw in bundle.contents.items()}}
        adapter.save_artifact(claim, 'snapshot', snapshot)
        adapter.save_artifact(claim, 'structural_inputs', {
            'reference_utf8': reference.raw_contents.decode('utf-8') if reference else None,
            'reference_hash': reference.reference_hash if reference else None,
            'mappings': [m.model_dump(mode='json') for m in mappings]})
        # Jev (OpenRouter, public ad text only), before Opus reads the ad: hidden instructions aimed at the AI
        # hold the job; a requirement the ad states that the owner cannot meet archives it (owner, 2026-10-12).
        # None means Jev was not reached; the job then runs exactly as before.
        screen = jev_screen(ad_text, config) if text_kind == 'full' and saved_package is None else None
        extras = extras_settings(config)
        knockout = next((KNOCKOUT_REASONS[q] for q, at in extras['knockout_at'].items()
                         if screen is not None and screen.get(q, 0) >= float(at)), None)
        if text_kind != 'full':
            reason = 'insufficient_evidence'
        elif screen is not None and screen['injection'] >= float(extras['jev_hold_at']):
            reason = 'ad_has_ai_instructions'
        elif knockout is not None:
            stage, reason, final_status = Stage.ARCHIVED, knockout, 'archived'
        else:
            # A completed package can recover without loading any credential.
            if llm is None and saved_package is None:
                llm = configured_llm(config)
            saved_candidate = adapter.load_artifact(key.value, 'candidate')
            if saved_package is not None and saved_candidate is None:
                raise AgenticError('artifact_invalid')
            if saved_candidate is not None:
                candidate = validate_assessment(validate_model_payload(CandidateAssessment, saved_candidate), bundle, pol)
            elif candidate_cache is not None and key.candidate_hash in candidate_cache:
                candidate = validate_assessment(candidate_cache[key.candidate_hash], bundle, pol)
            else:
                candidate = evaluate_candidate(bundle, budget, llm, policy=pol, model=cfg['evaluator_model'],
                                               reference=reference, mappings=mappings)
                if candidate_cache is not None:
                    candidate_cache[key.candidate_hash] = candidate
            expected_structural = analyse_candidate(bundle, reference, mappings, pol)
            if candidate.structural_analysis != expected_structural:
                raise AgenticError('candidate_hash_mismatch')
            if candidate.run_key != key.candidate_hash:
                raise AgenticError('candidate_hash_mismatch')
            adapter.save_artifact(claim, 'candidate', candidate.model_dump(mode='json'))
            from pipeline.agentic.model_insights import pipeline_insights
            models = adapter.load_artifact(key.value, 'model_insights')
            if models is None:
                models = pipeline_insights(conn, config, bundle=bundle, policy=pol, cfg=cfg,
                                           structural=expected_structural)
                adapter.save_artifact(claim, 'model_insights', models)
            saved_evaluation = adapter.load_artifact(key.value, 'evaluation')
            if saved_package is not None and saved_evaluation is None:
                raise AgenticError('artifact_invalid')
            evaluation = validate_model_payload(AgenticEvaluation, saved_evaluation) if saved_evaluation is not None else evaluate_job(
                key, ad_text, budget, llm, evidence_bundle=bundle, candidate_analysis=candidate,
                model=cfg['evaluator_model'], research=_research(posting, budget, cfg),
                commute_km=km_from_home(posting.get('location') or ''), model_insights=models,
                embedding_model=cfg['embedding_model'])
            decision = decide(evaluation, ad_text=ad_text, title=posting['title'], policy=pol,
                              captured_complete=text_kind == 'full', expected_run_key=key, evidence_bundle=bundle,
                              commute_km=km_from_home(posting.get('location') or ''))
            adapter.save_artifact(claim, 'evaluation', evaluation.model_dump(mode='json'))
            # Jev skills (owner 2026-10-12, career facts only): a second-opinion fit score and a requirement map
            # for the board and the writer. Failures only mean they are missing.
            # Candidate-derived facts may only use the approved paid gateway.
            # Legacy direct Jev/vector extras have no approved candidate route.
            facts = []
            requirement_map = []
            if saved_package is None and facts:
                fit = jev_skills.fit_scores(ad_text, facts, config)
                if fit is not None:
                    jev_skills.save(conn, posting_id, key.ad_hash, 'fit', fit)
                requirement_map = jev_skills.requirement_map(
                    [r.model_dump(mode='json') for r in evaluation.requirements.requirements], facts,
                    adtext.lock_path(config).parent / 'evidence-vectors.sqlite', config)
                if requirement_map:
                    jev_skills.save(conn, posting_id, key.ad_hash, 'requirements', requirement_map)
            if decision.route != 'draft':
                stage = Stage.ARCHIVED if decision.route == 'archive' else Stage.DLQ
                reason, final_status = decision.reason, 'archived' if decision.route == 'archive' else 'held'
            elif operation == 'evaluate':
                reason = 'evaluation_complete'
            else:
                if saved_package is None:
                    budget.ensure_live()
                    quota_reason = store.admit_draft(claim, invocation_id, *draft_limits)
                    if quota_reason is not None:
                        reason = quota_reason
                        return stage
                company = adapter.load_artifact(key.value, 'company_research')
                if saved_package is None and company is None:
                    from pipeline.agentic.company_research import run_company_researcher
                    company = run_company_researcher(ad_text, _research(posting, budget, cfg), budget,
                        llm_drafter or llm, model=cfg['worker_model'], run_key=key)
                    adapter.save_artifact(claim, 'company_research', company)
                artifacts = _restore_package(saved_package, evaluation) if saved_package is not None else draft_and_review(
                    key, evaluation, budget, llm_drafter=llm_drafter or llm, llm_reviewer=llm_reviewer or llm,
                    return_bundle=True, evidence_bundle=bundle, posting=posting, ad_text=ad_text,
                    worker_model=cfg['worker_model'], reviewer_model=cfg['reviewer_model'],
                    requirement_map=requirement_map, jev_facts=facts, jev_config=config,
                    company_research=company, model_insights=models,
                    research=_research(posting, budget, cfg))  # the writer researches the employer too (owner 2026-10-20)
                adapter.save_artifact(claim, 'package_bundle', _package_payload(artifacts))
                if saved_package is None:
                    budget.ensure_live()
                if _run_key(posting_id, captured, bundle, pol, cfg).value != key.value:
                    raise AgenticError('snapshot_changed')
                if _capture(conn, posting_id) != captured:
                    raise AgenticError('snapshot_changed')
                result = adapter.finalize_package(claim, artifacts.manifest, artifacts.cv_bytes, artifacts.letter_bytes,
                                                   operation_id='finalize-' + key.value, artifacts=artifacts)
                form_map = build_form_map(evaluation, artifacts.proposal.screening_answers, evidence_bundle=bundle,
                                          application_id=result['application_id'], url=posting['url'])
                from pathlib import Path
                adapter.save_artifact(claim, 'form_map', form_map.model_dump(mode='json'),
                                      path=Path(result['package_dir']) / 'form_map.json')
                adapter.set_stage(claim, Stage.READY, 'agentic_package_ready', key.ad_hash,
                                  application_id=result['application_id'], draft_id=result['draft_id'])
                stage, reason, final_status = Stage.READY, 'agentic_package_ready', 'ready'
    except Exception as exc:
        # Framework/provider details may include candidate content. Persist only
        # codes owned by this codebase; never repr/str an arbitrary exception.
        code = getattr(exc, 'code', None)
        reason = code if isinstance(exc, AgenticError) and type(code) is str and code.replace('_', '').isalnum() else 'execution_failed'
    finally:
        try:
            if stage != Stage.READY:
                adapter.set_stage(claim, stage, reason, key.ad_hash)
            store.release(claim, status=final_status, reason=reason)
            activity('finished', reason)
        except AgenticError:
            # A stale worker cannot overwrite the current worker's projection.
            pass
        if budget is not None:
            budget.batch.release(budget)
    return stage


def agentic_batch_run(snapshot_ids, config, conn, *, batch_id=None, max_seconds=None, expected_run_keys=None, **kwargs):
    summary = {'processed': 0, 'ready': 0, 'archived': 0, 'held': 0, 'skipped': 0,
               'deferred': [], 'skipped_reasons': {}}
    if not enabled(config):
        return summary
    store = AgenticStore(conn); store.ensure()
    cfg = _config(config)
    invocation_deadline = time.time() + min(cfg['batch_seconds'],
                                           max_seconds if max_seconds is not None else cfg['batch_seconds'])
    previous_charges = dict(conn.execute('SELECT batch_id,charged FROM agentic_batches'))
    batch = _make_batch(store, cfg, seconds=max_seconds, batch_id=batch_id)
    batches = {batch.batch_id: batch}
    bundle = kwargs.pop('evidence_bundle', None) or snapshot_evidence(profile_dir())
    cache = {}
    todo = list(dict.fromkeys(snapshot_ids))[:20]
    for n, pid in enumerate(todo):
        if expected_run_keys is not None and pid not in expected_run_keys:
            raise AgenticError('snapshot_changed')
        if invocation_deadline - time.time() < MODEL_PASS_SECONDS:
            # Out of time. A job started with ~0 s can only be recorded as "posting_unavailable" without being read,
            # and that false hold sends it to the back of the rotation; leave the rest untouched for the next run.
            summary['skipped'] += len(todo) - n
            summary['deferred'].extend({'posting_id': p, 'reason': 'batch_deadline', 'next_eligible_at': None} for p in todo[n:])
            break
        skips = []
        stage = run_agentic_job(pid, config, conn, batch=batch, evidence_bundle=bundle,
                                candidate_cache=cache, _batch_registry=batches, _invocation_deadline=invocation_deadline,
                                expected_run_key=expected_run_keys.get(pid) if expected_run_keys is not None else None,
                                _skip_reasons=skips, **kwargs)
        last = conn.execute("SELECT reason FROM agentic_runs WHERE posting_id=? ORDER BY rowid DESC LIMIT 1",
                            (pid,)).fetchone()
        if stage == Stage.DLQ and expected_run_keys is None and last is not None and last[0] == 'snapshot_changed' \
                and invocation_deadline - time.time() >= MODEL_PASS_SECONDS:
            # The first pass only refreshed the full ad text; judge the refreshed ad now, not on the next timer run.
            # Skip the retry once the batch deadline has passed: a job started with ~0 s can only be recorded as
            # "posting_unavailable" without being read, and that false hold sends it to the back of the rotation.
            stage = run_agentic_job(pid, config, conn, batch=batch, evidence_bundle=bundle,
                                    candidate_cache=cache, _batch_registry=batches,
                                    _invocation_deadline=invocation_deadline, **kwargs)
        if stage is None:
            summary['skipped'] += 1
            summary['deferred'].extend(skips or [{'posting_id': pid, 'reason': 'not_admitted', 'next_eligible_at': None}])
            continue
        summary['processed'] += 1
        summary[{Stage.READY: 'ready', Stage.ARCHIVED: 'archived', Stage.DLQ: 'held'}[stage]] += 1
        if stage == Stage.READY:
            _tell_owner_ready(conn, pid)
        elif stage == Stage.DLQ:
            _alert_if_error(conn, pid)
    summary['batch_id'] = batch.batch_id
    # Resumed jobs retain their original conservative batch ceilings, deadlines
    # and circuit state. Expose every participating identity instead of hiding
    # their charges behind the fresh batch used by new jobs.
    summary['batches'] = [{'batch_id': ident, 'charged_tokens': value.charged_tokens,
                          'token_ceiling': value._state.token_ceiling,
                          'deadline': value.deadline, 'paused': value._state.circuit_open}
                         for ident, value in batches.items()]
    summary['charged_tokens'] = sum(value.charged_tokens for value in batches.values())
    summary['spent_tokens'] = sum(value.charged_tokens - previous_charges.get(ident, 0)
                                  for ident, value in batches.items())
    for item in summary['deferred']:
        summary['skipped_reasons'][item['reason']] = summary['skipped_reasons'].get(item['reason'], 0) + 1
    return summary


def _tell_owner_ready(conn, pid):
    """A READY job goes to the board's chat history; notify() does not push it."""
    try:
        from jobwatch.notify import BOARD, notify
        row = conn.execute("SELECT title, company FROM postings WHERE id=?", (pid,)).fetchone()
        title, company = (row[0], row[1]) if row else ("a job", "")
        notify(conn, f"Ready for you: {title}{' at ' + company if company else ''}. CV and cover letter are done; "
                     f"the form fills next and stops before Submit. {BOARD}/job/{pid}")
    except Exception:  # noqa: BLE001 - a failed message never fails the run
        pass


def _alert_if_error(conn, pid):
    """A job stopped by a jobwatch failure (not a normal decision) texts the owner via Hermes, once a day per kind."""
    try:
        from jobwatch.notify import ERROR_REASONS, alert
        row = conn.execute("SELECT r.reason, p.title FROM agentic_runs r JOIN postings p ON p.id=r.posting_id "
                           "WHERE r.posting_id=? ORDER BY r.rowid DESC LIMIT 1", (pid,)).fetchone()
        if row and row[0] in ERROR_REASONS:
            alert(conn, f"jobwatch stopped on \"{row[1]}\" ({row[0]}). Claude Code needs to look.",
                  row[0])
    except Exception:  # noqa: BLE001 - a failed message never fails the run
        pass


def after_collect(conn, config, max_seconds=None, collector_run_id=None):
    if not enabled(config):
        return {'skipped': 'disabled'}
    started = time.monotonic()
    with adtext.review_lock(adtext.lock_path(config)) as acquired:
        if not acquired:
            return {'skipped': 'busy'}
        from pipeline.nodes import ingest
        # Collection/ad capture is deterministic and may fetch public full ads.
        ingest.run(conn, config, limit=200, fetch_budget=25)
        _near_duplicates(conn, config)
        # Reserve space for both unfinished work and public READY refreshes.
        # Each successful attempt updates pipeline_state.updated_at, rotating the
        # queues so an old held job or a large READY backlog cannot starve either.
        pending, refresh = [], []
        # A matched posting the pipeline has never attempted has no pipeline_state row, so the loop
        # below cannot see it and it waits forever (258 of them on 2026-10-13). Keep a share of every
        # queue for those; they gain a row on their first attempt, so this empties itself.
        unseen = [r[0] for r in conn.execute(
            'SELECT m.posting_id FROM matches m '
            'WHERE m.posting_id NOT IN (SELECT posting_id FROM pipeline_state) '
            'ORDER BY m.posting_id LIMIT 100')]
        for pid, stage in conn.execute('SELECT posting_id,stage FROM pipeline_state WHERE stage<>? '
                                       'ORDER BY updated_at,posting_id', (str(Stage.ARCHIVED),)):
            if stage != str(Stage.READY):
                if len(pending) < 200: pending.append(pid)
            elif len(refresh) < 20:
                captured = _capture(conn, pid)
                if captured and not observation_current(latest_observation(conn, pid), posting_id=pid,
                        url=captured[0]['url'], ad_hash=content_hash(captured[1].encode())):
                    refresh.append(pid)
            if len(pending) == 200 and len(refresh) == 20: break
        AgenticStore(conn).ensure()
        pending = [pid for pid in unseen[:25] + pending if not _unreadable_backoff(conn, pid)]
        pending = _target_first(conn, config, pending)
        # A posting whose last run only refreshed its ad text (snapshot_changed) needs just the second pass; without
        # this it went to the back of the queue every time and 7029 never got its judgement.
        again = [pid for pid in pending if (conn.execute('SELECT reason FROM agentic_runs WHERE posting_id=? '
                 'ORDER BY rowid DESC LIMIT 1', (pid,)).fetchone() or ('',))[0] == 'snapshot_changed'][:5]
        pending = again + [pid for pid in pending if pid not in again]
        # Jobs the model step failed on (provider error, bad format) were never judged; read them before the rest.
        retry = [pid for pid in pending if pid not in again and (conn.execute('SELECT reason FROM agentic_runs WHERE '
                 'posting_id=? ORDER BY rowid DESC LIMIT 1', (pid,)).fetchone() or ('',))[0] in MODEL_RETRY][:8]
        pending = again + retry + [pid for pid in pending if pid not in again and pid not in retry]
        ids = []
        for index in range(20):
            for queue in (pending, refresh):
                if index < len(queue) and len(ids) < 20: ids.append(queue[index])
        # Ingest, duplicate check and ordering count against the same unit budget (2026-10-12: they ran outside
        # it and the fast timer was killed at systemd's 15 min limit).
        if max_seconds is not None:
            max_seconds = max(60, max_seconds - (time.monotonic() - started))
        return agentic_batch_run(ids, config, conn, max_seconds=max_seconds, collector_run_id=collector_run_id)


MODEL_RETRY = ('model_unavailable', 'model_invalid_response', 'model_truncated_response', 'invalid_requirements')
UNREADABLE = ('posting_unavailable', 'posting_identity_unverified')
UNREADABLE_TRIES, UNREADABLE_WAIT_H = 3, 12


def _unreadable_backoff(conn, pid, now=None):
    """True when the last UNREADABLE_TRIES runs of this posting all failed to read the page and the newest is under
    UNREADABLE_WAIT_H old: it is left alone for now so the run time goes to ads that can be read (2026-10-18: five
    dead PageUp links cost a run every 20 minutes). A different outcome, or the wait passing, brings it back."""
    rows = conn.execute('SELECT reason, json_extract(checkpoint_json,\'$.job_deadline\') FROM agentic_runs '
                        'WHERE posting_id=? ORDER BY rowid DESC LIMIT ?', (pid, UNREADABLE_TRIES)).fetchall()
    if len(rows) < UNREADABLE_TRIES or any(r[0] not in UNREADABLE for r in rows):
        return False
    newest = rows[0][1]
    return newest is not None and (now or time.time()) - float(newest) < UNREADABLE_WAIT_H * 3600


def _target_first(conn, config, pending):
    """Embeddings put the 15 waiting ads closest to the target roles first; 5 places stay with the oldest
    so nothing waits forever. Without embeddings the old oldest-first order is kept."""
    items = {}
    for pid in pending:
        captured = _capture(conn, pid)
        if captured and captured[1]:
            items[pid] = (content_hash(captured[1].encode()), captured[1])
    try:
        profile_md = (profile_dir() / 'career_ops_profile.md').read_text(encoding='utf-8')
    except OSError:
        profile_md = ''
    scores = rank_by_target(conn, items, profile_md, config) if items else None
    if not scores:
        return pending[:20]
    oldest = pending[:5]
    closest = sorted((p for p in pending if p in scores and p not in oldest), key=lambda p: -scores[p])[:15]
    return closest + oldest


def _near_duplicates(conn, config, min_similarity=0.95):
    """The same vacancy listed twice under new ad text: embeddings find same-company look-alikes, Jev confirms
    "same role, level and location", and the newer copy (new or held, never READY) is archived as duplicate_of:<id>.
    Same-template ads for other stores or suburbs stay (Jev says different vacancy)."""
    import numpy as np
    extras = extras_settings(config)
    if not extras.get('enabled'):
        return 0
    conn.execute('CREATE TABLE IF NOT EXISTS near_dup_checked (posting_id INTEGER PRIMARY KEY, ad_hash TEXT NOT NULL)')
    live = {}
    for pid, stage in conn.execute('SELECT posting_id,stage FROM pipeline_state WHERE stage<>?', (str(Stage.ARCHIVED),)):
        captured = _capture(conn, pid)
        if captured and captured[1]:
            live[pid] = (stage, content_hash(captured[1].encode()), captured)
    checked = dict(conn.execute('SELECT posting_id,ad_hash FROM near_dup_checked'))
    open_stages = (str(Stage.INGESTED), str(Stage.DLQ))  # not READY: nothing drafted for the owner is touched
    new = [p for p, (stage, h, _) in live.items() if stage in open_stages and checked.get(p) != h]
    new = sorted(new, reverse=True)[:100]  # newest first; the rest are checked on later runs
    if not new:
        return 0
    got = vectors(conn, {f"ad:{h}": c[1] for _, h, c in live.values()}, config)
    if got is None:
        return 0
    ids = list(live)
    matrix = np.array([got[f"ad:{live[p][1]}"] for p in ids], dtype=float)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    row = {p: i for i, p in enumerate(ids)}
    company = {p: ''.join(ch for ch in (live[p][2][0]['company'] or '').lower() if ch.isalnum()) for p in ids}
    archived = 0
    for pid in sorted(new, reverse=True):
        if live[pid][0] not in open_stages:
            continue
        sims = matrix @ matrix[row[pid]]
        for other in sorted((q for q in ids if q < pid and sims[row[q]] >= min_similarity
                             and company[q] == company[pid] and live[q][0] != str(Stage.ARCHIVED)),
                            key=lambda q: -sims[row[q]])[:3]:
            a, b = live[pid][2], live[other][2]
            same = same_vacancy({**a[0], 'text': a[1]}, {**b[0], 'text': b[1]}, config)
            if same is not None and same >= float(extras['duplicate_at']):
                pipeline_store.move(conn, pid, 'near_duplicate', Stage(live[pid][0]), Stage.ARCHIVED,
                                    output={'duplicate_of': other, 'similarity': round(float(sims[row[other]]), 3),
                                            'jev_same_vacancy': round(same, 2)},
                                    reason=f'duplicate_of:{other}')
                live[pid] = (str(Stage.ARCHIVED),) + live[pid][1:]
                archived += 1
                break
        conn.execute('INSERT OR REPLACE INTO near_dup_checked(posting_id,ad_hash) VALUES (?,?)', (pid, live[pid][1]))
    conn.commit()
    return archived


def bundle_name(bundle) -> str:
    """The owner's name from the evidence snapshot's profile.yaml, only to mask it before anything goes to Jev."""
    try:
        import yaml
        raw = bundle.contents.get('profile.yaml', b'').decode('utf-8')
        return str(((yaml.safe_load(raw) or {}).get('candidate') or {}).get('name') or '')
    except Exception:
        return ''
