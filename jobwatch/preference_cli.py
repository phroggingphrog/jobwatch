"""On-demand local fitting; never starts a timer or calls an external model."""
import json
import sqlite3
from pathlib import Path
from jobwatch.config import load_config
from jobwatch import preference_service as service
from jobwatch.preferences import PreferenceStore, fit_store


def register(sub):
    parser = sub.add_parser('preferences', help='local owner preference learning')
    parser.add_argument('action', choices=['status', 'fit'])
    parser.add_argument('--output-dir', type=Path)


def handle(args):
    if getattr(args, 'cmd', None) != 'preferences':
        return None
    cfg = load_config(args.config_dir)
    conn = sqlite3.connect(f'file:{cfg.db_path}?mode=rw' if args.action == 'fit' else f'file:{cfg.db_path}?mode=ro', uri=True)
    try:
        identity, _ = service.pool(conn, cfg)
        store = PreferenceStore(conn)
        if args.action == 'fit':
            if args.output_dir is None:
                print(json.dumps({'error':'output_dir_required'}))
                return 2
            result = fit_store(store, args.output_dir, identity)
            print(json.dumps({'accepted':result['gate']['accepted'], 'reasons':result['gate'].get('reasons', [])}))
        else:
            status = store.status(identity)
            print(json.dumps({k:v for k,v in status.items() if k != 'fit'}))
        return 0
    except (ValueError, OSError, sqlite3.DatabaseError):
        print(json.dumps({'error':'preference_operation_unavailable'}))
        return 1
    finally:
        conn.close()
