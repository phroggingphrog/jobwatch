"""Dismissal transitions invalidate snapshots even after restoration."""
from tests.baseline_support import frozen, world
from pipeline.agentic import feedback, shortlist


def test_rejection_and_restoration_require_new_current_snapshots(frozen):
    conn, config = frozen.conn, frozen.config
    entries = shortlist.build_shortlist(conn, config)
    shown = next(e for e in entries if e.posting_id == 42)
    rejected = feedback.record_feedback(conn, config, posting_id=42, kind='reject', request_id='reject',
        actor='person', expected_entry_id=shown.entry_id, reason_code='not_this_employer')
    assert shortlist.load_latest(conn, config=config)['status'] == 'stale'
    assert 42 not in {e.posting_id for e in shortlist.build_shortlist(conn, config)}
    feedback.record_feedback(conn, config, posting_id=42, kind='restore', request_id='restore',
        actor='person', expected_rejection_id=rejected['id'])
    assert shortlist.load_latest(conn, config=config)['status'] == 'stale'
    restored = shortlist.build_shortlist(conn, config)
    assert 42 in {e.posting_id for e in restored}
    assert next(e.entry_id for e in restored if e.posting_id == 42) != shown.entry_id
