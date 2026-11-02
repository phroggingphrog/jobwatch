"""Reconsider category-only decisions after a snapshot changes, without models.

This function never restores closed jobs, explicit eligibility exclusions or
technical errors. It keeps evaluation text and event history for audit access.
"""
from __future__ import annotations

import json

from . import store, tracks
from .schemas import Stage
from .title_triage import snapshot_hash

CATEGORY_REASONS = {'title_drop', 'title_not_target', 'title_triage_drop', 'title_triage_not_target', 'side_track'}


def refresh(conn, config, *, limit=100):
    snapshot = tracks.settings(config)
    digest = snapshot_hash(snapshot)
    conn.execute('CREATE TABLE IF NOT EXISTS category_refresh_state(posting_id INTEGER PRIMARY KEY, snapshot_hash TEXT NOT NULL)')
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pipeline_state'").fetchone(): return 0
    rows = conn.execute("SELECT p.id,p.title,p.closed_at,s.stage,s.reason,s.data_json FROM postings p JOIN pipeline_state s ON s.posting_id=p.id LEFT JOIN category_refresh_state c ON c.posting_id=p.id WHERE c.snapshot_hash IS NULL OR c.snapshot_hash<>? ORDER BY s.updated_at,p.id LIMIT ?", (digest,limit)).fetchall()
    changed = 0
    for pid,title,closed,stage,reason,raw in rows:
        if closed: continue
        data = json.loads(raw)
        new_id = tracks.classify(title, snapshot)
        category = snapshot.get(new_id)
        old = data.get('track')
        permitted = category is None or category.action != 'archive' or not category.exclusion_confirmed
        restored = False
        if stage == Stage.ARCHIVED and reason in CATEGORY_REASONS and permitted:
            store.move(conn,pid,'category_refresh',Stage.ARCHIVED,Stage.INGESTED,
                output={'category_snapshot_hash':digest,'previous_track':old},reason='category_changed')
            changed += 1
            restored = True
        elif stage == Stage.SIDE and (category is None or category.action != 'side'):
            store.move(conn,pid,'category_refresh',Stage.SIDE,Stage.INGESTED,
                output={'category_snapshot_hash':digest,'previous_track':old},reason='category_changed')
            changed += 1
            restored = True
        if restored and 'ingest' not in data:
            from .nodes.ingest import make_ad
            from jobwatch.util import adtext
            posting = conn.execute('SELECT * FROM postings WHERE id=?',(pid,)).fetchone()
            text,kind = adtext.get_text(conn,pid) or ('', 'partial')
            text = text or posting['description'] or ''
            if text:
                kind = kind if kind in ('full','partial','teaser') else 'partial'
                data['ingest'] = make_ad(posting,text,kind,'unknown').model_dump()
        data['track'] = new_id
        data['category_snapshot_hash'] = digest
        # Merge a refresh event written above instead of overwriting it.
        current = store.get(conn,pid)
        current['data'].update(data)
        conn.execute('UPDATE pipeline_state SET data_json=? WHERE posting_id=?',(json.dumps(current['data'],ensure_ascii=False),pid))
        conn.execute('INSERT INTO category_refresh_state VALUES(?,?) ON CONFLICT(posting_id) DO UPDATE SET snapshot_hash=excluded.snapshot_hash',(pid,digest))
    return changed
