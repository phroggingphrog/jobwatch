"""On-demand local fitting; never starts a timer or calls an external model."""
import json
import sqlite3
from pathlib import Path
from jobwatch.config import load_config
from jobwatch import preference_service as service
from jobwatch.preferences import PreferenceStore, fit_store


def register(sub):
    parser = sub.add_parser('preferences', help='local owner preference learning')
    parser.add_argument('action', choices=['status', 'fit', 'migrate'])
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--confirm-owner', action='store_true', help='explicitly copy unchanged historical owner choices')


def handle(args):
    if getattr(args, 'cmd', None) != 'preferences':
        return None
    if args.action == 'migrate' and not getattr(args, 'confirm_owner', False):
        print(json.dumps({'error':'confirm_owner_required'}))
        return 2
    cfg = load_config(args.config_dir)
    conn = None
    try:
        conn = sqlite3.connect(f'file:{cfg.db_path}?mode=rw' if args.action in ('fit', 'migrate') else f'file:{cfg.db_path}?mode=ro', uri=True)
        if args.action == 'migrate':
            from jobwatch.preferences.migration import refeaturise
            print(json.dumps(refeaturise(conn, cfg, actor='owner')))
            return 0
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
        if conn is not None:
            conn.close()
