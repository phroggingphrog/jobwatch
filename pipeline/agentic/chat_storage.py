"""Local SQLite LangGraph persistence. One private database per Jobwatch person.

No pickle, hosted store, embeddings, network transport or candidate payload logs.
The synchronous dispatcher owns the connection; graph worker access is serialized.
"""
from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, UTC

from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple, WRITES_IDX_MAP
from langgraph.store.base import BaseStore, GetOp, PutOp, SearchOp, ListNamespacesOp, Item, SearchItem


class ChatSaver(BaseCheckpointSaver):
    def __init__(self, conn, lock):
        super().__init__()
        self.conn, self.lock = conn, lock
        with lock:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS chat_checkpoints (
                    thread TEXT, ns TEXT, id TEXT, parent TEXT, type TEXT, payload BLOB,
                    metadata TEXT, PRIMARY KEY(thread,ns,id));
                CREATE TABLE IF NOT EXISTS chat_writes (
                    thread TEXT, ns TEXT, id TEXT, task TEXT, idx INTEGER,
                    channel TEXT, type TEXT, payload BLOB, PRIMARY KEY(thread,ns,id,task,idx));
            """)

    def get_tuple(self, config):
        c = config['configurable']
        thread, ns = c['thread_id'], c.get('checkpoint_ns', '')
        with self.lock:
            row = self.conn.execute(
                'SELECT id,parent,type,payload,metadata FROM chat_checkpoints WHERE thread=? AND ns=? ' +
                ('AND id=?' if c.get('checkpoint_id') else 'ORDER BY id DESC LIMIT 1'),
                (thread, ns, c['checkpoint_id']) if c.get('checkpoint_id') else (thread, ns)).fetchone()
            if not row:
                return None
            ident, parent, kind, payload, metadata = row
            writes = self.conn.execute('SELECT task,channel,type,payload FROM chat_writes '
                'WHERE thread=? AND ns=? AND id=? ORDER BY task,idx', (thread, ns, ident)).fetchall()
        def cfg(ident):
            return {'configurable': {'thread_id': thread, 'checkpoint_ns': ns, 'checkpoint_id': ident}}
        return CheckpointTuple(config=cfg(ident), checkpoint=self.serde.loads_typed((kind, payload)),
            metadata=json.loads(metadata), parent_config=cfg(parent) if parent else None,
            pending_writes=[(task, channel, self.serde.loads_typed((typ, data)))
                            for task, channel, typ, data in writes])

    def put(self, config, checkpoint, metadata, new_versions):
        c = config['configurable']
        kind, payload = self.serde.dumps_typed(checkpoint)
        metadata = dict(metadata)
        if c.get('invocation_id'):
            metadata['invocation_id'] = c['invocation_id']
        with self.lock, self.conn:
            self.conn.execute('INSERT OR REPLACE INTO chat_checkpoints VALUES(?,?,?,?,?,?,?)',
                (c['thread_id'], c.get('checkpoint_ns', ''), checkpoint['id'], c.get('checkpoint_id'),
                 kind, payload, json.dumps(metadata)))
        return {'configurable': {'thread_id': c['thread_id'], 'checkpoint_ns': c.get('checkpoint_ns', ''),
                                 'checkpoint_id': checkpoint['id']}}

    def put_writes(self, config, writes, task_id, task_path=''):
        c = config['configurable']
        with self.lock, self.conn:
            for i, (channel, value) in enumerate(writes):
                idx = WRITES_IDX_MAP.get(channel, i)
                kind, payload = self.serde.dumps_typed(value)
                verb = 'REPLACE' if idx < 0 else 'IGNORE'
                self.conn.execute(f'INSERT OR {verb} INTO chat_writes VALUES(?,?,?,?,?,?,?,?)',
                    (c['thread_id'], c.get('checkpoint_ns', ''), c['checkpoint_id'], task_id, idx,
                     channel, kind, payload))

    def list(self, config, *, filter=None, before=None, limit=None):
        with self.lock:
            rows = self.conn.execute('SELECT thread,ns,id FROM chat_checkpoints ORDER BY id DESC').fetchall()
        for thread, ns, ident in rows:
            c = (config or {}).get('configurable', {})
            if c and (thread != c['thread_id'] or ('checkpoint_ns' in c and ns != c['checkpoint_ns'])
                      or (c.get('checkpoint_id') and ident != c['checkpoint_id'])):
                continue
            if before and ident >= before['configurable']['checkpoint_id']:
                continue
            item = self.get_tuple({'configurable': {'thread_id': thread, 'checkpoint_ns': ns, 'checkpoint_id': ident}})
            if filter and any(item.metadata.get(k) != v for k, v in filter.items()):
                continue
            if limit is not None:
                if limit <= 0:
                    break
                limit -= 1
            yield item


class ChatStore(BaseStore):
    """JSON key/value store; no semantic search or arbitrary namespace discovery."""
    def __init__(self, conn, lock):
        self.conn, self.lock = conn, lock
        with lock:
            conn.execute('CREATE TABLE IF NOT EXISTS chat_memory '
                         '(namespace TEXT,key TEXT,value TEXT,created TEXT,updated TEXT,PRIMARY KEY(namespace,key))')
            conn.commit()

    def batch(self, ops):
        results = []
        with self.lock, self.conn:
            for op in ops:
                if isinstance(op, PutOp):
                    ns = json.dumps(op.namespace)
                    if op.value is None:
                        self.conn.execute('DELETE FROM chat_memory WHERE namespace=? AND key=?', (ns, op.key))
                    else:
                        now = datetime.now(UTC).isoformat()
                        self.conn.execute('INSERT INTO chat_memory VALUES(?,?,?,?,?) ON CONFLICT(namespace,key) '
                            'DO UPDATE SET value=excluded.value,updated=excluded.updated',
                            (ns, op.key, json.dumps(op.value), now, now))
                    results.append(None)
                elif isinstance(op, (GetOp, SearchOp)):
                    rows = self.conn.execute('SELECT namespace,key,value,created,updated FROM chat_memory').fetchall()
                    items = []
                    for ns, key, raw, created, updated in rows:
                        namespace, value = tuple(json.loads(ns)), json.loads(raw)
                        if isinstance(op, GetOp):
                            match = namespace == op.namespace and key == op.key
                        else:
                            if op.query:
                                raise ValueError('semantic_search_not_supported')
                            match = namespace[:len(op.namespace_prefix)] == op.namespace_prefix
                            match = match and all(value.get(k) == v for k, v in (op.filter or {}).items())
                        if match:
                            cls = Item if isinstance(op, GetOp) else SearchItem
                            items.append(cls(namespace=namespace, key=key, value=value,
                                created_at=datetime.fromisoformat(created), updated_at=datetime.fromisoformat(updated)))
                    results.append((items[0] if items else None) if isinstance(op, GetOp)
                                   else items[op.offset:op.offset + op.limit])
                elif isinstance(op, ListNamespacesOp):
                    raise ValueError('namespace_listing_not_supported')
                else:
                    raise ValueError('store_operation_not_supported')
        return results

    async def abatch(self, ops):
        return self.batch(ops)
