"""Private, resumable vector caches and paid discovery accounting."""
from __future__ import annotations

import hashlib
import math
import os
import re
import stat
import time
import uuid
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import numpy as np

from jobwatch import db, users
from jobwatch.apply.paths import safe_write_bytes
from pipeline.agentic.gateway import PaidGatewayEmbeddings
from pipeline.agentic.runtime import BatchBudget, JobBudget, RuntimeErrorSafe

from . import DiscoveryError


def text_key(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def normalise(vectors) -> np.ndarray:
    try:
        values = np.asarray(vectors, dtype=np.float32)
        if values.ndim != 2 or not values.shape[0] or not values.shape[1] or not np.isfinite(values).all():
            raise ValueError
        # Float64 norms avoid overflow of otherwise finite float32 vectors.
        norms = np.linalg.norm(values.astype(np.float64), axis=1)
        if np.any(norms <= 0) or not np.isfinite(norms).all():
            raise ValueError
        return (values / norms[:, None]).astype(np.float32)
    except (ValueError, TypeError, OverflowError):
        raise DiscoveryError('invalid_vector') from None


def _vector(blob, dims=None):
    if not blob or len(blob) % 4 or (dims is not None and (type(dims) is not int or dims <= 0 or len(blob) != dims * 4)):
        raise DiscoveryError('invalid_vector')
    return normalise([np.frombuffer(blob, dtype='<f4')])[0]


class VectorCache:
    def __init__(self, conn, model):
        self.conn, self.model = conn, model

    def get_many(self, keys):
        result = {}
        for key in dict.fromkeys(keys):
            row = self.conn.execute('SELECT dims, vector FROM text_embeddings WHERE key=? AND model=?',
                                    (key, self.model)).fetchone()
            if row is not None:
                result[key] = _vector(row[1], row[0])
        _consistent(result)
        return result

    def put_many(self, items):
        prepared = {key: normalise([value])[0] for key, value in items.items()}
        _consistent(prepared)
        for key, value in prepared.items():
            self.conn.execute('INSERT INTO text_embeddings(key, model, dims, vector, created_at) VALUES(?,?,?,?,?) '
                              'ON CONFLICT(key, model) DO UPDATE SET dims=excluded.dims, vector=excluded.vector, created_at=excluded.created_at',
                              (key, self.model, len(value), value.astype('<f4').tobytes(), db.ts()))
        self.conn.commit()

    def prune(self, days):
        if type(days) is not int or days < 0:
            raise DiscoveryError('invalid_configuration')
        cursor = self.conn.execute('DELETE FROM text_embeddings WHERE model=? AND created_at<?',
                                   (self.model, db.ts(db.now_utc() - timedelta(days=days))))
        self.conn.commit()
        return cursor.rowcount


def _consistent(items):
    if len({len(v) for v in items.values()}) > 1:
        raise DiscoveryError('invalid_vector')


def _read_vector(path):
    """Bounded binary read, refusing symlinks in every path component."""
    parts = Path(os.path.abspath(path)).parts[1:]
    parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in parts[:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 4_000_000:
            raise DiscoveryError('invalid_vector')
        blob = stream.read(4_000_001)
        if len(blob) > 4_000_000:
            raise DiscoveryError('invalid_vector')
        return blob


class VectorStore:
    def __init__(self, root: Path, model: str):
        self.root, self.model = Path(root), model
        slug = re.sub(r'[^A-Za-z0-9._-]+', '-', model).strip('-')[:70] or 'model'
        self.folder = self.root / f'{slug}-{text_key(model)[:16]}'

    def _path(self, key):
        digest = key if re.fullmatch('[0-9a-f]{64}', key) else text_key(key)
        return self.folder / digest[:2] / f'{digest}.f32'

    def get_many(self, keys):
        result = {}
        for key in dict.fromkeys(keys):
            try:
                blob = _read_vector(self._path(key))
            except FileNotFoundError:
                continue
            result[key] = _vector(blob)
        _consistent(result)
        return result

    def put_many(self, items):
        prepared = {key: normalise([value])[0] for key, value in items.items()}
        _consistent(prepared)
        for key, value in prepared.items():
            safe_write_bytes(self._path(key), value.astype('<f4').tobytes())


def embed_cached(embedder, cache, texts):
    result = cache.get_many(list(texts))
    missing = [key for key in texts if key not in result]
    for offset in range(0, len(missing), 32):
        keys = missing[offset:offset + 32]
        vectors = embedder.embed_documents([texts[key] for key in keys])
        if len(vectors) != len(keys):
            raise DiscoveryError('invalid_vector')
        values = normalise(vectors)
        fresh = dict(zip(keys, values))
        _consistent({**result, **fresh})
        cache.put_many(fresh)
        result.update(fresh)
    return result


def reference_store(model=None, *, config=None):
    from .datasets import reference_root
    if model is None:
        from jobwatch.config import load_config
        from pipeline.agentic.service import _config
        model = _config(config if config is not None else load_config())['embedding_model']
    if not model:
        raise DiscoveryError('embedding_not_configured')
    return VectorStore(reference_root() / 'vectors', model)


def make_embedder(llm, config, budget):
    from pipeline.agentic.service import _config
    model = _config(config)['embedding_model']
    if model is None:
        raise DiscoveryError('embedding_not_configured')
    return PaidGatewayEmbeddings(llm, model, budget)


def discovery_tokens_since(conn, start):
    # Older read-only databases remain readable; schema creation belongs to migrations.
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='discovery_spend'").fetchone():
        return 0
    return conn.execute('SELECT COALESCE(SUM(charged_tokens),0) FROM discovery_spend WHERE at>=?', (start,)).fetchone()[0]


def _daily_spent(conn, start):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if {'agentic_batches', 'agentic_activity'} <= tables:
        from pipeline.agentic.service import _spent_today
        return _spent_today(conn, start)[1]
    return discovery_tokens_since(conn, start)


@contextmanager
def discovery_budget(conn, purpose: str, *, token_ceiling: int, seconds: float = 300.0):
    from jobwatch.candidate import intake
    from pipeline.agentic import execution
    if (type(token_ceiling) is not int or token_ceiling <= 0 or type(seconds) not in (int, float)
            or not math.isfinite(seconds) or seconds <= 0):
        raise DiscoveryError('invalid_configuration')
    invocation = execution.current()
    if invocation is not None:
        invocation.check()
        seconds = min(seconds, invocation.deadline - time.monotonic())
    scope = intake.discovery_scope(users.current())
    start, daily_limit = None, None
    if scope is not None:
        from pipeline.agentic.service import _local_midnight
        start, daily_limit = _local_midnight(time.time()), scope.daily_token_ceiling
        room = daily_limit - _daily_spent(conn, start)
        if room <= 0:
            raise DiscoveryError('daily_budget')
        token_ceiling = min(token_ceiling, room)
    now = time.time()
    row_id = conn.execute('INSERT INTO discovery_spend(at,purpose,charged_tokens) VALUES(?,?,0)', (now, purpose)).lastrowid
    conn.commit()
    batch = BatchBudget('discovery-' + uuid.uuid4().hex, token_ceiling=token_ceiling, deadline=now + seconds)
    recorded = 0

    def persist(checkpoint, **_):
        nonlocal recorded
        # A write lock makes concurrent discovery reservations see each other's charge.
        conn.execute('SAVEPOINT discovery_charge')
        try:
            conn.execute('UPDATE discovery_spend SET charged_tokens=charged_tokens WHERE id=?', (row_id,))
            at = time.time()
            day_start = _local_midnight(at) if daily_limit is not None else None
            prior_at = conn.execute('SELECT at FROM discovery_spend WHERE id=?', (row_id,)).fetchone()[0]
            delta = checkpoint.job_charged - recorded if day_start is None or prior_at >= day_start else checkpoint.job_charged
            if daily_limit is not None and delta > 0 and _daily_spent(conn, day_start) + delta > daily_limit:
                raise RuntimeErrorSafe('daily_budget')
            conn.execute('UPDATE discovery_spend SET charged_tokens=?, at=? WHERE id=?', (checkpoint.job_charged, at, row_id))
            conn.execute('RELEASE SAVEPOINT discovery_charge')
            recorded = checkpoint.job_charged
        except BaseException:
            conn.execute('ROLLBACK TO SAVEPOINT discovery_charge')
            conn.execute('RELEASE SAVEPOINT discovery_charge')
            raise

    budget = JobBudget(text_key(purpose + uuid.uuid4().hex), batch, token_ceiling=token_ceiling,
                       deadline=now + seconds, persist=persist)
    try:
        yield budget
    finally:
        try:
            conn.execute('UPDATE discovery_spend SET charged_tokens=?, at=? WHERE id=?', (budget.charged_tokens, time.time(), row_id))
            conn.commit()
        finally:
            batch.release(budget)
