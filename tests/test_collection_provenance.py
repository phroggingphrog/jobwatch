"""Collector failures retain safe origin metadata without exception text."""
import json

import pytest

from jobwatch.run import failure_provenance


def test_exception_text_and_local_values_are_not_retained():
    secret = 'private candidate and posting text'
    namespace = {'__name__': 'jobwatch.synthetic'}
    exec('def fail(secret):\n    raise ModuleNotFoundError(secret)', namespace)
    try:
        namespace['fail'](secret)
    except ModuleNotFoundError as exc:
        result = failure_provenance(exc)
    assert result == {'exception_type': 'ModuleNotFoundError',
                      'origin_module': 'jobwatch.synthetic', 'origin_function': 'fail'}
    assert secret not in repr(result)


def test_external_exception_does_not_export_external_path():
    try:
        raise ValueError('private text')
    except ValueError as exc:
        assert failure_provenance(exc) == {'exception_type': 'ValueError'}


def test_failed_run_persists_invocation_identity_and_safe_origin(tmp_path, monkeypatch):
    from conftest import make_config
    from jobwatch import db, run
    from pipeline.agentic import discovery
    config = make_config(tmp_path=tmp_path)
    namespace = {'__name__': 'pipeline.agentic.synthetic'}
    exec('def fail(*args):\n    raise ModuleNotFoundError("private text")', namespace)
    monkeypatch.setattr(discovery, 'prepare_run', namespace['fail'])
    with pytest.raises(ModuleNotFoundError):
        run.run(config, 'fast', dry_run=True, run_id='synthetic-invocation')
    with db.connect(config.db_path) as conn:
        value = json.loads(conn.execute('SELECT stats_json FROM runs').fetchone()[0])
    assert value['invocation_id'] == 'synthetic-invocation'
    assert value['error'] == 'ModuleNotFoundError'
    assert value['failure_provenance']['origin_module'] == 'pipeline.agentic.synthetic'
    assert 'private text' not in json.dumps(value)
