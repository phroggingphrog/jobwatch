"""Real persisted synthetic evaluations must pass freshness and safety checks."""
import pytest
from tests.test_agentic_service import world, SyntheticGateway
from jobwatch.llm import LLM
from jobwatch import adtext
from jobwatch.preference_service import pool, create_next, record_pick
from jobwatch.preferences import PreferenceStore, PreferenceError
from pipeline.agentic.service import agentic_batch_run


def test_current_gate_and_changed_ad_invalidate_choice(world):
    conn, config, bundle, add = world
    for pid in (1,2,3): add(pid)
    add(4, low=True)
    summary = agentic_batch_run([1,2,3,4], config, conn, evidence_bundle=bundle,
                                llm=LLM(transport=SyntheticGateway(bundle), keys=['synthetic']))
    assert summary['ready'] == 3
    identity, alternatives = pool(conn, config)
    assert {a['posting_id'] for a in alternatives} == {1,2,3}
    item = create_next(conn, config)
    assert len(item['alternatives']) == 3
    # The actual ad changes after display; POST must re-check exact provenance.
    old = conn.execute('SELECT description FROM postings WHERE id=1').fetchone()[0]
    adtext.save_text(conn, 1, old+' Current ad now requires full-time hours only.', 'synthetic-full')
    conn.commit()
    assert {a['posting_id'] for a in pool(conn, config)[1]} == {2,3}
    with pytest.raises(PreferenceError, match='stale_set'):
        record_pick(conn, config, item['id'], None, 'owner-click')
    assert not PreferenceStore(conn).get_set(item['id'])['answered']


def test_legacy_agentic_rows_are_not_current_evaluations(world):
    conn, config, bundle, add = world
    add(1)
    conn.execute('CREATE TABLE agentic_runs (posting_id INTEGER, run_key TEXT, status TEXT)')
    conn.execute("INSERT INTO agentic_runs VALUES(1,'legacy','ready')")
    conn.commit()
    before = conn.total_changes
    identity, alternatives = pool(conn, config)
    assert alternatives == [] and len(identity) == 64
    assert conn.total_changes == before
