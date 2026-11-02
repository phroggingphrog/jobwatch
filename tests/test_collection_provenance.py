"""A crashed collection run keeps its invocation identity and a safe call site, never exception text (issue #51)."""
import json

import pytest

from jobwatch.run import _error_detail


def test_exception_text_and_local_values_are_not_retained():
    secret = 'private candidate and posting text'

    def fail(secret):
        raise ModuleNotFoundError(secret, name='some_missing_module')

    try:
        fail(secret)
    except ModuleNotFoundError as exc:
        result = _error_detail(exc)
    assert result['module'] == 'some_missing_module'
    assert result['where'].startswith('tests/test_collection_provenance.py:')
    assert secret not in repr(result)


def test_external_exception_does_not_export_external_path():
    namespace = {}
    exec('def fail():\n    raise ValueError("private text")', namespace)
    try:
        namespace['fail']()
    except ValueError as exc:
        result = _error_detail(exc)
    assert result['module'] is None
    assert 'private text' not in repr(result)


def test_failed_run_persists_invocation_identity_and_safe_origin(tmp_path, monkeypatch):
    from conftest import make_config
    from jobwatch import db, run
    from pipeline.agentic import discovery
    config = make_config(tmp_path=tmp_path)

    def fail(*args):
        raise ModuleNotFoundError('private text', name='some_missing_module')

    monkeypatch.setattr(discovery, 'prepare_run', fail)
    with pytest.raises(ModuleNotFoundError):
        run.run(config, 'fast', dry_run=True, run_id='synthetic-invocation')
    with db.connect(config.db_path) as conn:
        value = json.loads(conn.execute('SELECT stats_json FROM runs').fetchone()[0])
    assert value['invocation_id'] == 'synthetic-invocation'
    assert value['error'] == 'ModuleNotFoundError'
    assert value['error_detail']['module'] == 'some_missing_module'
    assert value['error_detail']['where'].startswith('tests/test_collection_provenance.py:')
    assert 'private text' not in json.dumps(value)
