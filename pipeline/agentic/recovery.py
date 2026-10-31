"""Read-only recovery proposals. This module cannot release or replay incidents.

Run with ``python -m pipeline.agentic.recovery /absolute/path/to/jobwatch.db``.
The output contains fixed codes and numeric IDs, not candidate or posting text.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3


CRITERIA = {
    'execution_failed': ['match_invocation_to_failed_run', 'verify_exception_cause',
                         'verify_corrected_source_and_synthetic_regression'],
    'deadline_exceeded': ['inspect_checkpoint_and_shared_deadline',
                          'verify_bounded_resume_without_deadline_renewal'],
    'turn_limit': ['inspect_role_turns_and_repeated_operations',
                   'verify_terminal_progress_with_existing_turn_limit'],
    'token_limit': ['inspect_job_batch_and_reservation_accounting',
                    'verify_progress_with_existing_token_limits'],
    'invalid_evaluation': ['identify_failed_validation_without_private_text',
                           'verify_synthetic_schema_and_citation_regression'],
    'invalid_model_payload': ['identify_payload_shape_and_protocol_failure',
                              'verify_synthetic_protocol_and_bounded_correction'],
}


def plan(conn: sqlite3.Connection) -> list[dict]:
    """Return requirements, not a verdict that a cause has been corrected."""
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                          "AND name='agentic_incidents'").fetchone()
    if not exists:
        return []
    rows = conn.execute("SELECT incident_id,posting_id,reason,state FROM agentic_incidents "
                        "WHERE state='paused' ORDER BY created_at,incident_id").fetchall()
    return [{
        'incident_id': ident, 'posting_id': posting, 'reason': reason,
        'state': state, 'action': 'retain_pause', 'evidence_status': 'not_verified',
        'recovery_requires': CRITERIA.get(reason, ['verify_specific_cause_and_synthetic_regression'])
                             + ['explicit_recovery_authorization'],
    } for ident, posting, reason, state in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    args = parser.parse_args()
    path = args.database.expanduser().resolve(strict=True)
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as conn:
        conn.execute('PRAGMA query_only=ON')
        print(json.dumps({'dry_run': True, 'proposals': plan(conn)}, indent=2))


if __name__ == '__main__':
    main()
