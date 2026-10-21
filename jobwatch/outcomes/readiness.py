"""Observed outcome inventory; no-response cases are right-censored, not failures."""
from .callback import posterior, SUCCESS


def outcome_readiness(conn):
    history = {}
    for row in conn.execute("SELECT application_id,to_status FROM application_events WHERE kind IN ('status','outcome_decided')"):
        history.setdefault(row[0], set()).add(row[1])
    applied = successes = failures = pending = 0
    for row in conn.execute('SELECT id,status,applied_at FROM applications'):
        ident, status, at = row
        reached = history.get(ident, set()) | {status}
        # A local rejected/archived draft is not evidence of submission.
        if not (at or 'applied' in reached or reached & set(SUCCESS)):
            continue
        applied += 1
        if reached & set(SUCCESS): successes += 1
        elif status == 'rejected': failures += 1
        else: pending += 1
    resolved = successes + failures
    return {'status': 'untrained' if not resolved else 'descriptive_only',
            'applied': applied, 'callbacks': successes, 'resolved_without_callback': failures,
            'pending': pending, 'resolved': resolved,
            'resolved_posterior': posterior(successes, resolved) if resolved else None,
            'prediction_available': False,
            'reason': 'no_observed_outcomes' if not resolved else 'heldout_calibration_required'}
