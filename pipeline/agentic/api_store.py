"""Private, transactional native API state beside LangGraph checkpoints."""
from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
import time
import uuid

from jobwatch import users
from jobwatch.apply.paths import ensure_dir
from pipeline.agentic.private_sqlite import connect as private_connect


class Conflict(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


class APIStore:
    def __init__(self, person):
        if not users.valid_name(person):
            raise ValueError('invalid_person')
        root = ensure_dir(users.user_dir(person) / 'career-chat')
        path = root / 'state.sqlite'
        self.conn = private_connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS api_meta(version INTEGER PRIMARY KEY);
            INSERT OR IGNORE INTO api_meta VALUES(1);
            CREATE TABLE IF NOT EXISTS api_threads(
                id TEXT PRIMARY KEY, created REAL NOT NULL, skill_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS api_runs(
                id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES api_threads(id),
                state TEXT NOT NULL, request_key TEXT UNIQUE NOT NULL, input_hash TEXT NOT NULL,
                input_json TEXT NOT NULL, result_json TEXT, error TEXT,
                created REAL NOT NULL, updated REAL NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS api_runs_thread ON api_runs(thread_id,created);
            CREATE TABLE IF NOT EXISTS api_interactions(
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES api_runs(id), position INTEGER NOT NULL,
                payload TEXT NOT NULL, response TEXT, expires REAL NOT NULL, resume_run TEXT);
            CREATE TABLE IF NOT EXISTS api_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES api_runs(id),
                created REAL NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS api_events_run ON api_events(run_id,id);
            CREATE TABLE IF NOT EXISTS api_artifacts(
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES api_runs(id),
                kind TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL,
                UNIQUE(run_id,kind,path));
        ''')
        if self.conn.execute('SELECT MAX(version) FROM api_meta').fetchone()[0] != 1:
            self.close()
            raise Conflict('unsupported_state_version')

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @contextlib.contextmanager
    def transaction(self):
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def thread(self, ident):
        row = self.conn.execute('SELECT * FROM api_threads WHERE id=?', (ident,)).fetchone()
        if row is None:
            raise KeyError('thread_not_found')
        return dict(row)

    def create_thread(self, skill_hash):
        ident = uuid.uuid4().hex
        with self.conn:
            self.conn.execute('INSERT INTO api_threads VALUES(?,?,?)', (ident, time.time(), skill_hash))
        return self.thread(ident)

    def raw_run(self, ident):
        row = self.conn.execute('SELECT * FROM api_runs WHERE id=?', (ident,)).fetchone()
        if row is None:
            raise KeyError('run_not_found')
        return dict(row)

    def event(self, ident, kind, data=None):
        # Callers supply fixed metadata only. Messages and interaction text belong
        # in private state, never the diagnostics stream.
        self.conn.execute('INSERT INTO api_events(run_id,created,kind,data) VALUES(?,?,?,?)',
                          (ident, time.time(), kind, encoded(data or {})))

    def emit(self, ident, kind, data):
        with self.conn:
            self.event(ident, kind, data)

    def enqueue(self, thread_id, payload, key):
        self.thread(thread_id)
        digest, request_key = fingerprint(payload), fingerprint([thread_id, key])
        with self.transaction():
            previous = self.conn.execute('SELECT id,input_hash FROM api_runs WHERE request_key=?',
                                         (request_key,)).fetchone()
            if previous:
                if previous['input_hash'] != digest:
                    raise Conflict('idempotency_conflict')
                return previous['id']
            active = self.conn.execute("SELECT 1 FROM api_runs WHERE thread_id=? AND state IN "
                "('queued','running','waiting_for_input','waiting_for_approval','interrupted')", (thread_id,)).fetchone()
            if active:
                raise Conflict('thread_busy')
            if self.conn.execute("SELECT COUNT(*) FROM api_runs WHERE state='queued'").fetchone()[0] >= 20:
                raise Conflict('queue_full')
            return self._insert(thread_id, payload, request_key)

    def _insert(self, thread, payload, request_key):
        ident, now = uuid.uuid4().hex, time.time()
        self.conn.execute('INSERT INTO api_runs(id,thread_id,state,request_key,input_hash,input_json,created,updated) '
                          "VALUES(?,?,'queued',?,?,?,?,?)",
                          (ident, thread, request_key, fingerprint(payload), encoded(payload), now, now))
        self.event(ident, 'queued')
        return ident

    def enqueue_selection(self, selection_id, payload, skill_hash):
        """A person-scoped identity independent of newly-created thread IDs."""
        key = fingerprint(['selection', selection_id])
        with self.transaction():
            previous = self.conn.execute('SELECT id,input_hash FROM api_runs WHERE request_key=?',(key,)).fetchone()
            if previous:
                if previous['input_hash'] != fingerprint(payload):
                    raise Conflict('idempotency_conflict')
                return previous['id']
            if self.conn.execute("SELECT COUNT(*) FROM api_runs WHERE state='queued'").fetchone()[0] >= 20:
                raise Conflict('queue_full')
            thread = uuid.uuid4().hex
            self.conn.execute('INSERT INTO api_threads VALUES(?,?,?)',(thread,time.time(),skill_hash))
            return self._insert(thread,payload,key)

    def public_run(self, ident):
        row = self.raw_run(ident)
        result = {k: row[k] for k in ('id', 'thread_id', 'state', 'error', 'created', 'updated')}
        result['schema_version'] = 1
        result['result'] = json.loads(row['result_json']) if row['result_json'] else None
        result['interactions'] = [dict(id=r['id'], expires_at=r['expires'],
            answered=r['response'] is not None, **json.loads(r['payload'])) for r in self.conn.execute(
            'SELECT * FROM api_interactions WHERE run_id=? ORDER BY position', (ident,))]
        result['artifacts'] = [dict(id=r['id'], kind=r['kind'], url='/api/agent/artifacts/' + r['id'])
            for r in self.conn.execute('SELECT id,kind FROM api_artifacts WHERE run_id=?', (ident,))]
        return result

    def events(self, ident, after=0):
        self.raw_run(ident)
        return [dict(id=r['id'], run_id=ident, created=r['created'], type=r['kind'], data=json.loads(r['data']))
            for r in self.conn.execute('SELECT * FROM api_events WHERE run_id=? AND id>? ORDER BY id LIMIT 100',
                                       (ident, after))]

    def claim_next(self):
        with self.transaction():
            row = self.conn.execute("SELECT * FROM api_runs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if row is None:
                return None
            self.conn.execute("UPDATE api_runs SET state='running',updated=? WHERE id=?", (time.time(), row['id']))
            self.event(row['id'], 'running')
            return dict(row)

    def recover(self):
        # A process-wide file lock is held before this method. Do not silently
        # repeat an uncertain paid model request after a process crash.
        with self.transaction():
            rows = self.conn.execute("SELECT id FROM api_runs WHERE state='running'").fetchall()
            for row in rows:
                self.conn.execute("UPDATE api_runs SET state='interrupted',error='worker_interrupted',updated=? WHERE id=?",
                                  (time.time(), row['id']))
                self.event(row['id'], 'interrupted', {'reason': 'worker_interrupted'})

    def usage_checkpoint(self, ident):
        rows = self.conn.execute("SELECT kind,data FROM api_events WHERE run_id=? AND kind IN "
                                 "('model_started','model_finished') ORDER BY id", (ident,)).fetchall()
        calls, charged, actual, known = 0, 0, 0, 0
        for row in rows:
            value = json.loads(row['data'])
            if row['kind'] == 'model_started':
                calls += 1
                charged += value['reserved_tokens']
            elif value['actual_tokens'] is not None:
                known += 1
                actual += value['actual_tokens']
                charged += value['actual_tokens'] - value['reserved_tokens']
        return dict(calls=calls, charged_tokens=charged, actual_tokens=actual, unknown_usage_calls=calls-known)

    def finish(self, ident, result=None, error=None):
        with self.transaction():
            row = self.raw_run(ident)
            interactions = (result or {}).get('interactions', [])
            state = ('cancelled' if error == 'cancelled' else 'interrupted' if error == 'worker_interrupted' else
                     'deferred' if error == 'person_busy' else 'failed') if error else 'completed'
            if interactions and not error:
                if len(interactions) > 8 or any(x['type'] not in ('question', 'approval') for x in interactions):
                    raise Conflict('unsupported_interaction')
                state = 'waiting_for_approval' if any(x['type'] == 'approval' for x in interactions) else 'waiting_for_input'
                for index, item in enumerate(interactions):
                    self.conn.execute('INSERT INTO api_interactions(id,run_id,position,payload,expires) VALUES(?,?,?,?,?)',
                                      (uuid.uuid4().hex, ident, index, encoded(item), time.time() + 86400))
            self.conn.execute('UPDATE api_runs SET state=?,result_json=?,error=?,updated=? WHERE id=?',
                              (state, encoded(result) if result else None, error, time.time(), ident))
            self.event(ident, state, {'reason': error} if error else {})

    def respond(self, interaction_id, response, *, message=None):
        with self.transaction():
            row = self.conn.execute('SELECT * FROM api_interactions WHERE id=?', (interaction_id,)).fetchone()
            if row is None:
                raise KeyError('interaction_not_found')
            if row['response'] is not None:
                if encoded(response) != row['response']:
                    raise Conflict('interaction_consumed')
                return row['resume_run'], json.loads(row['payload'])
            run = self.raw_run(row['run_id'])
            item = json.loads(row['payload'])
            rejecting = item['type'] == 'approval' and response.get('decision') == 'reject'
            if run['state'] not in ('waiting_for_input', 'waiting_for_approval') or (row['expires'] <= time.time() and not rejecting):
                raise Conflict('interaction_expired')
            if item['type'] == 'approval':
                if response['decision'] not in ('approve', 'reject') or response.get('answer') is not None:
                    raise Conflict('invalid_approval')
                decision = {'type': response['decision']}
            else:
                if response['decision'] not in ('answer', 'decline'):
                    raise Conflict('invalid_answer')
                answer = response.get('answer')
                if response['decision'] == 'answer' and (not isinstance(answer, str) or not answer.strip()):
                    raise Conflict('answer_required')
                decision = {'type': 'respond', 'message': answer if response['decision'] == 'answer' else
                            'The human declined to answer. Do not infer missing facts.'}
            self.conn.execute('UPDATE api_interactions SET response=? WHERE id=?', (encoded(response), interaction_id))
            rows = self.conn.execute('SELECT * FROM api_interactions WHERE run_id=? ORDER BY position', (row['run_id'],)).fetchall()
            resume = None
            if all(r['response'] is not None for r in rows):
                # Declining an expired approval grants no authority and lets an
                # authenticated conversation recover. Expired approvals/answers
                # that would authorise work still fail closed.
                if any(r['expires'] <= time.time() and json.loads(r['response']).get('decision') != 'reject' for r in rows):
                    raise Conflict('interaction_expired')
                decisions = []
                for r in rows:
                    supplied = json.loads(r['response'])
                    kind = json.loads(r['payload'])['type']
                    decisions.append({'type': supplied['decision']} if kind == 'approval' else
                        {'type': 'respond', 'message': supplied.get('answer') if supplied['decision'] == 'answer' else
                         'The human declined to answer. Do not infer missing facts.'})
                self.conn.execute("UPDATE api_runs SET state='resumed',updated=? WHERE id=?", (time.time(), row['run_id']))
                previous = json.loads(run['result_json'])
                payload = {'decisions': decisions, 'expected_checkpoint': previous.get('checkpoint_id'),
                           'approval_bindings': [json.loads(r['payload']).get('binding') for r in rows]}
                if message is not None:
                    payload['message'] = message
                resume = self._insert(run['thread_id'], payload, fingerprint(['resume', row['run_id']]))
                self.conn.execute('UPDATE api_interactions SET resume_run=? WHERE run_id=?', (resume, row['run_id']))
            self.event(row['run_id'], 'interaction_answered', {'interaction_id': interaction_id})
            return resume, item

    def cancel(self, ident):
        with self.transaction():
            row = self.raw_run(ident)
            if row['state'] in ('queued', 'waiting_for_input', 'waiting_for_approval', 'interrupted'):
                self.conn.execute("UPDATE api_runs SET state='cancelled',cancel_requested=1,updated=? WHERE id=?",
                                  (time.time(), ident))
            elif row['state'] == 'running':
                self.conn.execute('UPDATE api_runs SET cancel_requested=1,updated=? WHERE id=?', (time.time(), ident))
            self.event(ident, 'cancellation_requested')

    def retry(self, ident):
        with self.transaction():
            row = self.raw_run(ident)
            if row['state'] not in ('interrupted', 'deferred'):
                raise Conflict('run_not_interrupted')
            if self.conn.execute("SELECT 1 FROM api_runs WHERE thread_id=? AND id<>? AND state IN "
                "('queued','running','waiting_for_input','waiting_for_approval','interrupted')",
                (row['thread_id'], ident)).fetchone():
                raise Conflict('thread_busy')
            if self.conn.execute("SELECT COUNT(*) FROM api_runs WHERE state='queued'").fetchone()[0] >= 20:
                raise Conflict('queue_full')
            payload = json.loads(row['input_json'])
            if 'decisions' in payload and self.conn.execute('SELECT 1 FROM api_interactions WHERE resume_run=? AND expires<=?',
                                                            (ident, time.time())).fetchone():
                raise Conflict('interaction_expired')  # same 24h rule as respond(): a stale approval never authorizes work
            # Lock contention occurs before graph execution. Retry that original
            # request normally; only an interrupted worker needs checkpoint recovery.
            if row['state'] == 'interrupted':
                payload['recover'] = True
            self.conn.execute("UPDATE api_runs SET state='queued',error=NULL,cancel_requested=0,input_json=?,updated=? WHERE id=?",
                              (encoded(payload), time.time(), ident))
            self.event(ident, 'recovery_requested')
