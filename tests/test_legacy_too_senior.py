"""Offline correction safety tests; never open the real database."""
import json
import sqlite3

import pytest

from scripts import legacy_too_senior as fix
from jobwatch import db as dbm
from jobwatch.web import queries as q
from pipeline import store
from tests.web.test_ai import seed, review, staged


def setup_db(tmp_path, count=4):
    path = tmp_path / 'copy.sqlite'
    conn = dbm.connect(path)
    store.ensure(conn)
    for n in range(count):
        pid = seed(conn, n + 1, 'Synthetic role')
        review(conn, pid, verdict='hide', hide_reason='not_target',
               report_json='{}', model_json='{"not_target_kind":"too_senior"}')
    return path, conn


def snapshot(conn):
    return list(conn.execute('SELECT * FROM ad_reviews ORDER BY posting_id'))


def test_roundtrip_and_only_column_changed(tmp_path):
    path, conn = setup_db(tmp_path)
    before = [dict(r) for r in snapshot(conn)]
    backup = tmp_path / 'backup.json'
    assert fix.preflight(conn)['count'] == 4
    fix.apply(conn, backup, path)
    after = [dict(r) for r in snapshot(conn)]
    assert [{**r, 'hide_reason': 'not_target'} for r in after] == before
    assert backup.stat().st_mode & 0o777 == 0o600
    assert all(r['ai']['hide_reason'] == 'too_senior' for r in q.load_rows(conn, 'all'))
    fix.rollback(conn, backup, path)
    assert [dict(r) for r in snapshot(conn)] == before
    with pytest.raises(fix.GuardError):
        fix.rollback(conn, backup, path)


@pytest.mark.parametrize('count', [0, 3, 5])
def test_count_guard(tmp_path, count):
    path, conn = setup_db(tmp_path, count)
    with pytest.raises(fix.GuardError):
        fix.apply(conn, tmp_path / 'backup.json', path)
    assert all(r['hide_reason'] == 'not_target' for r in snapshot(conn))


@pytest.mark.parametrize('field,raw', [('model_json', 'broken'), ('model_json', '[]'),
    ('model_json', 'null'), ('model_json', '{"not_target_kind":[]}'),
    ('report_json', 'broken'), ('report_json', '[]'),
    ('report_json', '{"not_target_kind":"sales"}')])
def test_invalid_or_named_excluded(tmp_path, field, raw):
    path, conn = setup_db(tmp_path)
    conn.execute(f'UPDATE ad_reviews SET {field}=? WHERE posting_id=(SELECT MIN(posting_id) FROM ad_reviews)', (raw,))
    conn.commit()
    assert fix.preflight(conn)['count'] == 3


@pytest.mark.parametrize('stage', ['archived', 'dlq', 'ready', 'drafted', 'draft_queued', 'scored', 'ingested'])
def test_pipeline_precedence(tmp_path, stage):
    path, conn = setup_db(tmp_path)
    pid = snapshot(conn)[0]['posting_id']
    staged(conn, pid, stage, reason='not_target')
    assert fix.preflight(conn)['count'] == (4 if stage in ('scored', 'ingested') else 3)


def test_concurrent_drift_aborts(tmp_path):
    path, conn = setup_db(tmp_path)
    before = [dict(r) for r in snapshot(conn)]
    def drift():
        other = sqlite3.connect(path)
        other.execute("UPDATE ad_reviews SET model_json='{}' WHERE posting_id=(SELECT MIN(posting_id) FROM ad_reviews)")
        other.commit()
        other.close()
    with pytest.raises(fix.GuardError):
        fix.apply(conn, tmp_path / 'backup.json', path, before_lock=drift)
    assert all(r['hide_reason'] == 'not_target' for r in snapshot(conn))
    assert [dict(r) for r in snapshot(conn)] != before


def test_rollback_refuses_drift_and_wrong_database(tmp_path):
    path, conn = setup_db(tmp_path)
    backup = tmp_path / 'backup.json'
    fix.apply(conn, backup, path)
    with pytest.raises(fix.GuardError):
        fix.rollback(conn, backup, tmp_path / 'other.sqlite')
    conn.execute("UPDATE ad_reviews SET reason='changed' WHERE posting_id=(SELECT MIN(posting_id) FROM ad_reviews)")
    conn.commit()
    with pytest.raises(fix.GuardError):
        fix.rollback(conn, backup, path)
    assert all(r['hide_reason'] == 'too_senior' for r in snapshot(conn))


def test_trigger_and_existing_backup_refused(tmp_path):
    path, conn = setup_db(tmp_path)
    backup = tmp_path / 'backup.json'
    backup.write_text('keep')
    with pytest.raises(FileExistsError):
        fix.apply(conn, backup, path)
    assert backup.read_text() == 'keep'
    conn.execute("CREATE TRIGGER unexpected AFTER UPDATE ON ad_reviews BEGIN UPDATE ad_reviews SET reason='oops'; END")
    conn.commit()
    with pytest.raises(fix.GuardError):
        fix.apply(conn, tmp_path / 'new.json', path)
    assert all(r['hide_reason'] == 'not_target' for r in snapshot(conn))


def test_transaction_failure_is_atomic(tmp_path, monkeypatch):
    path, conn = setup_db(tmp_path)
    before = [dict(r) for r in snapshot(conn)]
    def fail(*args):
        raise fix.GuardError('injected post-update failure')
    monkeypatch.setattr(fix, 'verify_records', fail)
    with pytest.raises(fix.GuardError):
        fix.apply(conn, tmp_path / 'backup.json', path)
    assert [dict(r) for r in snapshot(conn)] == before


def test_cli_dry_run_and_explicit_offline_gate(tmp_path):
    import subprocess
    import sys
    path, conn = setup_db(tmp_path)
    conn.close()
    command = [sys.executable, '-m', 'scripts.legacy_too_senior', '--db', str(path)]
    refused = subprocess.run(command, capture_output=True, text=True)
    assert refused.returncode == 2
    result = subprocess.run(command + ['--offline-copy'], capture_output=True, text=True)
    assert result.returncode == 0
    assert json.loads(result.stdout) == {'count': 4, 'unsorted': {'all': 4, 'matches': 4}}


def test_aggregate_zero_with_compatibility_and_unrelated_unchanged(tmp_path):
    path, conn = setup_db(tmp_path)
    for n in range(17):
        pid = seed(conn, n + 5, 'Synthetic named role')
        review(conn, pid, verdict='hide', hide_reason='not_target', report_json='{}',
               model_json=json.dumps({'not_target_kind': sorted(q.NOT_TARGET_KEYS)[n % len(q.NOT_TARGET_KEYS)]}))
    unrelated = [dict(r) for r in snapshot(conn)][4:]
    assert fix.aggregates(conn) == {'all': 4, 'matches': 4}
    fix.apply(conn, tmp_path / 'backup.json', path)
    assert fix.aggregates(conn) == {'all': 0, 'matches': 0}
    assert [dict(r) for r in snapshot(conn)][4:] == unrelated
