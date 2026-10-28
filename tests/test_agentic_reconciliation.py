"""Canonical migrated-schema persistence, ledger recovery and fencing acceptance."""
import hashlib
import json

import pytest

from jobwatch import db, ledger
from pipeline.agentic.contracts import AgenticError, PackageManifest, RunKey
from pipeline.agentic.persistence import PersistenceAdapter
from pipeline.agentic.store import AgenticStore


def key(posting=42):
    return RunKey(posting_id=posting, ad_hash='a'*64, evidence_hash='b'*64,
                  rubric_version='career-ops-v1', config_hash='c'*64)


def manifest(rk, cv, letter):
    return PackageManifest(run_key=rk, evaluation_hash='a'*64, evidence_hash='b'*64,
        answers_hash='a'*64, draft_hash='a'*64, review_hash='a'*64,
        pdfs={'cv': hashlib.sha256(cv).hexdigest(), 'letter': hashlib.sha256(letter).hexdigest()},
        verification={'cv_pdf': True, 'letter_pdf': True, 'claims': True, 'review': True}, owner_to_answer=0)


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('JOBWATCH_PROFILE_DIR', str(tmp_path / 'profile'))
    conn = db.connect(tmp_path / 'db.sqlite')
    conn.execute('INSERT INTO postings(id,source,source_id,url,url_hash,dedupe_key,title,first_seen_at,last_seen_at) '
                 "VALUES(42,'synthetic','42','https://example.invalid/42','url42','dedupe42','Junior analyst','now','now')")
    conn.commit()
    # Prove application_id must be looked up by posting_id, never assumed equal.
    ledger.upsert(conn, 'applications', 'applications', {'id': 17, 'posting_id': 42,
        'status': 'interested', 'created_at': 'now', 'updated_at': 'now'})
    clock = [100.0]
    store = AgenticStore(conn, clock=lambda: clock[0]); store.ensure()
    adapter = PersistenceAdapter(conn, store, clock=lambda: clock[0])
    claim = store.claim(key(), 'worker', 60)
    return conn, store, adapter, claim, clock


def test_real_schema_reuses_application_and_idempotent_run_scoped_draft(world, tmp_path):
    conn, store, adapter, claim, _ = world
    cv, letter = b'%PDF synthetic CV', b'%PDF synthetic letter'
    package = manifest(key(), cv, letter)
    result = adapter.finalize_package(claim, package, cv, letter, 'finalize-one')
    assert result['application_id'] == 17 and result['version'] == 1
    assert conn.execute('SELECT status FROM applications WHERE id=17').fetchone()[0] == 'drafted'
    row = conn.execute('SELECT created_at,status,dir,verify_json,models_json FROM drafts').fetchone()
    assert row['status'] == 'ready' and json.loads(row['models_json'])['run_key'] == claim.run_key
    assert (tmp_path / 'data/drafts/17/v1/cv.pdf').read_bytes() == cv
    again = adapter.finalize_package(claim, package, cv, letter, 'different-operation-same-run')
    assert result == again
    assert conn.execute('SELECT COUNT(*) FROM drafts').fetchone()[0] == 1
    assert conn.execute('SELECT COUNT(*) FROM application_events').fetchone()[0] == 1
    before = ledger.snapshot(conn)
    ledger.reindex(conn)
    assert ledger.snapshot(conn) == before


def test_interrupted_ledger_flush_recovers_same_package_without_duplicate_rows(world, monkeypatch):
    conn, store, adapter, claim, _ = world
    cv, letter = b'%PDF CV', b'%PDF letter'
    package = manifest(key(), cv, letter)
    original = ledger.append
    calls = []

    def interrupted(kind, record):
        original(kind, record)
        calls.append(record)
        raise OSError('private failure after fsync')

    monkeypatch.setattr(ledger, 'append', interrupted)
    with pytest.raises(AgenticError, match='ledger_unavailable'):
        adapter.finalize_package(claim, package, cv, letter, 'op')
    assert conn.execute('SELECT COUNT(*) FROM drafts').fetchone()[0] == 1
    assert conn.execute('SELECT sent FROM agentic_ledger_outbox ORDER BY id LIMIT 1').fetchone()[0] == 0
    monkeypatch.setattr(ledger, 'append', original)
    result = adapter.finalize_package(claim, package, cv, letter, 'op')
    assert result['version'] == 1 and conn.execute('SELECT COUNT(*) FROM drafts').fetchone()[0] == 1
    assert conn.execute('SELECT COUNT(*) FROM agentic_ledger_outbox WHERE sent=0').fetchone()[0] == 0
    before = ledger.snapshot(conn)
    ledger.reindex(conn)
    assert ledger.snapshot(conn) == before


def test_wrong_manifest_input_or_stale_worker_cannot_publish(world):
    conn, store, adapter, claim, clock = world
    cv, letter = b'%PDF CV', b'%PDF letter'
    with pytest.raises(AgenticError, match='invalid_manifest_hashes'):
        adapter.finalize_package(claim, manifest(key(), cv, letter), b'changed', letter, 'op')
    wrong_key = key(43)
    with pytest.raises(AgenticError, match='invalid_manifest_hashes'):
        adapter.finalize_package(claim, manifest(wrong_key, cv, letter), cv, letter, 'op')
    clock[0] = 161.0
    fresh = store.claim(key(), 'next-worker', 60)
    with pytest.raises(AgenticError, match='stale_claim'):
        adapter.finalize_package(claim, manifest(key(), cv, letter), cv, letter, 'op')
    assert conn.execute('SELECT COUNT(*) FROM drafts').fetchone()[0] == 0
    assert fresh.generation > claim.generation


def test_changed_manifest_for_same_run_and_corrupt_artifact_fail_closed(world, tmp_path):
    conn, store, adapter, claim, _ = world
    cv, letter = b'%PDF CV', b'%PDF letter'
    adapter.finalize_package(claim, manifest(key(), cv, letter), cv, letter, 'op')
    with pytest.raises(AgenticError, match='operation_conflict'):
        adapter.finalize_package(claim, manifest(key(), b'changed', letter), b'changed', letter, 'op')
    (tmp_path / 'data/drafts/17/v1/cv.pdf').write_bytes(b'changed')
    with pytest.raises(AgenticError, match='artifact_invalid'):
        adapter.finalize_package(claim, manifest(key(), cv, letter), cv, letter, 'op')


def test_late_outbox_recovery_cannot_rewind_a_newer_owner_outcome(world, monkeypatch):
    """Canonical replay must retain an owner update made after a flush interruption."""
    conn, store, adapter, claim, _ = world
    cv, letter = b'%PDF CV', b'%PDF letter'
    original = ledger.append
    failed = []

    def unavailable_on_completed_application(kind, record):
        if record.get('table') == 'applications' and record.get('row', {}).get('status') == 'drafted':
            failed.append(record)
            raise OSError('synthetic interrupted completion flush')
        return original(kind, record)

    monkeypatch.setattr(ledger, 'append', unavailable_on_completed_application)
    with pytest.raises(AgenticError, match='ledger_unavailable'):
        adapter.finalize_package(claim, manifest(key(), cv, letter), cv, letter, 'op')
    assert failed
    assert conn.execute('SELECT status FROM applications WHERE id=17').fetchone()[0] == 'drafted'
    monkeypatch.setattr(ledger, 'append', original)
    ledger.upsert(conn, 'applications', 'applications', {'id': 17, 'status': 'submitted', 'updated_at': 'later'})
    adapter.reconcile()
    assert conn.execute('SELECT status FROM applications WHERE id=17').fetchone()[0] == 'submitted'
    before = ledger.snapshot(conn)
    ledger.reindex(conn)
    assert ledger.snapshot(conn) == before
    assert conn.execute('SELECT status FROM applications WHERE id=17').fetchone()[0] == 'submitted'


@pytest.mark.parametrize('dry_run', [False, True])
def test_reindex_refuses_pending_outbox_update_to_an_existing_row(world, dry_run):
    conn, store, adapter, claim, _ = world
    # This key already exists in the ledger, so the legacy unknown-key guard
    # alone cannot protect its more recent committed-but-unflushed value.
    adapter._row(claim, 'synthetic-update', 'applications', 'applications',
                 {'id': 17, 'status': 'drafted', 'updated_at': 'later'})
    conn.commit()
    before = ledger.snapshot(conn)
    with pytest.raises(ledger.ReindexRefused, match='pending agentic ledger records'):
        ledger.reindex(conn, dry_run=dry_run)
    assert ledger.snapshot(conn) == before
    assert conn.execute('SELECT COUNT(*) FROM agentic_ledger_outbox WHERE sent=0').fetchone()[0] == 1
    adapter.reconcile()
    ledger.reindex(conn)
    assert ledger.snapshot(conn) == before
