"""Current, independently gated evaluations are the only preference alternatives."""
from __future__ import annotations
from pipeline.agentic import service
from pipeline.agentic.contracts import AgenticEvaluation
from pipeline.agentic.runtime import validate_model_payload
from pipeline.agentic.persistence import latest_result
from jobwatch.preferences import PreferenceStore, PreferenceError, alternative_from_evaluation, context_hash


def preference_context(*, bundle, policy, cfg, structural):
    """Bind model readiness to every confirmed input for the server-bound person.

    Preferences such as location and writing style can change without changing
    primary evidence or the structural family projection. Like canonical run
    keys, use the complete approved payload so these changes invalidate old fits.
    This is read-only: historic owner responses and posteriors remain untouched.
    """
    from jobwatch import users
    from jobwatch.candidate import intake
    from jobwatch.candidate.contracts import digest
    approved = intake.current_version(users.current())
    return context_hash(bundle.bundle_hash, policy.model_dump(mode='json'), cfg,
                        structural.run_key, service.RUBRIC_VERSION, service.IMPLEMENTATION_VERSION,
                        digest(approved) if approved else None)


def pool(conn, config):
    cfg, policy = service._config(config), service.default_policy()
    dp = service.decision_policy_for(config)
    bundle = service.snapshot_evidence(service.profile_dir())
    service.verify_evidence_snapshot(bundle)
    inputs = service.load_inputs(bundle, cfg)
    structural = service.analyse_candidate(bundle, *inputs, policy)
    identity = preference_context(bundle=bundle, policy=policy, cfg=cfg, structural=structural)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'agentic_runs', 'agentic_packages', 'agentic_artifacts'} <= tables:
        return identity, []
    columns = {r[1] for r in conn.execute('PRAGMA table_info(agentic_runs)')}
    if 'generation' not in columns:
        return identity, []
    rows = conn.execute('SELECT DISTINCT posting_id FROM agentic_runs ORDER BY posting_id DESC').fetchall()
    alternatives = []
    for (posting_id,) in rows:
        captured = service._capture(conn, posting_id)
        if captured is None or captured[2] != 'full':
            continue
        result = latest_result(conn, posting_id)
        if not result or not result.get('evaluation'):
            continue
        key = service._run_key(posting_id, captured, bundle, policy, cfg, inputs, structural)
        if key.value != result['run_key']:
            continue
        try:
            ev = validate_model_payload(AgenticEvaluation, result['evaluation'])
            gate = service.gate_current(ev, posting=captured[0], ad_text=captured[1], decision_policy=dp,
                                        policy=policy, captured_complete=True, expected_run_key=key,
                                        evidence_bundle=bundle)
            alternatives.append(alternative_from_evaluation(ev, title=captured[0]['title'],
                company=captured[0]['company'], profile_hash=bundle.bundle_hash, gate=gate))
        except ValueError:
            continue
    return identity, alternatives


def create_next(conn, config):
    identity, alternatives = pool(conn, config)
    store = PreferenceStore(conn)
    existing = store.list_sets(identity)
    current = {a['posting_id']: a for a in alternatives}
    for item in existing:
        if not item['answered'] and all(current.get(a['posting_id']) == a for a in item['alternatives']):
            return item
    # Prefer unseen jobs, preserving disjoint training and held-out postings.
    used = {a['posting_id'] for s in existing for a in s['alternatives']}
    unseen = [a for a in alternatives if a['posting_id'] not in used]
    if len(unseen) >= 3:
        return store.create_set(unseen[:3], identity)
    raise PreferenceError('three_unseen_eligible_jobs_required')


def record_pick(conn, config, set_id, selected, request_id):
    identity, alternatives = pool(conn, config)
    store = PreferenceStore(conn)
    item = store.get_set(set_id)
    if item is None:
        raise PreferenceError('unknown_set')
    current = {a['posting_id']: a for a in alternatives}
    if item['context_hash'] != identity or not all(current.get(a['posting_id']) == a for a in item['alternatives']):
        raise PreferenceError('stale_set')
    return store.pick(set_id, selected, actor='owner', request_id=request_id)
