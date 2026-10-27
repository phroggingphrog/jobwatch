"""Synthetic incidents do not contact Hermes or run a model."""
import sqlite3

import pytest

from jobwatch import notify
from pipeline.agentic import incidents


@pytest.fixture
def conn():
    with sqlite3.connect(':memory:') as value:
        yield value


def live_transport(monkeypatch, sender):
    monkeypatch.setattr(notify, 'is_live', lambda _: True)
    monkeypatch.setattr(notify, '_setting', lambda _: 'synthetic-config')
    monkeypatch.setattr(notify, '_send', sender)


def test_first_failure_is_visible_paused_and_deduplicated(conn, monkeypatch):
    monkeypatch.setattr(notify, '_send', lambda _: pytest.fail('test database must not send'))
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
                                  'posting_closed', 'busy', 'daily_budget', 'batch_deadline', 'budget_exhausted'])
def test_normal_deferrals_and_decisions_are_not_failures(conn, reason):
    assert incidents.report(conn, posting_id=42, run_id='attempt-1', reason=reason) is None
    assert incidents.list_incidents(conn) == [] and not incidents.is_paused(conn, 42)
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='agentic_incidents'").fetchone()


def test_delivery_retry_is_separate_and_does_not_duplicate_messages(conn, monkeypatch):
    sent = []
    live_transport(monkeypatch, lambda lines: sent.extend(lines) or False)
    one = incidents.report(conn, posting_id=42, run_id='attempt-1', reason='model_unavailable', now=100)
    assert one['notification_state'] == 'failed' and one['notification_attempts'] == 1
    assert one['notification_error'] == 'hermes_handoff_failed'
    assert incidents.flush_notifications(conn, now=120) == 0 and len(sent) == 1
    monkeypatch.setattr(notify, '_send', lambda lines: sent.extend(lines) or True)
    assert incidents.flush_notifications(conn, now=160) == 1
    after = incidents.list_incidents(conn)[0]
    assert after['notification_state'] == 'handed_off' and after['notification_attempts'] == 2
    assert after['state'] == 'paused' and incidents.is_paused(conn, 42)
    assert incidents.flush_notifications(conn, force=True, now=1000) == 0
    assert len(sent) == 2 and sent[0] == sent[1]
    assert conn.execute('SELECT COUNT(*) FROM chat_messages').fetchone()[0] == 1


def test_missing_hermes_configuration_is_reported_without_send(conn, monkeypatch):
    monkeypatch.setattr(notify, 'is_live', lambda _: True)
    monkeypatch.setattr(notify, '_setting', lambda _: '')
    monkeypatch.setattr(notify, '_send', lambda _: pytest.fail('not configured'))
    row = incidents.report(conn, posting_id=42, run_id='attempt-1', reason='execution_failed')
    assert row['notification_state'] == 'failed' and row['notification_error'] == 'hermes_not_configured'


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
    incidents.mark_phase(conn, 'run-1', 'evaluation', posting_id=42)
    incidents.begin_run(conn, 'run-2', unit='collector')
    timed_out = incidents.reconcile_service_exit(conn, unit='reader', reason='service_timeout')
    assert len(timed_out) == 1
    assert timed_out[0]['posting_id'] == 42 and timed_out[0]['phase'] == 'evaluation'
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
