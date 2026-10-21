"""Read-only snapshot inventory and explicitly enabled bounded batch execution."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from jobwatch.config import load_config
from jobwatch import db
from pipeline.agentic.contracts import AgenticError
from pipeline.agentic.service import agentic_batch_run, enabled, snapshot_inventory


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Agentic career-ops runner (never submits applications)')
    parser.add_argument('--config-dir')
    parser.add_argument('--db', type=Path)
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--posting-id', type=int, action='append', dest='posting_ids')
    parser.add_argument('--dry-run', action='store_true', help='Read-only inventory; no models, writes or fetching')
    parser.add_argument('--snapshot', type=Path, help='Save read-only inventory with --dry-run, or verify before execution')
    parser.add_argument('--batch-id', help='Resume a durable batch identity')
    args = parser.parse_args(argv)
    config = load_config(args.config_dir)
    db_path = (args.db or config.db_path).expanduser().resolve()
    conn = None
    error = None
    result = None
    try:
        if args.dry_run:
            conn = sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True)
            conn.row_factory = sqlite3.Row
        else:
            if not enabled(config):
                raise AgenticError('agentic_disabled')
            from jobwatch import discovery_gate
            if not discovery_gate.allowed('agentic'):
                print(json.dumps({'skipped': discovery_gate.SKIPPED}))
                return 0
            conn = db.connect(db_path)
        inventory = snapshot_inventory(conn, config, posting_ids=args.posting_ids, limit=args.limit)
        payload = {'schema_version': 1, 'postings': inventory}
        if args.dry_run:
            if args.snapshot:
                from jobwatch.apply.paths import safe_write_text
                safe_write_text(args.snapshot, json.dumps(payload, indent=2))
            result = {'mode': 'inventory', **payload}
        else:
            if args.snapshot:
                expected = json.loads(args.snapshot.read_text())
                selected = [row['posting_id'] for row in expected['postings']]
                inventory = snapshot_inventory(conn, config, posting_ids=selected, limit=args.limit)
                if expected != {'schema_version': 1, 'postings': inventory}:
                    raise AgenticError('snapshot_changed')
            result = agentic_batch_run([row['posting_id'] for row in inventory], config, conn, batch_id=args.batch_id,
                                      expected_run_keys={row['posting_id']: row['run_key'] for row in inventory})
    except Exception as exc:
        error = exc.code if isinstance(exc, AgenticError) else 'execution_unavailable'
    finally:
        if conn is not None:
            conn.close()
    print(json.dumps({'error': error} if error else result, sort_keys=True))
    return 1 if error else 0


if __name__ == '__main__':
    raise SystemExit(main())
