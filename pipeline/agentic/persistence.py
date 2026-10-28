"""Fenced immutable artifacts and canonical apply rows with a durable ledger outbox."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from jobwatch import ledger
from jobwatch.apply.paths import data_dir, drafts_dir, ensure_dir, safe_write_bytes, safe_write_text
from pipeline import store as pipeline_store
from pipeline.schemas import Stage
from pipeline.agentic.contracts import AgenticError, PackageManifest, answers_content_hash
from pipeline.agentic.runtime import validate_model_payload
from pipeline.agentic.store import AgenticStore, Claim
from pipeline.agentic.liveness import latest_observation, observation_metadata, observation_current


KINDS = frozenset({'candidate_digest', 'candidate_digest_counts', 'public_screening', 'snapshot', 'structural_inputs', 'candidate', 'evaluation', 'evaluation_counts', 'proposal', 'review', 'answers',
                   'manifest', 'verify', 'cv', 'letter', 'cv_markdown', 'letter_markdown', 'form_map', 'package_bundle', 'company_research', 'model_insights'})


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec='seconds')


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_artifact(path: str, expected_hash: str, *, data_root: Path | None = None) -> bytes:
    invalid = False
    try:
        p = Path(path)
        p.resolve().relative_to((data_root if data_root is not None else data_dir()).resolve())
        if p.is_symlink() or not p.is_file():
            raise ValueError
        raw = p.read_bytes()
        if _sha(raw) != expected_hash:
            raise ValueError
    except Exception:
        invalid = True
    if invalid:
        raise AgenticError('artifact_invalid') from None
    return raw


def latest_result(conn: sqlite3.Connection, posting_id: int, *, data_root: Path | None = None,
                  parse: frozenset = frozenset({'evaluation', 'candidate', 'manifest'})) -> dict | None:
    """Private protected-board projection of the newest fenced run for a posting."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='agentic_runs'").fetchone():
        return None
    row = conn.execute('SELECT run_key,status,reason FROM agentic_runs WHERE posting_id=? '
                       'ORDER BY generation DESC LIMIT 1', (posting_id,)).fetchone()
    if row is None:
        return None
    if row[1] == 'ready':
        parse = parse | {'manifest'}   # the readiness check below reads the manifest
    result = {'run_key': row[0], 'posting_id': posting_id, 'status': row[1], 'stored_status': row[1], 'reason': row[2],
              'application_id': None, 'draft_id': None, 'version': None, 'package_dir': None,
              'artifact_paths': {}, 'artifact_hashes': {}, 'evaluation': None, 'candidate': None,
              'manifest': None, 'cv_pdf': None, 'letter_pdf': None,
              'liveness': observation_metadata(latest_observation(conn, posting_id))}
    package = conn.execute('SELECT application_id,draft_id,version,package_dir,phase '
                           'FROM agentic_packages WHERE run_key=?', (row[0],)).fetchone()
    if package:
        result.update(zip(('application_id', 'draft_id', 'version', 'package_dir'), package[:4]))
        result['package_phase'] = package[4]
    for kind, path, sha in conn.execute('SELECT kind,path,sha256 FROM agentic_artifacts WHERE run_key=?', (row[0],)):
        result['artifact_paths'][kind] = path
        result['artifact_hashes'][kind] = sha
        if kind in parse:   # list views pass {'evaluation'}: the 3 MB candidate file is only needed on a job's own page
            try:
                result[kind] = json.loads(_read_artifact(path, sha, data_root=data_root))
            except (AgenticError, ValueError):
                result['status'], result['reason'] = 'held', 'artifact_invalid'
    result['cv_pdf'] = result['artifact_paths'].get('cv')
    result['letter_pdf'] = result['artifact_paths'].get('letter')
    if result['status'] == 'ready':
        try:
            if not package or package[4] != 'complete':
                raise AgenticError('artifact_invalid')
            for kind in ('cv', 'letter', 'manifest', 'proposal', 'review', 'evaluation', 'candidate', 'form_map'):
                _read_artifact(result['artifact_paths'][kind], result['artifact_hashes'][kind], data_root=data_root)
        except (AgenticError, KeyError):
            result['status'], result['reason'] = 'held', 'artifact_invalid'
    if result['status'] == 'ready':
        from jobwatch.util import adtext as adtext
        from jobwatch.candidate.contracts import content_hash
        cursor = conn.execute('SELECT * FROM postings WHERE id=?', (posting_id,))
        posting_row = cursor.fetchone()
        posting = dict(zip((d[0] for d in cursor.description), posting_row)) if posting_row else None
        current = False
        if posting:
            text, kind = adtext.local_text(conn, posting)
            ad_hash = content_hash(text.encode())
            package_ad_hash = ((result.get('manifest') or {}).get('run_key') or {}).get('ad_hash')
            current = kind == 'full' and package_ad_hash == ad_hash and observation_current(
                latest_observation(conn, posting_id), posting_id=posting_id, url=posting['url'], ad_hash=ad_hash)
        if not current:
            result['status'], result['reason'] = 'held', 'posting_check_required'
    return result


class PersistenceAdapter:
    def __init__(self, conn, store, *, clock: Callable[[], float] = time.time):
        self.conn, self.store, self.clock = conn, store, clock

    def save_artifact(self, claim: Claim, kind: str, value: Any, *, path: Path | None = None) -> Path:
        if kind not in KINDS:
            raise AgenticError('invalid_artifact_kind')
        # Existing manifest hashes bind Pydantic's insertion-ordered JSON,
        # including nested mappings. Preserve that order across reload/retry.
        raw = value if type(value) is bytes else json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
        destination = path or data_dir() / 'agentic' / claim.run_key / (kind + '.json')
        destination.resolve().relative_to(data_dir().resolve())
        self.store._begin()
        try:
            self.store._assert_live(claim)
            prior = self.conn.execute('SELECT path,sha256 FROM agentic_artifacts WHERE run_key=? AND kind=?',
                                      (claim.run_key, kind)).fetchone()
            if prior and (prior[0] != str(destination) or prior[1] != _sha(raw)):
                raise AgenticError('artifact_conflict')
            safe_write_bytes(destination, raw)
            self.conn.execute('INSERT OR IGNORE INTO agentic_artifacts VALUES(?,?,?,?)',
                              (claim.run_key, kind, str(destination), _sha(raw)))
            self.store._commit()
        except BaseException:
            self.store._rollback()
            raise
        return destination

    def load_artifact(self, run_key: str, kind: str) -> Any:
        row = self.conn.execute('SELECT path,sha256 FROM agentic_artifacts WHERE run_key=? AND kind=?',
                                (run_key, kind)).fetchone()
        if row is None:
            return None
        raw = _read_artifact(row[0], row[1])
        if kind in {'cv', 'letter', 'cv_markdown', 'letter_markdown'}:
            return raw
        invalid = False
        try:
            value = json.loads(raw)
        except Exception:
            invalid = True
        if invalid:
            raise AgenticError('artifact_invalid') from None
        return value

    def _row(self, claim, phase, kind, table, values):
        # The DB row and its exact ledger record commit together. A restart can
        # repeat append after fsync safely because ledger replay is keyed by PK.
        row = ledger._write_row(self.conn, table, values)
        operation_id = f'{claim.run_key}:{phase}:{table}:{row["id"]}'
        record = _json({'at': datetime.now(UTC).isoformat(timespec='microseconds'),
                        'op': 'upsert', 'table': table, 'row': row})
        prior = self.conn.execute('SELECT record_json FROM agentic_ledger_outbox WHERE operation_id=?',
                                  (operation_id,)).fetchone()
        if prior and prior[0] != record:
            raise AgenticError('operation_conflict')
        self.conn.execute('INSERT OR IGNORE INTO agentic_ledger_outbox '
                          '(operation_id,run_key,kind,record_json) VALUES(?,?,?,?)',
                          (operation_id, claim.run_key, kind, record))
        return row

    def reconcile(self) -> int:
        """Flush committed outbox records; never delete or rebuild canonical data."""
        count = 0
        self.store._begin()
        failed = False
        try:
            for ident, kind, payload in self.conn.execute(
                    'SELECT id,kind,record_json FROM agentic_ledger_outbox WHERE sent=0 ORDER BY id').fetchall():
                ledger.append(kind, json.loads(payload))
                self.conn.execute('UPDATE agentic_ledger_outbox SET sent=1 WHERE id=?', (ident,))
                count += 1
            self.store._commit()
        except Exception:
            self.store._rollback()
            failed = True
        if failed:
            raise AgenticError('ledger_unavailable') from None
        return count

    def record_observation(self, claim, observation, captured):
        """Fence public evidence and any full-ad refresh in one transaction."""
        from jobwatch.candidate.contracts import content_hash
        from jobwatch.models import canonical_url
        from pipeline.agentic.service import _capture
        self.store._begin()
        try:
            self.store._assert_live(claim)
            if _capture(self.conn, claim.posting_id) != captured:
                raise AgenticError('snapshot_changed')
            if (observation.posting_id != claim.posting_id or observation.url_hash !=
                    content_hash(canonical_url(captured[0]['url']).encode())):
                raise AgenticError('observation_identity_invalid')
            self.conn.execute('INSERT INTO agentic_posting_observations '
                '(posting_id,run_key,generation,observation_json) VALUES(?,?,?,?)',
                (claim.posting_id,claim.run_key,claim.generation,observation.model_dump_json()))
            changed = observation.status == 'active' and (observation.text != captured[1] or captured[2] != 'full')
            if changed:
                self.conn.execute('INSERT INTO ad_text(posting_id,text,source,fetched_at) VALUES(?,?,?,?) '
                    'ON CONFLICT(posting_id) DO UPDATE SET text=excluded.text,source=excluded.source,fetched_at=excluded.fetched_at',
                    (claim.posting_id,observation.text,'browser-liveness',observation.checked_at))
            self.store._commit()
            return changed
        except BaseException:
            self.store._rollback()
            raise

    def set_stage(self, claim, stage, reason, ad_hash, *, application_id=None, draft_id=None):
        self.store._begin()
        try:
            self.store._assert_live(claim)
            old = self.conn.execute('SELECT stage FROM pipeline_state WHERE posting_id=?', (claim.posting_id,)).fetchone()
            projection = {'agentic': {'run_key': claim.run_key, 'application_id': application_id,
                                      'draft_id': draft_id, 'package_ready': str(stage) == str(Stage.READY),
                                      'form_ready': False, 'liveness': observation_metadata(latest_observation(self.conn, claim.posting_id))}}
            self.conn.execute('INSERT INTO pipeline_state(posting_id,stage,content_hash,data_json,reason,updated_at) '
                'VALUES(?,?,?,?,?,?) ON CONFLICT(posting_id) DO UPDATE SET stage=excluded.stage,'
                'content_hash=excluded.content_hash,data_json=excluded.data_json,reason=excluded.reason,updated_at=excluded.updated_at',
                (claim.posting_id, str(stage), ad_hash, _json(projection), reason, _now()))
            if old is None or old[0] != str(stage):
                pipeline_store.event(self.conn, claim.posting_id, 'agentic', old[0] if old else None, str(stage), 1, reason)
            self.store._commit()
        except BaseException:
            self.store._rollback()
            raise

    def finalize_package(self, claim, manifest, cv_bytes, letter_bytes, operation_id, *, artifacts=None):
        """Idempotently reserve one canonical draft per run and publish verified files."""
        manifest = validate_model_payload(PackageManifest, manifest.model_dump(mode='json'))
        if (manifest.run_key.value != claim.run_key or manifest.run_key.posting_id != claim.posting_id
                or manifest.pdfs != {'cv': _sha(cv_bytes), 'letter': _sha(letter_bytes)}):
            raise AgenticError('invalid_manifest_hashes')
        manifest_hash = _sha(manifest.model_dump_json().encode())
        if artifacts is not None:
            if (artifacts.manifest != manifest or artifacts.evaluation.run_key != manifest.run_key
                    or _sha(artifacts.evaluation.model_dump_json().encode()) != manifest.evaluation_hash
                    or artifacts.proposal.draft_hash != manifest.draft_hash
                    or _sha(artifacts.review.model_dump_json().encode()) != manifest.review_hash
                    or answers_content_hash(artifacts.proposal.screening_answers) != manifest.answers_hash
                    or artifacts.verify_report.get('ok') is not True):
                raise AgenticError('invalid_package')
        self.store._begin()
        try:
            self.store._assert_live(claim)
            if claim.lease_until <= self.clock():
                raise AgenticError('stale_claim')
            package = self.conn.execute('SELECT manifest_hash,application_id,draft_id,version,package_dir,phase '
                                        'FROM agentic_packages WHERE run_key=?', (claim.run_key,)).fetchone()
            if package:
                if package[0] != manifest_hash:
                    raise AgenticError('operation_conflict')
                app_id, draft_id, version, folder, phase = package[1:]
            else:
                app = self.conn.execute('SELECT id,status FROM applications WHERE posting_id=?',
                                        (claim.posting_id,)).fetchone()
                if app is None:
                    match = self.conn.execute('SELECT id,arm FROM matches WHERE posting_id=?', (claim.posting_id,)).fetchone()
                    approw = self._row(claim, 'prepare', 'applications', 'applications', {
                        'posting_id': claim.posting_id, 'match_id': match[0] if match else None,
                        'arm': match[1] if match else None, 'status': 'drafting',
                        'created_at': _now(), 'updated_at': _now()})
                    app_id = approw['id']
                else:
                    app_id = app[0]
                version = (self.conn.execute('SELECT MAX(version) FROM drafts WHERE application_id=?',
                                             (app_id,)).fetchone()[0] or 0) + 1
                folder = str(drafts_dir() / str(app_id) / f'v{version}')
                draftrow = self._row(claim, 'prepare', 'drafts', 'drafts', {
                    'application_id': app_id, 'version': version, 'created_at': _now(),
                    'status': 'drafting', 'dir': folder, 'models_json': _json({'runtime': 'deepagents', 'run_key': claim.run_key})})
                draft_id = draftrow['id']
                self.conn.execute('INSERT INTO agentic_packages VALUES(?,?,?,?,?,?,?)',
                    (claim.run_key, manifest_hash, app_id, draft_id, version, folder, 'prepared'))
                phase = 'prepared'
            self.store._commit()
        except BaseException:
            self.store._rollback()
            raise
        self.reconcile()
        result = {'status': 'accepted', 'application_id': app_id, 'draft_id': draft_id,
                  'version': version, 'run_key': claim.run_key, 'package_dir': folder}
        if phase == 'complete':
            for kind in ('cv', 'letter', 'manifest'):
                if self.load_artifact(claim.run_key, kind) is None:
                    raise AgenticError('artifact_invalid')
            return result
        vdir = Path(folder)
        self.save_artifact(claim, 'cv', cv_bytes, path=vdir / 'cv.pdf')
        self.save_artifact(claim, 'letter', letter_bytes, path=vdir / 'letter.pdf')
        self.save_artifact(claim, 'manifest', manifest.model_dump(mode='json'), path=vdir / 'manifest.json')
        if artifacts is not None:
            values = {'proposal': artifacts.proposal.model_dump(mode='json'),
                      'review': artifacts.review.model_dump(mode='json'), 'verify': artifacts.verify_report,
                      'answers': [a.model_dump(mode='json') for a in artifacts.proposal.screening_answers]}
            for kind, value in values.items():
                self.save_artifact(claim, kind, value, path=vdir / f'{kind}.json')
            self.save_artifact(claim, 'cv_markdown', artifacts.cv_markdown.encode(), path=vdir / 'cv.md')
            self.save_artifact(claim, 'letter_markdown', artifacts.letter_markdown.encode(), path=vdir / 'letter.md')
            # Compatibility files used by existing protected download/review routes.
            safe_write_text(vdir / 'summary.json', _json({'verify_ok': True, 'run_key': claim.run_key,
                'draft_hash': manifest.draft_hash, 'owner_to_answer': manifest.owner_to_answer}))
            safe_write_text(vdir / 'content.json', _json(artifacts.proposal.content))
        self.store._begin()
        try:
            self.store._assert_live(claim)
            current_phase = self.conn.execute('SELECT phase FROM agentic_packages WHERE run_key=?', (claim.run_key,)).fetchone()[0]
            if current_phase == 'prepared':
                verify = artifacts.verify_report if artifacts is not None else dict(manifest.verification)
                review = artifacts.review.model_dump(mode='json') if artifacts is not None else {'review_hash': manifest.review_hash}
                self._row(claim, 'complete', 'drafts', 'drafts', {'id': draft_id, 'status': 'ready',
                    'claims_json': _json(artifacts.proposal.content if artifacts is not None else {}),
                    'verify_json': _json(verify), 'review_json': _json(review), 'error': None})
                app = self.conn.execute('SELECT status FROM applications WHERE id=?', (app_id,)).fetchone()
                # Owner-controlled outcome states are never rewound by package generation.
                status = 'drafted' if app[0] in {'interested', 'drafting', 'drafted'} else app[0]
                self._row(claim, 'complete', 'applications', 'applications',
                          {'id': app_id, 'status': status, 'updated_at': _now()})
                self._row(claim, 'complete', 'applications', 'application_events', {
                    'application_id': app_id, 'at': _now(), 'kind': 'draft', 'from_status': app[0],
                    'to_status': status, 'actor': 'jobwatch', 'source': 'pipeline-agentic',
                    'detail_json': _json({'run_key': claim.run_key, 'draft_id': draft_id, 'version': version,
                                          'package_ready': True, 'form_ready': False})})
                self.conn.execute("UPDATE agentic_packages SET phase='journal_pending' WHERE run_key=?", (claim.run_key,))
            self.store._commit()
        except BaseException:
            self.store._rollback()
            raise
        self.reconcile()
        self.store._begin()
        try:
            self.store._assert_live(claim)
            self.conn.execute("UPDATE agentic_packages SET phase='complete' WHERE run_key=?", (claim.run_key,))
            self.store._commit()
        except BaseException:
            self.store._rollback()
            raise
        return result
