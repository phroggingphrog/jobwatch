import json
import sqlite3
import pytest
from scripts import live_legacy_procedure as live
from scripts import legacy_too_senior as old
from tests.test_legacy_too_senior import setup_db
from tests.web.test_ai import staged


def test_three_roundtrip_and_durable_backup(tmp_path):
    path, c = setup_db(tmp_path, 3)
    manifest = live.inspect(c, path)
    original = live.snapshot(c)
    backup = tmp_path / 'backup.sqlite'
    live.execute(c, path, manifest, backup)
    assert old.aggregates(c) == {'all': 0, 'matches': 0}
    assert backup.stat().st_mode & 0o777 == 0o600
    live.restore(c, path, manifest, backup)
    assert live.snapshot(c) == original
    with pytest.raises(old.GuardError):
        live.restore(c, path, manifest, backup)


@pytest.mark.parametrize('change', ['unrelated', 'eligible', 'pipeline'])
def test_any_changed_data_aborts(tmp_path, change):
    path, c = setup_db(tmp_path, 3)
    manifest = live.inspect(c, path)
    if change == 'unrelated':
        c.execute("UPDATE postings SET title='changed'")
    elif change == 'eligible':
        c.execute("UPDATE ad_reviews SET reason='changed'")
    else:
        staged(c, old.selected(c)[0]['review']['posting_id'], 'archived', reason='not_target')
    c.commit()
    with pytest.raises(old.GuardError):
        live.execute(c, path, manifest, tmp_path / 'backup.sqlite')
    assert all(x['review']['hide_reason'] == 'not_target' for x in old.selected(c))


def test_failure_after_update_rolls_back(tmp_path, monkeypatch):
    path, c = setup_db(tmp_path, 3)
    m = live.inspect(c, path)
    before = live.snapshot(c)
    monkeypatch.setattr(live, 'check_after', lambda *a: (_ for _ in ()).throw(old.GuardError('injected')))
    with pytest.raises(old.GuardError):
        live.execute(c, path, m, tmp_path / 'backup.sqlite')
    assert live.snapshot(c) == before


def test_directory_fsync_failure_prevents_update(tmp_path, monkeypatch):
    path, c = setup_db(tmp_path, 3)
    m = live.inspect(c, path)
    before = live.snapshot(c)
    monkeypatch.setattr(live, 'sync_parent', lambda *a: (_ for _ in ()).throw(OSError('injected')))
    with pytest.raises(OSError):
        live.execute(c, path, m, tmp_path / 'backup.sqlite')
    assert live.snapshot(c) == before


def test_cli_without_approval_never_opens_writer(tmp_path):
    import subprocess
    import sys
    path, c = setup_db(tmp_path, 3)
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps(live.inspect(c, path)))
    before = live.snapshot(c)
    r = subprocess.run([sys.executable, '-m', 'scripts.live_legacy_procedure',
                        '--db', str(path), '--manifest', str(manifest),
                        '--action', 'apply', '--backup', str(tmp_path / 'backup.sqlite')],
                       capture_output=True, text=True)
    assert r.returncode == 1
    assert live.snapshot(c) == before
    assert not (tmp_path / 'backup.sqlite').exists()


def test_manifest_identity_and_count_guards(tmp_path):
    path, c = setup_db(tmp_path, 4)
    with pytest.raises(old.GuardError):
        live.inspect(c, path)


def test_rollback_refuses_unrelated_drift(tmp_path):
    path, c = setup_db(tmp_path, 3)
    m = live.inspect(c, path)
    b = tmp_path / 'backup.sqlite'
    live.execute(c, path, m, b)
    c.execute("UPDATE postings SET title='changed'"); c.commit()
    with pytest.raises(old.GuardError):
        live.restore(c, path, m, b)
