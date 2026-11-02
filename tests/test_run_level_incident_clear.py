"""A crashed discovery run keeps its cause, and the same unit's next clean run clears the run-level incident."""
import json
import sqlite3

import pytest

from jobwatch import run as runner
from pipeline.agentic import incidents

def paused_run_incident(conn, run_id='collector-a', unit='jobwatch-native-fast', posting_id=None):
    incidents.begin_run(conn, run_id, unit=unit)
    row = incidents.report(conn, posting_id=posting_id, run_id=run_id, reason='execution_failed', phase='collection')
    incidents.end_run(conn, run_id, state='failed')
    return row

def test_same_unit_clean_run_releases_the_run_level_incident():
    with sqlite3.connect(':memory:') as conn:
        paused_run_incident(conn)
        assert incidents.list_incidents(conn)[0]['state'] == 'paused'
        assert incidents.resolve_run_level(conn, unit='jobwatch-native-fast', now=123.0) == 1
        row = incidents.list_incidents(conn, include_resolved=True)[0]
        assert row['state'] == 'released' and row['resolved_at'] == 123.0

def test_another_units_success_leaves_the_incident_paused():
    with sqlite3.connect(':memory:') as conn:
        paused_run_incident(conn)
        assert incidents.resolve_run_level(conn, unit='jobwatch-native-slow') == 0
        assert incidents.list_incidents(conn)[0]['state'] == 'paused'

def test_a_job_incident_is_never_cleared_by_a_discovery_run():
    with sqlite3.connect(':memory:') as conn:
        paused_run_incident(conn, posting_id=42)
        assert incidents.resolve_run_level(conn, unit='jobwatch-native-fast') == 0
        assert incidents.list_incidents(conn)[0]['state'] == 'paused'

def test_crashed_collection_records_the_missing_module_and_its_frame(tmp_path, monkeypatch):
    from conftest import make_config
    from pipeline.agentic import discovery
    config = make_config(tmp_path=tmp_path)
    def crash(conn, config):
        raise ModuleNotFoundError("No module named 'jobwatch.synthetic_missing'", name='jobwatch.synthetic_missing')
    monkeypatch.setattr(discovery, 'prepare_run', crash)
    with pytest.raises(ModuleNotFoundError):
        runner.run(config, 'fast')
    with sqlite3.connect(config.db_path) as conn:
        stats = json.loads(conn.execute('SELECT stats_json FROM runs ORDER BY id DESC LIMIT 1').fetchone()[0])
    assert stats['error'] == 'ModuleNotFoundError'
    detail = stats['error_detail']
    assert detail['module'] == 'jobwatch.synthetic_missing'
    assert detail['where'].startswith('tests/test_run_level_incident_clear.py:')
    assert 'message' not in detail

def test_cli_clears_the_incident_only_after_its_unit_runs_clean(tmp_path, monkeypatch):
    from conftest import make_config
    from jobwatch import cli
    config = make_config(tmp_path=tmp_path)
    summary = {'run_id': 1, 'requests': 0, 'alerts': {}, 'pruned': 0, 'collectors': [
        {'collector': 'synthetic', 'status': 'ok', 'fetched': 1, 'au_kept': 1, 'vic': 0, 'new': 1,
         'matched': 0, 'queued': 0, 'errors': [], 'latency_ms': 10}]}
    monkeypatch.setattr(cli, 'load_config', lambda _: config)
    monkeypatch.setattr(cli.discovery_gate, 'allowed', lambda cmd: True)
    monkeypatch.setattr('jobwatch.run.run', lambda *args, **kwargs: summary)
    monkeypatch.setenv('JOBWATCH_SERVICE_UNIT', 'jobwatch-native-fast')
    with sqlite3.connect(config.db_path) as conn:
        paused_run_incident(conn)
    assert cli.main(['run', '--tier', 'fast']) == 0
    with sqlite3.connect(config.db_path) as conn:
        assert incidents.list_incidents(conn) == []
        assert incidents.list_incidents(conn, include_resolved=True)[0]['state'] == 'released'
