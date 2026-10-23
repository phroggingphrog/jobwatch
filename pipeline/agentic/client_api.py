"""Narrow native operations for the embedded app; ordinary API auth stays unchanged."""
from __future__ import annotations

import hashlib
import asyncio
from contextlib import contextmanager
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from jobwatch import users, model_choice
from jobwatch.apply.paths import ensure_dir
from jobwatch.candidate import intake
from pipeline.agentic.api_store import APIStore
from pipeline.agentic.persistence import _read_artifact
from pipeline.agentic.execution import require_route
from pipeline.agentic.runtime import RuntimeErrorSafe

UPLOAD = '/api/agent/client/upload'
DOWNLOAD = '/api/agent/client/download'

_MODEL_CATALOG = {}


def model_catalog(person, config):
    """List the configured paid gateway, never another credential or provider."""
    from pipeline.agentic.service import configured_llm
    import requests
    try:
        llm = configured_llm(config)
        require_route(llm, model_choice.get_model('chat', person))
        cache_key = (person, llm.base_url, hashlib.sha256(llm._keys[0].encode()).digest())
        cached = _MODEL_CATALOG.get(cache_key)
        if cached and time.monotonic() - cached[0] < 300:
            return cached[1]
        with requests.Session() as session:
            session.trust_env = False
            response = session.get(llm.base_url + '/models', timeout=3, allow_redirects=False,
                headers={'Authorization': 'Bearer ' + llm._keys[0]})
        response.raise_for_status()
        options = []
        for row in response.json()['data']:
            model = row.get('id')
            try:
                require_route(llm, model)
            except RuntimeErrorSafe:
                continue
            options.append({'id': model, 'label': model.split('/', 1)[1].replace('-', ' ').title(),
                            'provider': model.split('/', 1)[0].title()})
        result = {'options': sorted({r['id']: r for r in options}.values(), key=lambda r: r['id']),
                  'catalog_available': True}
        _MODEL_CATALOG[cache_key] = (time.monotonic(), result)
        return result
    except Exception:
        return {'options': [], 'catalog_available': False}


@contextmanager
def _db():
    root = users.base_dir() / 'agent-api'
    ensure_dir(root)
    path = root / 'app-tickets.sqlite'
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE IF NOT EXISTS tickets(hash TEXT PRIMARY KEY, person TEXT NOT NULL, '
                 'kind TEXT NOT NULL, payload TEXT NOT NULL, expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0)')
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _ticket(person, kind, payload):
    token = secrets.token_urlsafe(32)
    with _db() as conn:
        conn.execute('DELETE FROM tickets WHERE expires<?', (time.time(),))
        if conn.execute('SELECT count(*) FROM tickets WHERE person=? AND used=0', (person,)).fetchone()[0] >= 30:
            raise HTTPException(429, 'too_many_tickets')
        conn.execute('INSERT INTO tickets VALUES(?,?,?,?,?,0)',
            (hashlib.sha256(token.encode()).hexdigest(), person, kind, json.dumps(payload), time.time()+300))
    return token


def ticket(token, kind, *, consume=False):
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        raise HTTPException(401, 'invalid_ticket')
    digest = hashlib.sha256(token.encode()).hexdigest()
    with _db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM tickets WHERE hash=? AND kind=? AND used=0 AND expires>?',
                           (digest, kind, time.time())).fetchone()
        if row is None:
            raise HTTPException(401, 'invalid_ticket')
        if consume:
            conn.execute('UPDATE tickets SET used=1 WHERE hash=?', (digest,))
    return row['person'], json.loads(row['payload'])


def upload_ticket(request):
    if getattr(request.state, 'app_upload_token', None):
        return ticket(request.state.app_upload_token, 'upload')
    auth = request.headers.get('authorization', '')
    return ticket(auth.removeprefix('JobwatchUpload ') if auth.startswith('JobwatchUpload ') else '', 'upload')


async def receive_upload(request):
    """Authenticate before buffering the file. Simple POST avoids Access CORS preflight."""
    stream = request.stream()
    initial = b''
    if request.headers.get('authorization'):
        upload_ticket(request)
        request.state.app_upload_token = request.headers['authorization'].removeprefix('JobwatchUpload ')
    else:
        # Browser sends a fixed 44-byte capability envelope, then the unmodified file.
        async for chunk in stream:
            initial += chunk
            if len(initial) >= 44:
                break
        if len(initial) < 44 or initial[43:44] != b'\n':
            raise HTTPException(401, 'invalid_ticket')
        try:
            token = initial[:43].decode('ascii')
        except UnicodeError:
            raise HTTPException(401, 'invalid_ticket') from None
        ticket(token, 'upload')
        request.state.app_upload_token = token
        initial = initial[44:]
    chunks, size = [initial], len(initial)
    if size > intake.MAX_UPLOAD_BYTES:
        raise HTTPException(413, 'too_large')
    async for chunk in stream:
        size += len(chunk)
        if size > intake.MAX_UPLOAD_BYTES:
            raise HTTPException(413, 'too_large')
        chunks.append(chunk)
    return b''.join(chunks)


class UploadRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    filename: str = Field(min_length=1, max_length=255)
    kind: str
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    bytes: int = Field(gt=0, le=intake.MAX_UPLOAD_BYTES)


class ModelRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    picks: dict[str, str] = Field(min_length=1, max_length=6)


def mount(app, require, get_config):
    read, approve = require('read'), require('approve')
    origin = os.environ.get('JOBWATCH_APP_ORIGIN', '')
    if not re.fullmatch(r'https://[A-Za-z0-9.-]+(?::[0-9]+)?', origin):
        raise ValueError('invalid_app_origin')

    def cors(request):
        incoming = request.headers.get('origin')
        if incoming not in (origin, 'null'):
            raise HTTPException(403, 'origin_required')
        return {'Access-Control-Allow-Origin': incoming, 'Access-Control-Allow-Credentials': 'true',
                'Vary': 'Origin', 'Cache-Control': 'no-store'}

    @app.options(UPLOAD)
    def options(request: Request):
        return Response(headers={**cors(request), 'Access-Control-Allow-Methods': 'POST',
            'Access-Control-Allow-Headers': 'authorization,content-type', 'Access-Control-Max-Age': '300'})

    @app.post('/api/agent/client/upload-ticket')
    def issue_upload(body: UploadRequest, principal=Depends(approve)):
        if body.kind not in intake.KINDS or Path(body.filename).suffix.lower() not in intake.EXTENSIONS:
            raise HTTPException(415, 'unsupported_type')
        return {'url': origin + UPLOAD, 'ticket': _ticket(principal.person, 'upload', body.model_dump())}

    @app.post(UPLOAD, status_code=201)
    async def upload(request: Request):
        headers = cors(request)
        person, spec = upload_ticket(request)
        data = await request.body()
        if len(data) != spec['bytes'] or not hmac.compare_digest(hashlib.sha256(data).hexdigest(), spec['sha256']):
            return JSONResponse({'error': 'upload_changed'}, status_code=409, headers=headers)
        ticket(request.state.app_upload_token, 'upload', consume=True)
        def save():
            with users.use(person):
                return intake.save_upload(person, spec['filename'], data, spec['kind'])
        result = await asyncio.to_thread(save)
        return JSONResponse(result, status_code=201, headers=headers)

    @app.post('/api/agent/client/artifacts/{artifact_id}/download-ticket')
    def issue_download(artifact_id: str, principal=Depends(approve)):
        with APIStore(principal.person) as store:
            row = store.conn.execute('SELECT * FROM api_artifacts WHERE id=?', (artifact_id,)).fetchone()
            if row is None:
                raise KeyError('not_found')
            _read_artifact(row['path'], row['sha256'], data_root=users.user_dir(principal.person))
        return {'url': origin + DOWNLOAD + '?ticket=' + _ticket(principal.person, 'download', {'id': artifact_id})}

    @app.get(DOWNLOAD)
    def download(ticket: str):
        person, spec = globals()['ticket'](ticket, 'download', consume=True)
        with APIStore(person) as store:
            row = store.conn.execute('SELECT * FROM api_artifacts WHERE id=?', (spec['id'],)).fetchone()
            if row is None:
                raise KeyError('not_found')
            raw = _read_artifact(row['path'], row['sha256'], data_root=users.user_dir(person))
            pdf = row['kind'] in ('cv', 'letter')
            return Response(raw, media_type='application/pdf' if pdf else 'application/json', headers={
                'Content-Disposition': f'attachment; filename="{row["kind"]}.{ "pdf" if pdf else "json"}"',
                'Referrer-Policy': 'no-referrer'})

    @app.get('/api/agent/client/profile')
    def profile(principal=Depends(read)):
        with users.use(principal.person):
            proposal = intake.open_proposal(principal.person)
            result = {'current': intake.current_version(principal.person),
                      'proposal': proposal.model_dump(mode='json') if proposal else None}
            if proposal and proposal.status == 'draft':
                try:
                    confirmation = intake.confirmation(principal.person, proposal.id, get_config(principal.person))
                    result['confirmation'] = {**confirmation, 'scope': confirmation['scope'].model_dump(mode='json')}
                except intake.IntakeError:
                    pass  # incomplete drafts still show questions and evidence
            return result

    @app.get('/api/agent/client/models')
    def models(principal=Depends(read)):
        with users.use(principal.person):
            return {'roles': {role: {'label': label, 'model': model_choice.get_model(role, principal.person)}
                              for role, (label, _) in model_choice.ROLES.items()},
                    'embedding': 'openrouter/qwen/qwen3-embedding-8b',
                    **model_catalog(principal.person, get_config(principal.person))}

    @app.post('/api/agent/client/models')
    def set_models(body: ModelRequest, principal=Depends(approve)):
        from pipeline.agentic.service import configured_llm
        with users.use(principal.person):
            llm = configured_llm(get_config(principal.person))
            try:
                for role, model in body.picks.items():
                    if role not in model_choice.ROLES:
                        raise HTTPException(422, 'invalid_role')
                    model_choice.check(model, role, principal.person)
                    require_route(llm, model)
                model_choice.set_models(body.picks, principal.person)
            except (RuntimeErrorSafe, model_choice.ModelRefused):
                raise HTTPException(422, 'model_route_not_allowed') from None
            return models(principal)
