"""Bounded OFFLINE legacy correction. No default DB path; stdout is aggregates only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from jobwatch.web import queries as q

EXPECTED = 4


class GuardError(RuntimeError):
    pass


def object_json(raw):
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def digest(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def rows(conn):
    conn.row_factory = sqlite3.Row
    result = []
    for raw in conn.execute('SELECT * FROM ad_reviews ORDER BY posting_id'):
        row = dict(raw)
        pl = conn.execute('SELECT * FROM pipeline_state WHERE posting_id=?', (row['posting_id'],)).fetchone()
        result.append({'review': row, 'pipeline': dict(pl) if pl else None})
    return result


def eligible(item):
    r, pl = item['review'], item['pipeline']
    report, model = object_json(r['report_json']), object_json(r['model_json'])
    if r['verdict'] != 'hide' or r['hide_reason'] != 'not_target' or report is None or model is None:
        return False
    kind = report.get('not_target_kind')
    if isinstance(kind, str) and kind in q.NOT_TARGET_KEYS:
        return False
    if model.get('not_target_kind') != 'too_senior':
        return False
    # Use the candidate's actual effective-reader semantics, not duplicated stage lists.
    ai = q.ai_from_row({'ai_pid': r['posting_id'], 'ai_verdict': r['verdict'],
                        'ai_hide_reason': r['hide_reason'], 'ai_report': r['report_json'],
                        'ai_model_json': r['model_json']})
    override = q.ai_from_pipeline({'pl_stage': pl['stage'] if pl else None,
                                  'pl_data': pl['data_json'] if pl else None,
                                  'pl_reason': pl['reason'] if pl else None,
                                  'pl_at': pl['updated_at'] if pl else None})
    return override is None and ai['hide_reason'] == 'not_target'


def selected(conn):
    return [item for item in rows(conn) if eligible(item)]


def aggregates(conn):
    return {scope: sum(r['ai'] is not None and r['ai']['verdict'] == 'hide'
                       and r['ai']['hide_reason'] == 'not_target' for r in q.load_rows(conn, scope))
            for scope in ('all', 'matches')}


def preflight(conn):
    return {'count': len(selected(conn)), 'unsorted': aggregates(conn)}


def require_four(items):
    if len(items) != EXPECTED:
        raise GuardError('Expected exactly four eligible rows; aborted')


def begin(conn):
    if conn.in_transaction:
        raise GuardError('Existing transaction; aborted')
    conn.execute('BEGIN IMMEDIATE')
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name='ad_reviews'").fetchone():
        raise GuardError('Review triggers present; aborted')


def apply(conn, backup, database, before_lock=None):
    initial = selected(conn)
    require_four(initial)
    if before_lock:
        before_lock()  # injection seam for real separate-connection drift tests
    try:
        begin(conn)
        current = selected(conn)
        require_four(current)
        if current != initial:
            raise GuardError('Preflight drift; aborted')
        records = []
        for item in current:
            expected = {'review': {**item['review'], 'hide_reason': 'too_senior'}, 'pipeline': item['pipeline']}
            records.append({'posting_id': item['review']['posting_id'], 'old_reason': 'not_target',
                            'before': digest(item), 'after': digest(expected)})
        payload = {'version': 1, 'database': str(Path(database).resolve()), 'records': records}
        # Exclusive creation prevents clobbering previous recovery evidence. No ad text is saved.
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as out:
            json.dump(payload, out)
            out.flush()
            os.fsync(out.fileno())
        for item in current:
            pid = item['review']['posting_id']
            # Recheck full review and pipeline immediately before each guarded UPDATE.
            fresh = next((x for x in rows(conn) if x['review']['posting_id'] == pid), None)
            if fresh != item or not eligible(fresh):
                raise GuardError('Predicate drift; aborted')
            changed = conn.execute("UPDATE ad_reviews SET hide_reason='too_senior' WHERE posting_id=? AND verdict='hide' AND hide_reason='not_target'", (pid,)).rowcount
            if changed != 1:
                raise GuardError('Update count mismatch; aborted')
        verify_records(conn, records, 'after')
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def verify_records(conn, records, state):
    require_four(records)
    if len({r['posting_id'] for r in records}) != EXPECTED:
        raise GuardError('Duplicate recovery records; aborted')
    current = {item['review']['posting_id']: item for item in rows(conn)}
    for record in records:
        item = current.get(record['posting_id'])
        if item is None or digest(item) != record[state] or record['old_reason'] != 'not_target':
            raise GuardError('Recovery row drift; aborted')


def rollback(conn, backup, database):
    payload = json.loads(Path(backup).read_text())
    if payload.get('version') != 1 or payload.get('database') != str(Path(database).resolve()):
        raise GuardError('Recovery database mismatch; aborted')
    try:
        begin(conn)
        records = payload['records']
        verify_records(conn, records, 'after')
        for record in records:
            changed = conn.execute("UPDATE ad_reviews SET hide_reason=? WHERE posting_id=? AND verdict='hide' AND hide_reason='too_senior'", (record['old_reason'], record['posting_id'])).rowcount
            if changed != 1:
                raise GuardError('Rollback count mismatch; aborted')
        verify_records(conn, records, 'before')
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--offline-copy', action='store_true', required=True,
                        help='Attest this is a synthetic/private offline copy, NOT the live database')
    parser.add_argument('--action', choices=['dry-run', 'apply', 'rollback'], default='dry-run')
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    path = args.db.resolve(strict=True)
    # Defense in depth: refuse the canonical data tree even with an offline attestation.
    live_tree = (Path.home() / 'brain/data/jobwatch').resolve()
    if path == live_tree or live_tree in path.parents:
        parser.error('Live data tree refused; use an offline copy')
    if args.action != 'dry-run' and args.backup is None:
        parser.error('--backup required for apply/rollback')
    mode = 'ro' if args.action == 'dry-run' else 'rw'
    conn = sqlite3.connect(path.as_uri() + '?mode=' + mode, uri=True)
    try:
        if args.action == 'apply':
            apply(conn, args.backup, path)
        elif args.action == 'rollback':
            rollback(conn, args.backup, path)
        print(json.dumps(preflight(conn), sort_keys=True))
    except (GuardError, sqlite3.Error, ValueError, OSError, KeyError):
        # Do not leak row contents, identifiers, filesystem paths, or SQL parameters.
        parser.exit(1, 'Guard/IO failure; aborted. Inspect private recovery evidence offline.\n')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
