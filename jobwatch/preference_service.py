"""Current, independently gated evaluations are the only preference alternatives."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from pipeline.agentic import service
from jobwatch.candidate import approved as approved_reader
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
    return context_hash(users.current(), bundle.bundle_hash, policy.model_dump(mode='json'), cfg,
                        structural.run_key, service.RUBRIC_VERSION, service.IMPLEMENTATION_VERSION,
                        digest(approved) if approved else None)


@dataclass(frozen=True)
class CurrentRun:
    posting_id: int
    captured: tuple
    posting: dict
    key: object
    result: dict
    evaluation: AgenticEvaluation
    decision: object
    approved: dict | None = None


def current_runs(conn, config):
    """Read current stored assessments; never fetch, evaluate or create state."""
    from jobwatch import users
    from jobwatch.candidate import intake
    from jobwatch.candidate.contracts import digest
    from jobwatch.candidate.policy import policy_for
    approved = intake.current_version(users.current())
    approved_hash = digest(approved) if approved else None
    cfg, policy = service._config(config), service.default_policy()
    dp = policy_for(users.current(), approved=approved) if approved else None
    bundle = approved_reader.evidence(users.current())
    inputs = service.load_inputs(bundle, cfg)
    structural = service.analyse_candidate(bundle, *inputs, policy)
    identity = preference_context(bundle=bundle, policy=policy, cfg=cfg, structural=structural)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    runs = []
    columns = {r[1] for r in conn.execute('PRAGMA table_info(agentic_runs)')} if 'agentic_runs' in tables else set()
    if {'agentic_runs', 'agentic_packages', 'agentic_artifacts'} <= tables and 'generation' in columns:
        rows = conn.execute('SELECT DISTINCT posting_id FROM agentic_runs ORDER BY posting_id DESC').fetchall()
        for (posting_id,) in rows:
            posting = service._posting(conn, posting_id)
            if not posting or posting.get('closed_at'):
                continue
            captured = service._capture(conn, posting_id)
            if captured is None or captured[2] != 'full':
                continue
            result = latest_result(conn, posting_id)
            if not result or not result.get('evaluation') or result.get('reason') == 'artifact_invalid':
                continue
            if not service.observation_current(service.latest_observation(conn,posting_id),
                    posting_id=posting_id,url=captured[0]['url'],ad_hash=sha256(captured[1].encode()).hexdigest()):
                continue
            key = service._run_key(posting_id, captured, bundle, policy, cfg, inputs, structural, conn=conn)
            if key.value != result['run_key']:
                continue
            try:
                ev = validate_model_payload(AgenticEvaluation, result['evaluation'])
                gate = service.gate_current(ev, posting=captured[0], ad_text=captured[1], decision_policy=dp,
                    policy=policy, captured_complete=True, expected_run_key=key, evidence_bundle=bundle)
                runs.append(CurrentRun(posting_id, captured, posting, key, result, ev, gate, approved))
            except ValueError:
                continue
    latest = intake.current_version(users.current())
    if (digest(latest) if latest else None) != approved_hash:
        raise PreferenceError('snapshot_changed')
    service.verify_evidence_snapshot(bundle)
    return identity, bundle, policy, runs


def pool(conn, config, *, statuses=('eligible',)):
    from jobwatch.candidate.contracts import digest
    from jobwatch.candidate.policy import build_policy
    identity, bundle, policy, runs = current_runs(conn, config)
    alternatives = []
    for row in runs:
        status = 'eligible' if (row.decision.route, row.decision.reason) == ('draft', 'eligible') else (
            'held' if (row.decision.route, row.decision.reason) == ('hold', 'insufficient_evidence') else None)
        if status not in statuses:
            continue
        try:
            alternative = alternative_from_evaluation(row.evaluation, title=row.posting['title'],
                company=row.posting['company'], profile_hash=bundle.bundle_hash, gate=row.decision,
                posting=row.posting, ad_text=row.captured[1], approved=row.approved)
            alternative['approved_hash'] = digest(row.approved) if row.approved else None
            alternative['policy_hash'] = build_policy(row.approved).policy_hash if row.approved else None
            alternatives.append(alternative)
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
