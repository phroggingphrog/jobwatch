"""Observed outcome inventory; no-response cases are right-censored, not failures."""
from .callback import posterior, observed_outcome


def outcome_readiness(conn):
    history = {}
    for row in conn.execute("SELECT application_id,to_status FROM application_events WHERE kind IN ('status','outcome_decided')"):
        history.setdefault(row[0], set()).add(row[1])
    applied = successes = failures = pending = 0
    for row in conn.execute('SELECT id,status,applied_at FROM applications'):
        ident, status, at = row
        outcome = observed_outcome(status, at, history.get(ident, set()))
        if outcome is None:
            continue
        applied += 1
        if outcome == 'callback': successes += 1
        elif outcome == 'no_callback': failures += 1
        else: pending += 1
    resolved = successes + failures
    return {'status': 'untrained' if not resolved else 'descriptive_only',
            'applied': applied, 'callbacks': successes, 'resolved_without_callback': failures,
            'pending': pending, 'resolved': resolved,
            'resolved_posterior': posterior(successes, resolved) if resolved else None,
            'prediction_available': False,
            'reason': 'no_observed_outcomes' if not resolved else 'heldout_calibration_required'}


def response_time_readiness(conn):
    """Inventory timed first responses; silence remains censored, never negative."""
    from datetime import datetime, timezone
    result=dict(status='insufficient_history',responses=0,censored=0,minimum_responses=30,
        model='none',selection_bias='Applications are chosen by the owner; this describes applied jobs only.',
        reason='insufficient_history')
    def timestamp(value):
        try:
            parsed=datetime.fromisoformat(str(value).replace('Z','+00:00'))
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
        except (ValueError,TypeError):
            return None
    tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'applications','application_events'}<=tables:
        return result
    columns={r[1] for r in conn.execute('PRAGMA table_info(application_events)')}
    if not {'at','application_id','kind','to_status'}<=columns:
        return result
    for ident,at in conn.execute('SELECT id,applied_at FROM applications WHERE applied_at IS NOT NULL'):
        applied=timestamp(at)
        if applied is None:
            continue
        replies=[timestamp(r[0]) for r in conn.execute("SELECT at FROM application_events WHERE application_id=? "
            "AND kind IN ('status','outcome_decided') AND to_status IN ('assessment','interview','offer','rejected')",(ident,))]
        if any(reply is not None and reply>=applied for reply in replies):
            result['responses']+=1
        else:
            result['censored']+=1
    if result['responses']>=result['minimum_responses']:
        result.update(status='investigate',reason='offline_survival_analysis_only')
    return result
