"""Separate live procedure. Inspection is read-only; writes require bound board approval."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import urllib.request

from scripts import legacy_too_senior as old

EXPECTED = 3
GuardError = old.GuardError


def snapshot(c):
    """Logical whole-database snapshot, including schema; no private contents printed."""
    schema = [tuple(r) for r in c.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name')]
    data = {}
    for typ, name, _, _ in schema:
        if typ == 'table':
            quoted = '"' + name.replace('"', '""') + '"'
            data[name] = sorted([list(r) for r in c.execute('SELECT * FROM ' + quoted)], key=lambda r: json.dumps(r, sort_keys=True, default=str))
    return {'schema': schema, 'data': data}


def snap_hash(c):
    return old.digest(snapshot(c))


def identity(path):
    p = Path(path).resolve(strict=True)
    s = p.stat()
    return {'path': str(p), 'device': s.st_dev, 'inode': s.st_ino}


def inspect(c, path):
    items = old.selected(c)
    counts = old.aggregates(c)
    if len(items) != EXPECTED or counts != {'all': EXPECTED, 'matches': EXPECTED}:
        raise GuardError('Changed counts; diagnose privately')
    return {'version': 1, 'database': identity(path), 'snapshot': snap_hash(c),
            'eligible': old.digest(items), 'ids': [x['review']['posting_id'] for x in items],
            'count': EXPECTED, 'unsorted': counts}


def sync_parent(path):
    fd = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def durable_backup(path, backup, expected):
    # Writer lock is held by caller. A separate RO connection sees the same committed snapshot.
    fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    source = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    target = sqlite3.connect(backup)
    try:
        source.execute('PRAGMA query_only=ON')
        source.backup(target)
        if snap_hash(target) != expected:
            raise GuardError('Backup mismatch')
        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise GuardError('Backup integrity failure')
    finally:
        source.close()
        target.close()
    fd = os.open(backup, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    sync_parent(backup)


def corrected_snapshot(c, ids):
    before = snapshot(c)
    columns = [r[1] for r in c.execute('PRAGMA table_info(ad_reviews)')]
    pid, reason = columns.index('posting_id'), columns.index('hide_reason')
    for row in before['data']['ad_reviews']:
        if row[pid] in ids:
            row[reason] = 'too_senior'
    before['data']['ad_reviews'].sort(key=lambda r: json.dumps(r, sort_keys=True, default=str))
    return before


def check_after(c, expected):
    if snap_hash(c) != expected or old.aggregates(c) != {'all': 0, 'matches': 0}:
        raise GuardError('Unexpected postimage')


def execute(c, path, manifest, backup):
    try:
        old.begin(c)
        if inspect(c, path) != manifest:
            raise GuardError('Changed snapshot or identity')
        after = old.digest(corrected_snapshot(c, manifest['ids']))
        durable_backup(path, backup, manifest['snapshot'])
        for pid in manifest['ids']:
            n = c.execute("UPDATE ad_reviews SET hide_reason='too_senior' WHERE posting_id=? AND verdict='hide' AND hide_reason='not_target'", (pid,)).rowcount
            if n != 1:
                raise GuardError('Update count mismatch')
        check_after(c, after)
        c.commit()
    except BaseException:
        c.rollback()
        raise


def restore(c, path, manifest, backup):
    b = sqlite3.connect(Path(backup).resolve(strict=True).as_uri() + '?mode=ro', uri=True)
    try:
        if snap_hash(b) != manifest['snapshot']:
            raise GuardError('Wrong backup')
        after = old.digest(corrected_snapshot(b, manifest['ids']))
        old.begin(c)
        if identity(path) != manifest['database'] or snap_hash(c) != after:
            raise GuardError('Rollback drift')
        for pid in manifest['ids']:
            n = c.execute("UPDATE ad_reviews SET hide_reason='not_target' WHERE posting_id=? AND verdict='hide' AND hide_reason='too_senior'", (pid,)).rowcount
            if n != 1:
                raise GuardError('Rollback count mismatch')
        if snap_hash(c) != manifest['snapshot']:
            raise GuardError('Rollback postimage mismatch')
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        b.close()


def approve(approval_id, action, manifest):
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    if subprocess.check_output(['git', 'status', '--porcelain'], text=True).strip():
        raise GuardError('Unclean candidate')
    url = os.environ['PAPERCLIP_API_URL'].rstrip('/') + '/api/approvals/' + approval_id
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + os.environ['PAPERCLIP_API_KEY']})
    with urllib.request.urlopen(req, timeout=15) as response:
        approval = json.load(response)
    binding = {'candidate': sha, 'action': action, 'manifest_hash': old.digest(manifest)}
    if (approval.get('status') != 'approved' or approval.get('type') != 'request_board_approval'
            or approval.get('companyId') != os.environ['PAPERCLIP_COMPANY_ID']
            or approval.get('payload', {}).get('legacy_correction') != binding):
        raise GuardError('Approval not bound to this execution')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', type=Path, required=True)
    p.add_argument('--action', choices=['inspect', 'apply', 'rollback'], default='inspect')
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--backup', type=Path)
    p.add_argument('--board-approval-id')
    a = p.parse_args()
    c = None
    try:
        path = a.db.resolve(strict=True)
        if a.action == 'inspect':
            c = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
            c.execute('PRAGMA query_only=ON'); c.execute('BEGIN')
            m = inspect(c, path)
            fd = os.open(a.manifest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'w') as out:
                json.dump(m, out); out.flush(); os.fsync(out.fileno())
            sync_parent(a.manifest)
            print(json.dumps({'count': m['count'], 'unsorted': m['unsorted'], 'manifest_hash': old.digest(m)}))
        else:
            if not a.backup or not a.board_approval_id:
                raise GuardError('Approval and backup required')
            m = json.loads(a.manifest.read_text())
            approve(a.board_approval_id, a.action, m)
            c = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=5)
            (execute if a.action == 'apply' else restore)(c, path, m, a.backup)
            print(json.dumps({'unsorted': old.aggregates(c)}))
    except Exception:
        p.exit(1, 'Guard/IO/approval failure; aborted. Diagnose privately; never relax guards.\n')
    finally:
        if c is not None:
            c.close()


if __name__ == '__main__':
    main()
