"""Append-only owner labels. Construction and all GET-side methods never migrate/write."""
from __future__ import annotations
import json
import sqlite3
import uuid
from datetime import datetime, UTC
from .features import PreferenceError, canonical, digest, validate_alternatives, versions

MIN_TRAIN = 20
MIN_HOLDOUT = 5

def now():
    return datetime.now(UTC).isoformat()

class PreferenceStore:
    def __init__(self, conn: sqlite3.Connection, *, origin='owner'):
        if origin not in ('owner','synthetic'):
            raise PreferenceError('invalid_origin')
        self.conn = conn
        self.origin = origin

    def ensure(self):
        if self.conn.in_transaction:
            raise PreferenceError('transaction_active')
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.executescript('''
        CREATE TABLE IF NOT EXISTS preference_sets (
          id TEXT PRIMARY KEY, context_hash TEXT NOT NULL, created_at TEXT NOT NULL,
          holdout INTEGER NOT NULL CHECK(holdout IN (0,1)), payload TEXT NOT NULL,
          payload_hash TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS preference_picks (
          set_id TEXT PRIMARY KEY REFERENCES preference_sets(id), selected INTEGER,
          request_id TEXT UNIQUE NOT NULL, actor TEXT NOT NULL CHECK(actor='owner'), created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS preference_fits (
          id TEXT PRIMARY KEY, context_hash TEXT NOT NULL, dataset_hash TEXT NOT NULL,
          created_at TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TRIGGER IF NOT EXISTS preference_sets_no_update BEFORE UPDATE ON preference_sets
          BEGIN SELECT RAISE(ABORT,'immutable'); END;
        CREATE TRIGGER IF NOT EXISTS preference_sets_no_delete BEFORE DELETE ON preference_sets
          BEGIN SELECT RAISE(ABORT,'immutable'); END;
        CREATE TRIGGER IF NOT EXISTS preference_picks_no_update BEFORE UPDATE ON preference_picks
          BEGIN SELECT RAISE(ABORT,'immutable'); END;
        CREATE TRIGGER IF NOT EXISTS preference_picks_no_delete BEFORE DELETE ON preference_picks
          BEGIN SELECT RAISE(ABORT,'immutable'); END;
        CREATE TRIGGER IF NOT EXISTS preference_fits_no_update BEFORE UPDATE ON preference_fits
          BEGIN SELECT RAISE(ABORT,'immutable'); END;
        CREATE TRIGGER IF NOT EXISTS preference_fits_no_delete BEFORE DELETE ON preference_fits
          BEGIN SELECT RAISE(ABORT,'immutable'); END;
        ''')

    def exists(self):
        return self.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='preference_sets'").fetchone() is not None

    def list_sets(self, context_hash=None):
        if not self.exists():
            return []
        sql = 'SELECT s.id,s.context_hash,s.created_at,s.holdout,s.payload,s.payload_hash,p.selected,p.created_at FROM preference_sets s LEFT JOIN preference_picks p ON p.set_id=s.id'
        args = ()
        if context_hash is not None:
            sql += ' WHERE s.context_hash=?'
            args = (context_hash,)
        rows = self.conn.execute(sql + ' ORDER BY s.created_at,s.id', args).fetchall()
        result=[]
        for row in rows:
            payload=json.loads(row[4])
            if digest(payload) != row[5]:
                raise PreferenceError('snapshot_corrupt')
            result.append({'id':row[0], 'context_hash':row[1], 'created_at':row[2],
                           'holdout':bool(row[3]), **payload, 'answered':row[7] is not None,
                           'selected':row[6], 'answered_at':row[7]})
        return result

    def get_set(self, set_id):
        return next((s for s in self.list_sets() if s['id']==set_id), None)

    def create_set(self, alternatives, context_hash, *, holdout=None, migrated_from=None):
        alternatives = validate_alternatives(alternatives)
        if type(context_hash) is not str or len(context_hash) != 64 or any(c not in '0123456789abcdef' for c in context_hash):
            raise PreferenceError('invalid_context')
        if holdout is not None and type(holdout) is not bool:
            raise PreferenceError('invalid_holdout')
        if migrated_from is not None and (type(migrated_from) is not str or not migrated_from.strip() or len(migrated_from) > 128):
            raise PreferenceError('invalid_migration_source')
        payload = {'alternatives':alternatives, 'versions':versions(), 'origin':self.origin, 'context_hash':context_hash}
        if migrated_from is not None:
            payload['migrated_from'] = migrated_from
        key = digest(payload)
        self.ensure()
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            if any(s['origin'] != self.origin for s in self.list_sets()):
                raise PreferenceError('mixed_data_origins')
            old = self.conn.execute('SELECT id FROM preference_sets WHERE payload_hash=?',(key,)).fetchone()
            if old:
                set_id = old[0]
                if holdout is not None and self.get_set(set_id)['holdout'] != holdout:
                    raise PreferenceError('split_overlap')
            else:
                set_id = uuid.uuid4().hex
                # Split assigned before the owner answers, never by outcome.
                existing = self.list_sets(context_hash)
                ids = {a['posting_id'] for a in alternatives}
                assigned = {s['holdout'] for s in existing if ids & {a['posting_id'] for a in s['alternatives']}}
                if len(assigned) > 1:
                    raise PreferenceError('split_overlap')
                if assigned and holdout is not None and holdout not in assigned:
                    raise PreferenceError('split_overlap')
                holdout = assigned.pop() if assigned else (len(existing) % 5 == 4 if holdout is None else holdout)
                self.conn.execute('INSERT INTO preference_sets VALUES(?,?,?,?,?,?)',
                                  (set_id,context_hash,now(),int(holdout),canonical(payload),key))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return self.get_set(set_id)

    def pick(self, set_id, selected, *, actor, request_id):
        if actor != 'owner':
            raise PreferenceError('explicit_owner_required')
        if type(request_id) is not str or not 1 <= len(request_id) <= 128 or (selected is not None and type(selected) is not int):
            raise PreferenceError('invalid_pick')
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            choice = self.get_set(set_id)
            if choice is None:
                raise PreferenceError('unknown_set')
            if selected is not None and selected not in {a['posting_id'] for a in choice['alternatives']}:
                raise PreferenceError('invalid_pick')
            prior = self.conn.execute('SELECT set_id,selected,request_id FROM preference_picks WHERE set_id=? OR request_id=?',(set_id,request_id)).fetchall()
            if prior:
                if len(prior)!=1 or tuple(prior[0]) != (set_id,selected,request_id):
                    raise PreferenceError('pick_conflict')
            else:
                if choice['versions'] != versions():
                    raise PreferenceError('stale_set')
                self.conn.execute('INSERT INTO preference_picks VALUES(?,?,?,?,?)',(set_id,selected,request_id,'owner',now()))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return self.get_set(set_id)

    def dataset(self, context_hash):
        return [s for s in self.list_sets(context_hash) if s['answered'] and s['versions']==versions() and s['origin']==self.origin]

    def dataset_hash(self, context_hash):
        return digest(self.dataset(context_hash))

    def latest_fit(self, context_hash):
        if not self.exists():
            return None
        row=self.conn.execute('SELECT payload FROM preference_fits WHERE context_hash=? ORDER BY created_at DESC,id DESC LIMIT 1',(context_hash,)).fetchone()
        return json.loads(row[0]) if row else None

    def status(self, context_hash=None):
        all_rows=self.list_sets()
        rows=[s for s in all_rows if context_hash is None or s['context_hash']==context_hash]
        current=[s for s in rows if s['answered'] and s['versions']==versions() and s['origin']==self.origin]
        n_train=sum(not s['holdout'] for s in current)
        n_holdout=sum(s['holdout'] for s in current)
        historical_choices=sum(s['answered'] and s['origin']==self.origin for s in all_rows)
        stale_choices=historical_choices-len(current)
        status=('stale' if stale_choices else 'no_data') if not current else 'insufficient_data' if n_train<MIN_TRAIN or n_holdout<MIN_HOLDOUT else 'untrained'
        fit=self.latest_fit(context_hash) if context_hash else None
        if fit:
            from .model import evaluate_fit
            status='stale' if fit.get('dataset_hash')!=self.dataset_hash(context_hash) or fit.get('versions')!=versions() else 'valid' if evaluate_fit(fit)['accepted'] else 'rejected'
        if status=='valid' and self.origin=='synthetic':
            status='synthetic_valid'
        return {'origin':self.origin,'status':status,'n_sets':len(rows),'n_choices':len(current),'n_train':n_train,'n_holdout':n_holdout,
                'historical_choices':historical_choices,'stale_choices':stale_choices,
                'minimum_train':MIN_TRAIN,'minimum_holdout':MIN_HOLDOUT,'fit':fit}

    def save_fit(self, summary):
        self.ensure()
        with self.conn:
            self.conn.execute('INSERT INTO preference_fits VALUES(?,?,?,?,?)',
                              (summary['id'],summary['context_hash'],summary['dataset_hash'],now(),canonical(summary)))
