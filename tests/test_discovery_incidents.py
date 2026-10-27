"""Synthetic incidents do not contact a notification channel or run a model."""
import sqlite3
import time

import pytest

import subprocess

from jobwatch import notify
from jobwatch.notifier import legacy
from pipeline.agentic import incidents
from tests.notify_support import FakeChannel, use_fake_channel

WINDOW = incidents.DIGEST_SECONDS


@pytest.fixture
def conn():
    with sqlite3.connect(':memory:') as value:
        yield value


def live_transport(monkeypatch, sender):
    monkeypatch.setattr(notify, 'is_live', lambda _: True)
    use_fake_channel(monkeypatch, sender)


def test_first_failure_is_visible_paused_and_deduplicated(conn, monkeypatch):
    use_fake_channel(monkeypatch, lambda _: pytest.fail('test database must not send'))
    one = incidents.report(conn, posting_id=42, run_id='attempt-1', reason='deadline_exceeded', phase='evaluation')
    two = incidents.report(conn, posting_id=42, run_id='attempt-1', reason='service_timeout', phase='shutdown')
    assert one['incident_id'] == two['incident_id']
    assert one['state'] == 'paused' and incidents.is_paused(conn, 42)
    assert not incidents.is_paused(conn, 43)
    assert len(incidents.list_incidents(conn)) == 1
    messages = conn.execute('SELECT text FROM chat_messages WHERE ' + notify.CHAT_VISIBLE).fetchall()
    assert len(messages) == 1 and 'Explicit retry' in messages[0][0]
    assert notify.unread(conn) == 1
    assert one['notification_state'] == 'pending'


@pytest.mark.parametrize('reason', ['snapshot_changed', 'insufficient_evidence', 'posting_unavailable',
                                  'posting_closed', 'busy', 'daily_budget', 'batch_deadline', 'budget_exhausted',
                                  'invocation_budget_exhausted', 'batch_paused', 'concurrency_limit', 'job_already_active'])
def test_normal_deferrals_and_decisions_are_not_failures(conn, reason):
    assert incidents.report(conn, posting_id=42, run_id='attempt-1', reason=reason) is None
    assert incidents.list_incidents(conn) == [] and not incidents.is_paused(conn, 42)
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='agentic_incidents'").fetchone()


@pytest.mark.parametrize('reason', ['token_limit', 'turn_limit', 'failed_attempt_limit', 'missing_terminal',
                                  'tool_failed', 'invalid_model_payload', 'model_deadline',
                                  'model_rate_limited', 'model_transient', 'invalid_tool_arguments_json'])
def test_stopped_job_limits_and_actual_runtime_failures_pause_first_attempt(conn, reason):
    row = incidents.report(conn, posting_id=42, run_id='attempt-1', reason=reason, phase='assessment')
    assert row['reason'] == reason and row['state'] == 'paused'
    assert incidents.is_paused(conn, 42)
    assert len(incidents.list_incidents(conn)) == 1 and notify.unread(conn) == 1


def test_actual_job_token_limit_is_distinct_from_remaining_daily_allowance(conn):
    from pipeline.agentic import execution
    from pipeline.agentic.runtime import BatchBudget, JobBudget, RuntimeErrorSafe
    job = JobBudget('a' * 64, BatchBudget('batch', token_ceiling=1000), token_ceiling=50)
    with execution.use(execution.Execution('attempt', token_ceiling=1000)):
        with pytest.raises(RuntimeErrorSafe) as job_error:
            job.reserve('evaluator', 60, 1)
    assert job_error.value.code == 'token_limit'
    assert incidents.report(conn, posting_id=42, run_id='job-limit', reason=job_error.value.code)['state'] == 'paused'
    with execution.use(execution.Execution('daily-limited', token_ceiling=10)):
        with pytest.raises(RuntimeErrorSafe) as daily_error:
            job.reserve('evaluator', 20, 1)
    assert daily_error.value.code == 'invocation_budget_exhausted'
    assert incidents.report(conn, posting_id=43, run_id='daily-limit', reason=daily_error.value.code) is None
    assert not incidents.is_paused(conn, 43) and job.batch.charged_tokens == 0


@pytest.mark.parametrize('reason', ['invalid_configuration', 'credential_unavailable'])
def test_run_configuration_failures_are_reported_without_pausing_unrelated_jobs(conn, reason):
    row = incidents.report(conn, run_id='run-1', reason=reason, phase='configuration')
    assert row['posting_id'] is None and row['reason'] == reason
    assert not incidents.is_paused(conn, 42) and notify.unread(conn) == 1


def test_delivery_retry_is_separate_and_does_not_duplicate_messages(conn, monkeypatch):
    sent = []
    live_transport(monkeypatch, lambda lines: sent.extend(lines) or False)
    incidents.report(conn, posting_id=42, run_id='attempt-1', reason='model_unavailable', now=100)
    assert incidents.flush_notifications(conn, now=100 + WINDOW - 1) == 0 and sent == []
    assert incidents.flush_notifications(conn, now=100 + WINDOW) == 0
    one = incidents.list_incidents(conn)[0]
    assert one['notification_state'] == 'failed' and one['notification_attempts'] == 1
    assert one['notification_error'] == 'delivery_failed'
    assert incidents.flush_notifications(conn, now=100 + WINDOW + 20) == 0 and len(sent) == 1
    FakeChannel.sender = staticmethod(lambda lines: sent.extend(lines) or True)
    assert incidents.flush_notifications(conn, now=100 + WINDOW + 60) == 1
    after = incidents.list_incidents(conn)[0]
    assert after['notification_state'] == 'delivered' and after['notification_attempts'] == 2
    assert after['state'] == 'paused' and incidents.is_paused(conn, 42)
    assert incidents.flush_notifications(conn, force=True, now=1000) == 0
    assert len(sent) == 2 and sent[0] == sent[1]
    assert conn.execute('SELECT COUNT(*) FROM chat_messages').fetchone()[0] == 1


def test_no_channel_is_reported_without_send(conn, monkeypatch):
    monkeypatch.setattr(notify, 'is_live', lambda _: True)
    monkeypatch.delenv(legacy.SSH_ENV, raising=False)
    monkeypatch.delenv(legacy.FILE_ENV, raising=False)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('no channel: nothing to run'))
    incidents.report(conn, posting_id=42, run_id='attempt-1', reason='execution_failed', now=100)
    incidents.flush_notifications(conn, now=100 + WINDOW)
    row = incidents.list_incidents(conn)[0]
    assert row['notification_state'] == 'no_channel' and row['notification_error'] is None


def test_other_account_never_uses_owners_install_wide_route(conn, monkeypatch):
    from jobwatch import users
    monkeypatch.setattr(notify, 'is_live', lambda _: True)
    monkeypatch.setenv(legacy.SSH_ENV, 'someone@example.invalid')
    monkeypatch.setenv(legacy.FILE_ENV, '/tmp/x')
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('another account must not use the owner route'))
    with users.use('other-person'):
        incidents.report(conn, posting_id=42, run_id='other-attempt', reason='execution_failed', now=100)
        incidents.flush_notifications(conn, now=100 + WINDOW)
        row = incidents.list_incidents(conn)[0]
        assert row['notification_state'] == 'no_channel'
        assert incidents.is_paused(conn, 42) and notify.unread(conn) == 1


def test_rows_stored_before_generic_wording_read_as_generic(conn):
    row = incidents.report(conn, posting_id=42, run_id='attempt-1', reason='execution_failed', now=100)
    ident = row['incident_id']
    for stored, error, expect in [('handed_off', None, ('delivered', None)),
                                  ('failed', 'hermes_not_configured', ('no_channel', None)),
                                  ('failed', 'hermes_handoff_failed', ('failed', 'delivery_failed')),
                                  ('sending', None, ('pending', None))]:
        conn.execute('UPDATE agentic_incidents SET notification_state=?,notification_error=? WHERE incident_id=?',
                     (stored, error, ident))
        got = incidents.list_incidents(conn)[0]
        assert (got['notification_state'], got['notification_error']) == expect


def test_notification_sender_claim_prevents_concurrent_duplicate(conn, monkeypatch):
    row = incidents.report(conn, posting_id=42, run_id='attempt-1', reason='execution_failed', now=100)
    conn.execute("UPDATE agentic_incidents SET notification_state='sending',notification_lease_until=300 WHERE incident_id=?",
                 (row['incident_id'],))
    conn.commit()
    live_transport(monkeypatch, lambda _: pytest.fail('another sender owns the lease'))
    assert incidents.flush_notifications(conn, force=True, now=200) == 0


def test_explicit_release_is_scoped_single_use_and_preserves_incident(conn):
    one = incidents.report(conn, posting_id=42, run_id='attempt-1', reason='deadline_exceeded')
    for pid, run in [(43, 'attempt-1'), (42, 'other-attempt')]:
        with pytest.raises(ValueError, match='incident_not_found'):
            incidents.release(conn, one['incident_id'], pid, expected_run_id=run)
    row = incidents.release(conn, one['incident_id'], 42, expected_run_id='attempt-1')
    assert row['state'] == 'released' and not incidents.is_paused(conn, 42)
    assert incidents.list_incidents(conn) == []
    assert len(incidents.list_incidents(conn, include_resolved=True)) == 1
    with pytest.raises(ValueError, match='incident_already_released'):
        incidents.release(conn, one['incident_id'], 42)
    later = incidents.report(conn, posting_id=42, run_id='attempt-2', reason='deadline_exceeded')
    assert later['incident_id'] != one['incident_id'] and incidents.is_paused(conn, 42)


def test_incident_persists_across_restart_and_person_databases_are_isolated(tmp_path):
    path = tmp_path / 'person-a.sqlite'
    with sqlite3.connect(path) as first:
        one = incidents.report(first, posting_id=42, run_id='attempt-1', reason='execution_failed')
    with sqlite3.connect(path) as restarted, sqlite3.connect(tmp_path / 'person-b.sqlite') as other:
        assert incidents.is_paused(restarted, 42)
        assert incidents.list_incidents(restarted)[0]['incident_id'] == one['incident_id']
        assert not incidents.is_paused(other, 42)
        with pytest.raises(ValueError, match='incident_not_found'):
            incidents.release(other, one['incident_id'], 42)


def test_service_timeout_reconciles_last_phase_once_and_only_matching_unit(conn):
    incidents.begin_run(conn, 'run-1', unit='reader')
    incidents.mark_phase(conn, 'run-1', 'liveness', posting_id=42, completed=True)
    incidents.mark_phase(conn, 'run-1', 'evaluation', posting_id=42)
    incidents.begin_run(conn, 'run-2', unit='collector')
    timed_out = incidents.reconcile_service_exit(conn, unit='reader', reason='service_timeout')
    assert len(timed_out) == 1
    assert timed_out[0]['posting_id'] == 42 and timed_out[0]['phase'] == 'evaluation'
    assert timed_out[0]['last_successful_phase'] == 'liveness'
    assert incidents.is_paused(conn, 42)
    assert incidents.reconcile_service_exit(conn, unit='reader') == []
    assert conn.execute("SELECT state FROM agentic_invocations WHERE run_id='run-2'").fetchone()[0] == 'running'
    incidents.end_run(conn, 'run-2')
    assert incidents.reconcile_service_exit(conn, unit='collector') == []


def test_unknown_phase_and_exception_text_are_never_written(conn):
    row = incidents.report(conn, posting_id=42, run_id='attempt-1', reason='execution_failed', phase='PRIVATE contact@example.test')
    assert row['phase'] == 'unknown'
    assert 'PRIVATE' not in conn.execute('SELECT text FROM chat_messages').fetchone()[0]
    assert incidents.report(conn, posting_id=42, reason='PRIVATE exception text') is None


def test_read_only_status_does_not_create_schema(tmp_path):
    path = tmp_path / 'empty.sqlite'
    sqlite3.connect(path).close()
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as read:
        assert incidents.list_incidents(read) == []
        assert not incidents.is_paused(read, 42)


def test_twenty_one_incidents_in_one_window_send_one_digest_then_next_window_one_more(conn, monkeypatch):
    sent = []
    live_transport(monkeypatch, lambda lines: sent.extend(lines) or True)
    for pid in range(1, 22):
        incidents.report(conn, posting_id=pid, run_id=f'a-{pid}', reason='deadline_exceeded' if pid <= 12 else 'turn_limit',
                         now=100 + pid)
    incidents.report(conn, posting_id=1, run_id='a-1-again', reason='deadline_exceeded', now=200)
    assert sent == [] and incidents.flush_notifications(conn, now=100 + WINDOW) == 0
    assert incidents.flush_notifications(conn, now=101 + WINDOW) == 1
    assert len(sent) == 1 and sent[0].count('\n') == 0
    assert 'deadline_exceeded x12' in sent[0] and 'turn_limit x9' in sent[0]
    assert '#1, #2, #3, #4, #5, #6, #7, #8, #9, #10 +2 more' in sent[0] and '#11' not in sent[0].split(';')[0]
    assert sent[0].count('Explicit retry') == 1 and '21 stopped' in sent[0]
    assert incidents.flush_notifications(conn, now=102 + WINDOW) == 0 and len(sent) == 1
    incidents.report(conn, posting_id=30, run_id='b-30', reason='token_limit', now=100 + WINDOW + 10)
    incidents.report(conn, posting_id=31, run_id='b-31', reason='token_limit', now=100 + WINDOW + 20)
    assert incidents.flush_notifications(conn, now=100 + 2 * WINDOW + 9) == 0
    assert incidents.flush_notifications(conn, now=100 + 2 * WINDOW + 10) == 1
    assert len(sent) == 2 and 'token_limit x2 (jobs #30, #31)' in sent[1] and 'deadline_exceeded' not in sent[1]
    assert incidents.flush_notifications(conn, now=100 + 4 * WINDOW) == 0 and len(sent) == 2
    assert all(i['notification_state'] == 'delivered' for i in incidents.list_incidents(conn))


def test_same_reason_for_same_job_is_listed_once_in_a_digest(conn, monkeypatch):
    sent = []
    live_transport(monkeypatch, lambda lines: sent.extend(lines) or True)
    for run in ('x', 'y'):
        incidents.report(conn, posting_id=7, run_id=run, reason='turn_limit', now=100)
        incidents.release(conn, incidents.list_incidents(conn)[0]['incident_id'], 7)
    incidents.report(conn, run_id='run-1', reason='invalid_configuration', now=100)
    assert incidents.flush_notifications(conn, now=100 + WINDOW) == 1
    assert 'turn_limit x1 (jobs #7)' in sent[0] and 'invalid_configuration x1 (1 discovery run)' in sent[0]
    assert 'Check discovery status' in sent[0]


def test_failed_digest_handoff_keeps_everything_pending_and_delivers_once(conn, monkeypatch):
    sent = []
    live_transport(monkeypatch, lambda lines: False)
    for pid in (1, 2, 3):
        incidents.report(conn, posting_id=pid, run_id=f'a-{pid}', reason='execution_failed', now=100)
    assert incidents.flush_notifications(conn, now=100 + WINDOW) == 0
    assert all(i['notification_state'] == 'failed' and i['handed_off_at'] is None for i in incidents.list_incidents(conn))
    live_transport(monkeypatch, lambda lines: sent.extend(lines) or True)
    assert incidents.flush_notifications(conn, now=100 + WINDOW + 30) == 0 and sent == []
    incidents.report(conn, posting_id=4, run_id='late', reason='execution_failed', now=100 + WINDOW + 40)
    assert incidents.flush_notifications(conn, now=100 + WINDOW + 61) == 1
    assert len(sent) == 1 and 'execution_failed x4 (jobs #1, #2, #3, #4)' in sent[0]
    assert incidents.flush_notifications(conn, now=100 + 3 * WINDOW) == 0 and len(sent) == 1


def test_last_successful_phase_is_not_inferred_from_starting_work(conn):
    incidents.begin_run(conn, 'new', unit='reader')
    incidents.mark_phase(conn, 'new', 'assessment', posting_id=42)
    row = incidents.report(conn, posting_id=42, run_id='new', reason='deadline_exceeded', phase='assessment')
    assert row['last_successful_phase'] is None


def test_successful_phase_does_not_leak_from_previous_job_in_the_run(conn):
    incidents.begin_run(conn, 'batch', unit='reader')
    incidents.mark_phase(conn, 'batch', 'evaluation', posting_id=41, completed=True)
    incidents.mark_phase(conn, 'batch', 'liveness', posting_id=42)
    row = incidents.report(conn, posting_id=42, run_id='batch', reason='deadline_exceeded', phase='liveness')
    assert row['last_successful_phase'] is None


def test_additive_migration_preserves_old_rows(conn):
    row = incidents.report(conn, posting_id=42, run_id='old', reason='execution_failed')
    conn.execute('ALTER TABLE agentic_incidents DROP COLUMN last_successful_phase')
    conn.execute('ALTER TABLE agentic_invocations DROP COLUMN last_successful_phase')
    incidents.ensure(conn)
    saved = incidents.list_incidents(conn)[0]
    assert saved['incident_id'] == row['incident_id'] and saved['last_successful_phase'] is None


def activity_rows(conn, rows):
    conn.execute('CREATE TABLE IF NOT EXISTS agentic_activity(id INTEGER PRIMARY KEY,posting_id INTEGER,run_key TEXT,'
                 'invocation_id TEXT,event TEXT,reason TEXT,at REAL)')
    conn.executemany('INSERT INTO agentic_activity(posting_id,run_key,invocation_id,event,reason,at) VALUES(?,?,?,?,?,?)', rows)
    conn.commit()


def test_reconcile_old_failure_pauses_once_and_later_normal_outcome_wins(conn):
    activity_rows(conn, [(42, 'key-42', 'attempt-42', 'finished', 'deadline_exceeded', 100),
                         (43, 'key-43', 'attempt-43', 'finished', 'execution_failed', 100),
                         (43, 'key-43', 'later-43', 'finished', 'evaluated', 120),
                         (44, 'key-44', 'attempt-44', 'finished', 'posting_unavailable', 100),
                         (45, 'key-45', 'attempt-45', 'started', None, 100)])
    rows = incidents.reconcile_known_failures(conn)
    assert len(rows) == 1 and rows[0]['posting_id'] == 42
    assert rows[0]['phase'] is None and rows[0]['last_successful_phase'] is None
    assert incidents.is_paused(conn, 42) and not incidents.is_paused(conn, 43)
    assert incidents.reconcile_known_failures(conn) == []
    assert conn.execute('SELECT COUNT(*) FROM chat_messages').fetchone()[0] == 1
    incidents.release(conn, rows[0]['incident_id'], 42)
    assert incidents.reconcile_known_failures(conn) == [] and not incidents.is_paused(conn, 42)


def test_reconcile_does_not_repause_a_reported_released_failure(conn):
    activity_rows(conn, [(42, 'key-42', 'attempt-42', 'finished', 'deadline_exceeded', 100)])
    row = incidents.report(conn, posting_id=42, run_id='reader-trace', reason='deadline_exceeded', now=101)
    incidents.release(conn, row['incident_id'], 42)
    assert incidents.reconcile_known_failures(conn) == []
    assert not incidents.is_paused(conn, 42)


def test_reconcile_without_activity_is_read_only_and_handoffs_are_bounded(conn, monkeypatch):
    assert incidents.reconcile_known_failures(conn) == []
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='agentic_incidents'").fetchone()
    activity_rows(conn, [(pid, f'key-{pid}', f'attempt-{pid}', 'finished', 'deadline_exceeded', 100)
                         for pid in (1, 2, 3)])
    sent = []
    live_transport(monkeypatch, lambda lines: sent.extend(lines) or True)
    rows = incidents.reconcile_known_failures(conn)
    assert len(rows) == 3 and sent == []
    assert incidents.flush_notifications(conn, now=time.time() + WINDOW) == 1 and len(sent) == 1
    assert len(incidents.list_incidents(conn)) == 3
    assert all(i['notification_state'] == 'delivered' for i in incidents.list_incidents(conn))
