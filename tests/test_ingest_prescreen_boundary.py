"""Canonical location skip audit and override through ingestion."""
from conftest import make_config
from jobwatch import adtext
from jobwatch.prescreen import lifecycle, store
from pipeline.nodes import ingest
from test_prescreen import conn, pinned, accountant, _posting


def test_location_skip_is_recorded_and_posting_override_reaches_ingest(conn, pinned, tmp_path, monkeypatch):
    pinned(accountant())
    _posting(conn, 1, 'Graduate Accountant')
    conn.execute("UPDATE postings SET location='Sydney NSW', state='NSW' WHERE id=1")
    conn.commit()
    fetched = []
    def text(c, row, *args, **kwargs):
        fetched.append(row['id'])
        return 'Reconcile ledgers.', 'full'
    monkeypatch.setattr(adtext, 'ensure_text', text)
    cfg = make_config(tmp_path=tmp_path)
    result = ingest.run(conn, cfg)
    assert result['prescreened'] == 1 and not fetched
    assert store.latest_decision(conn, 1)['outcome'] == 'skip'
    lifecycle.override_skip(conn, 1, term_too=False)
    result = ingest.run(conn, cfg)
    assert result['admitted'] == 1 and fetched == [1]
    assert store.latest_decision(conn, 1)['outcome'] != 'skip'
