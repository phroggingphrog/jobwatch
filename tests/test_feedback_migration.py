"""Phase 6 storage is additive and preserves immutable human history."""
from jobwatch import db


def test_feedback_storage_is_available_and_migration_is_repeatable(tmp_path):
    conn = db.connect(tmp_path / 'jobs.db')
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'feedback_events', 'feedback_prompts', 'selection_requests'} <= tables
    conn.execute("INSERT INTO postings(source,source_id,url,url_hash,dedupe_key,title,first_seen_at,last_seen_at) "
                 "VALUES('synthetic','one','https://example.invalid/one','one','one','Invented role','2026-01-01','2026-01-01')")
    conn.commit()
    assert db.migrate(conn) == len(db.MIGRATIONS)
    assert conn.execute('SELECT title FROM postings').fetchone()[0] == 'Invented role'
