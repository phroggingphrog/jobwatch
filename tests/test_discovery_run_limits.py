import sqlite3

from pipeline.agentic import service
from pipeline.agentic.execution import Execution, use
from pipeline.agentic.runtime import RuntimeErrorSafe


def test_invocation_token_refusal_uses_effective_daily_or_run_reason(monkeypatch):
    seen = []
    real = service.agentic_batch_run
    monkeypatch.setattr(service, 'enabled', lambda config: True)
    monkeypatch.setattr(service, 'agentic_batch_run', lambda *args, **kwargs: seen.append(
        (use_current().token_ceiling, use_current().token_limit_reason)))

    def apply(scope, allowance, reason):
        with use(scope):
            real([], {}, None, token_allowance=allowance, token_allowance_reason=reason)

    def use_current():
        from pipeline.agentic.execution import current
        return current()

    apply(Execution('unlimited-run', token_ceiling=800), 300, 'run_budget')
    apply(Execution('finite-day', token_ceiling=800), 100, 'daily_budget')
    already_tighter = Execution('outer-run-cap', token_ceiling=100)
    apply(already_tighter, 300, 'daily_budget')

    assert seen == [(300, 'run_budget'), (100, 'daily_budget'), (100, 'run_budget')]
    assert service._runtime_stop_reason(RuntimeErrorSafe('invocation_budget_exhausted'),
                                        Execution('unlimited-run')) == 'run_budget'
    assert service._runtime_stop_reason(RuntimeErrorSafe('invocation_budget_exhausted'),
                                        Execution('finite-day', token_limit_reason='daily_budget')) == 'daily_budget'
    assert service._runtime_stop_reason(RuntimeErrorSafe('invocation_call_limit'),
                                        Execution('call-capped')) == 'run_call_limit'


def test_batch_budget_reason_defers_current_and_remaining_tail():
    summary = {'skipped': 0, 'deferred': []}
    pending = [41, 42, 43, 44]

    assert service._defer_budget_tail(summary, pending, 1, 'run_call_limit')

    assert summary['skipped'] == 3
    assert summary['deferred'] == [
        {'posting_id': 42, 'reason': 'run_call_limit', 'next_eligible_at': None},
        {'posting_id': 43, 'reason': 'run_call_limit', 'next_eligible_at': None},
        {'posting_id': 44, 'reason': 'run_call_limit', 'next_eligible_at': None},
    ]


def test_run_deferrals_do_not_count_as_assessments_but_keep_all_token_spend():
    conn = sqlite3.connect(':memory:')
    conn.executescript('''
        CREATE TABLE agentic_activity(event TEXT, at REAL, posting_id INTEGER, batch_id TEXT, reason TEXT);
        CREATE TABLE agentic_batches(batch_id TEXT, charged INTEGER);
        CREATE TABLE discovery_spend(at REAL, charged_tokens INTEGER);
    ''')
    reasons = ('daily_budget', 'run_budget', 'run_call_limit', 'snapshot_changed', 'evaluation_complete')
    for posting_id, reason in enumerate(reasons, start=1):
        batch_id = f'b{posting_id}'
        conn.execute('INSERT INTO agentic_activity VALUES(?,?,?,?,?)',
                     ('finished', 10, posting_id, batch_id, reason))
        conn.execute('INSERT INTO agentic_batches VALUES(?,?)', (batch_id, posting_id * 100))
    conn.execute('INSERT INTO discovery_spend VALUES(?,?)', (10, 75))

    assert service._spent_today(conn, 0) == (1, 1575)
