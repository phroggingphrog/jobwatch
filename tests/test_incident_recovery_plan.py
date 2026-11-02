"""Recovery proposals must not release incidents or create missing tables."""
import json
import sqlite3
import subprocess
import sys

from pipeline.agentic import incidents
from pipeline.agentic.recovery import plan


def test_cli_reads_existing_file_without_writing(tmp_path):
    database = tmp_path / 'incidents.db'
    with sqlite3.connect(database) as conn:
        incidents.report(conn, run_id='synthetic', reason='turn_limit', notify_immediately=False)
    before = database.read_bytes()
    result = subprocess.run([sys.executable, '-m', 'pipeline.agentic.recovery', str(database)],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)['proposals'][0]['action'] == 'retain_pause'
    assert database.read_bytes() == before


def test_cli_rejects_missing_database_without_creating_it(tmp_path):
    database = tmp_path / 'absent.db'
    result = subprocess.run([sys.executable, '-m', 'pipeline.agentic.recovery', str(database)],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert not database.exists()


def test_empty_database_stays_empty():
    conn = sqlite3.connect(':memory:')
    conn.execute('PRAGMA query_only=ON')
    assert plan(conn) == []
    assert conn.execute('SELECT name FROM sqlite_master').fetchall() == []


def test_plan_preserves_pauses_and_excludes_released_incidents():
    conn = sqlite3.connect(':memory:')
    for number, reason in enumerate(['execution_failed', 'deadline_exceeded', 'turn_limit',
                                     'token_limit', 'invalid_evaluation', 'invalid_model_payload']):
        incidents.report(conn, posting_id=number + 1, run_id=f'run-{number}',
                         reason=reason, notify_immediately=False)
    released = incidents.report(conn, posting_id=10, run_id='released', reason='turn_limit',
                                notify_immediately=False)
    incidents.release(conn, released['incident_id'], 10)
    before = conn.total_changes
    conn.execute('PRAGMA query_only=ON')
    proposals = plan(conn)
    assert len(proposals) == 6
    assert conn.total_changes == before
    assert {row['state'] for row in proposals} == {'paused'}
    assert all(row['action'] == 'retain_pause' and row['recovery_requires'] for row in proposals)
    assert all(row['evidence_status'] == 'not_verified' for row in proposals)
    assert {row['reason'] for row in proposals} == {
        'execution_failed', 'deadline_exceeded', 'turn_limit', 'token_limit',
        'invalid_evaluation', 'invalid_model_payload'}


def test_newer_success_does_not_authorize_release():
    conn = sqlite3.connect(':memory:')
    incidents.report(conn, run_id='old', reason='execution_failed', phase='collection',
                     notify_immediately=False)
    incidents.begin_run(conn, 'new')
    incidents.mark_phase(conn, 'new', 'collection')
    incidents.end_run(conn, 'new')
    conn.execute('PRAGMA query_only=ON')
    assert plan(conn)[0]['action'] == 'retain_pause'
