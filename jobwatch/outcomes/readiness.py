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
