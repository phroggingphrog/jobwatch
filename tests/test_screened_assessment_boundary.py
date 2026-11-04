"""Scheduled promotion must assess, not prepare an application."""
from test_screened_promote import shortlist
from conftest import make_config
from jobwatch import db
from pipeline import screened, store


def test_scheduled_promotion_is_evaluation_only(tmp_path, monkeypatch):
    config = make_config(tmp_path=tmp_path)
    conn = db.connect(config.db_path)
    store.ensure(conn)
    shortlist(conn, 'synthetic', 4.5)
    def batch(ids, config, conn, **kwargs):
        assert kwargs['operation'] == 'evaluate'
        return {'processed': 0}
    monkeypatch.setattr('pipeline.agentic.service.agentic_batch_run', batch)
    result = screened.promote(conn, config)
    assert result['selected'] == 1
    assert result['promoted'] == 0
    assert len(screened._promoted_ids(conn)) == 0


def test_only_started_jobs_charge_promotion_allowance(tmp_path, monkeypatch):
    config = make_config(tmp_path=tmp_path)
    conn = db.connect(config.db_path)
    store.ensure(conn)
    first = shortlist(conn, 'first', 4.5)
    shortlist(conn, 'second', 4.0)
    def batch(ids, config, conn, **kwargs):
        kwargs['_on_started'](first)
        kwargs['_on_started'](first)  # An ad-refresh retry is the same promotion.
        return {'processed': 1, 'skipped': 1}
    monkeypatch.setattr('pipeline.agentic.service.agentic_batch_run', batch)
    result = screened.promote(conn, config)
    assert result['selected'] == 2
    assert result['promoted'] == 1
    assert len(screened._promoted_ids(conn)) == 1
