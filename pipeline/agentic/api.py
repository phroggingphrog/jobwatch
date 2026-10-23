"""Native, authenticated Jobwatch agent API. No browser/UI startup side effects."""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import hmac
import json
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from jobwatch import users
from jobwatch.apply.paths import ensure_dir
from jobwatch.candidate import intake
from jobwatch.execution_mode import effective_mode
from pipeline.agentic.api_store import APIStore, Conflict, encoded
from pipeline.agentic.chat import dispatch, skill_version, job_database, job_connection
from pipeline.agentic.execution import Execution
from pipeline.agentic import profile_api, discovery_api
from pipeline.agentic.persistence import _read_artifact
from pipeline.agentic.runtime import RuntimeErrorSafe


@dataclass(frozen=True)
class Principal:
    person: str
    scopes: frozenset[str] = frozenset({'read', 'run'})


def credentials_from_env():
    credentials = {}
    source = os.environ.get('JOBWATCH_AGENT_CREDENTIALS_FILE')
    if source:
        path = Path(source).expanduser()
        if path.stat().st_mode & 0o077:
            raise RuntimeErrorSafe('credential_file_permissions')
        for row in json.loads(path.read_text()):
            credentials[row['token']] = Principal(row['person'], frozenset(row['scopes']))
    else:
        person = os.environ.get('JOBWATCH_AGENT_PERSON', users.DEFAULT_USER)
        token = os.environ.get('JOBWATCH_AGENT_TOKEN')
        approval = os.environ.get('JOBWATCH_AGENT_APPROVAL_TOKEN')
        if token:
            credentials[token] = Principal(person)
        if approval:
            if token == approval:
                raise RuntimeErrorSafe('approval_credential_must_differ')
            credentials[approval] = Principal(person, frozenset({'read', 'interact', 'approve'}))
    if not credentials:
        raise RuntimeErrorSafe('api_credentials_required')
    return credentials


class _Body(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Message(_Body):
    message: str = Field(min_length=1, max_length=16000)


class InteractionResponse(_Body):
    decision: Literal['answer', 'decline', 'approve', 'reject']
    answer: str | None = Field(default=None, max_length=4000)


def create_api(*, credentials=None, config=None, llm_factory=None, dispatcher=dispatch, browser_sessions=None):
    credentials = credentials if credentials is not None else credentials_from_env()
    if not credentials or any(not isinstance(token, str) or len(token) < 32 or not users.valid_name(p.person)
            or not p.scopes <= {'read', 'run', 'interact', 'approve'} for token, p in credentials.items()):
        raise RuntimeErrorSafe('api_credentials_invalid')
    from pipeline.agentic import identity

    def all_credentials():
        return {**credentials, **identity.credentials()}

    def known_people():
        return sorted({p.person for p in all_credentials().values()})

    people = known_people()
    hashes = [(hashlib.sha256(t.encode()).digest(), p) for t, p in credentials.items()]
    stopping = asyncio.Event()

    def get_config(person):
        from jobwatch.config import load_config
        with users.use(person):
            return config if config is not None else load_config()

    def event(person, run, kind, data):
        with APIStore(person) as store:
            store.emit(run, kind, data)

    def process(person, row):
        with users.use(person):
            def cancelled():
                with APIStore(person) as store:
                    return stopping.is_set() or bool(store.raw_run(row['id'])['cancel_requested'])
            try:
                cfg = get_config(person)
                from pipeline.agentic.service import _config
                settings = _config(cfg)
                payload = json.loads(row['input_json'])
                is_selection = 'selection_id' in payload
                with APIStore(person) as store:
                    usage = store.usage_checkpoint(row['id'])
                execution = Execution(row['id'], seconds=settings['batch_seconds'] if is_selection else min(settings['job_seconds'], settings['batch_seconds']),
                    token_ceiling=settings['batch_token_ceiling'] if is_selection else settings['job_token_ceiling'],
                    emit=lambda kind, data: event(person, row['id'], kind, data), cancelled=cancelled, **usage)
                with APIStore(person) as store:
                    if store.thread(row['thread_id'])['skill_hash'] != skill_version():
                        raise RuntimeErrorSafe('thread_skill_version_changed')
                execution.check()
                if is_selection:
                    from pipeline.agentic import selection, execution as invocation
                    from jobwatch.execution_mode import effective_mode
                    if effective_mode(cfg)=='off':
                        raise RuntimeErrorSafe('execution_disabled')
                    with invocation.use(execution), job_connection(cfg,write=True) as jobs:
                        result=selection.execute(jobs,cfg,payload['selection_id'],payload['manifest_hash'],row['id'],
                            llm_factory=(lambda:llm_factory(person)) if llm_factory else None)
                else:
                    result = dispatcher(person=person, thread_id=row['thread_id'], config=cfg,
                        llm=llm_factory(person) if llm_factory else None, execution=execution,
                        human_decision='decisions' in payload, **payload)
                execution.check()
                result['usage'] = execution.usage()
                with APIStore(person) as store:
                    # Only complete, immutable pipeline packages become API artifacts.
                    db_path = job_database(cfg)
                    if db_path.exists() and not result.get('outcomes'):
                        import sqlite3
                        with job_connection(cfg) as jobs:
                            if jobs.execute("SELECT 1 FROM sqlite_master WHERE name='agentic_activity'").fetchone():
                                result['outcomes'] = [dict(zip(('posting_id','run_key','status','reason'), item)) for item in jobs.execute(
                                    'SELECT DISTINCT r.posting_id,r.run_key,r.status,r.reason FROM agentic_runs r '
                                    "JOIN agentic_activity a ON a.run_key=r.run_key WHERE a.invocation_id=? AND a.event='finished'", (row['id'],))]
                    if db_path.exists() and result.get('outcomes'):
                        import sqlite3
                        with job_connection(cfg) as jobs:
                            for outcome in result['outcomes']:
                                key = outcome.get('run_key')
                                if not key or outcome.get('status') != 'ready':
                                    continue
                                for kind, path, sha in jobs.execute('SELECT a.kind,a.path,a.sha256 FROM '
                                    'agentic_artifacts a JOIN agentic_packages p ON p.run_key=a.run_key '
                                    "WHERE a.run_key=? AND p.phase='complete' AND a.kind IN ('cv','letter','form_map')", (key,)):
                                    _read_artifact(path, sha, data_root=users.user_dir(person))
                                    store.conn.execute('INSERT OR IGNORE INTO api_artifacts VALUES(?,?,?,?,?)',
                                                       (uuid.uuid4().hex, row['id'], kind, path, sha))
                        store.conn.commit()
                    store.finish(row['id'], result)
            except Exception as exc:
                code = getattr(exc, 'code', None)
                from pipeline.agentic.selection import SelectionError
                if not isinstance(exc, (RuntimeErrorSafe, Conflict, SelectionError)) or not isinstance(code, str) or not re.fullmatch(r'[a-z_]{1,80}', code):
                    code = 'execution_failed'
                with APIStore(person) as store:
                    if code == 'cancelled' and stopping.is_set() and not store.raw_run(row['id'])['cancel_requested']:
                        code = 'worker_interrupted'  # shutdown, not a user cancel: stay retryable (see CHAT.md recovery)
                    store.finish(row['id'], error=code)
                payload=json.loads(row['input_json'])
                if 'selection_id' in payload:
                    from pipeline.agentic import selection
                    with job_connection(get_config(person),write=True) as jobs:
                        selection.finish_error(jobs,payload['selection_id'],code)

    async def worker():
        while not stopping.is_set():
            worked = False
            for person in known_people():
                with users.use(person):
                    cfg=get_config(person)
                    if job_database(cfg).exists():
                        with job_connection(cfg,write=True) as jobs:
                            if jobs.execute("SELECT 1 FROM sqlite_master WHERE name='selection_requests'").fetchone():
                                from pipeline.agentic import selection
                                selection.reconcile(jobs)
                                selection.dispatch_pending(jobs,cfg)
                with APIStore(person) as store:
                    row = store.claim_next()
                if row is not None:
                    worked = True
                    await asyncio.to_thread(process, person, row)
            if not worked:
                await asyncio.sleep(0.1)

    @asynccontextmanager
    async def lifespan(app):
        root = ensure_dir(users.base_dir() / 'agent-api')
        fd = os.open(root / 'worker.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeErrorSafe('api_worker_already_running') from None
            for person in people:
                with APIStore(person) as store:
                    store.recover()
            stopping.clear()
            task = asyncio.create_task(worker())
            app.state.worker = task
            browser_task = asyncio.create_task(app.state.browser_worker(stopping)) if hasattr(app.state, 'browser_worker') else None
            try:
                yield
            finally:
                stopping.set()
                await task
                if browser_task:
                    await browser_task
                    app.state.browser_sessions.close_all()
        finally:
            os.close(fd)

    def lookup(authorization):
        value = authorization.removeprefix('Bearer ') if authorization and authorization.startswith('Bearer ') else ''
        digest = hashlib.sha256(value.encode()).digest()
        principal = None
        current_hashes = hashes + [(hashlib.sha256(key.encode()).digest(), p) for key,p in identity.credentials().items()]
        for expected, possible in current_hashes:
            if hmac.compare_digest(digest, expected):
                principal = possible
        return principal

    app = FastAPI(title='Jobwatch Agent API', version='1', lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def private_responses(request, call_next):
        # Bound JSON bodies before validation; do not log or echo their contents.
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            # Every body-bearing method is capped at 64 KiB; only the profile upload has its own larger cap, and it
            # needs a bearer with run scope before we buffer 10 MiB.
            upload = request.method == 'POST' and request.url.path == profile_api.UPLOAD_PATH
            app_upload = (os.environ.get('JOBWATCH_MCP_APP_ENABLED') == 'true' and request.method == 'POST'
                          and request.url.path == '/api/agent/client/upload')
            if app_upload:
                from pipeline.agentic.client_api import receive_upload
                try:
                    request._body = await receive_upload(request)
                except HTTPException as exc:
                    return JSONResponse({'error': exc.detail}, status_code=exc.status_code)
            cap, chunks, size = (intake.MAX_UPLOAD_BYTES + 44 if app_upload else profile_api.UPLOAD_BODY_CAP if upload else 65536), [], 0
            if upload:
                who = lookup(request.headers.get('authorization'))
                if who is None:
                    return JSONResponse({'error': 'authentication_required'}, status_code=401, headers={'WWW-Authenticate': 'Bearer'})
                if 'run' not in who.scopes:
                    return JSONResponse({'error': 'scope_required'}, status_code=403)
            too_large = {'error': 'too_large'} if upload else {'error': 'request_too_large'}
            declared = request.headers.get('content-length', '')
            if declared.isdigit() and int(declared) > cap:
                return JSONResponse(too_large, status_code=413)
            if not app_upload:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > cap:
                        return JSONResponse(too_large, status_code=413)
                    chunks.append(chunk)
                request._body = b''.join(chunks)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    def require(scope):
        def authenticate(authorization: str | None = Header(default=None)):
            principal = lookup(authorization)
            if principal is None:
                raise HTTPException(401, 'authentication_required', headers={'WWW-Authenticate': 'Bearer'})
            if scope not in principal.scopes:
                raise HTTPException(403, 'scope_required')
            return principal
        return authenticate

    identity.mount(app, credentials)

    read, write, interact = require('read'), require('run'), require('interact')

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse({'error': exc.code}, status_code=409)

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({'error': 'not_found'}, status_code=404)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse({'error': 'invalid_request'}, status_code=422)

    @app.exception_handler(Exception)
    async def failed(request, exc):
        return JSONResponse({'error': 'service_unavailable'}, status_code=503)

    from pipeline.agentic import browser_api
    browser_api.mount(app, require, get_config, sessions=browser_sessions)

    profile_api.mount(app, require, get_config, llm_factory)
    discovery_api.mount(app, require, get_config)
    from pipeline.agentic import shortlist_api
    shortlist_api.mount(app, require, get_config)
    from pipeline.agentic import feedback_api
    feedback_api.mount(app, require, get_config)
    if os.environ.get('JOBWATCH_LIBRECHAT_ENABLED') == 'true':
        from pipeline.agentic import librechat
        librechat.mount(app, require, get_config)

    if os.environ.get('JOBWATCH_MCP_APP_ENABLED') == 'true':
        from pipeline.agentic import client_api
        client_api.mount(app, require, get_config)

    @app.get('/health')
    def health():
        active = getattr(app.state, 'worker', None)
        if active is not None and active.done():
            raise HTTPException(503, 'worker_unavailable')
        return {'status': 'ok', 'schema_version': 1}

    @app.get('/api/agent/openapi.json')
    def schema(principal=Depends(read)):
        return app.openapi()

    @app.get('/api/agent/capabilities')
    def capabilities(principal=Depends(read)):
        return dict(schema_version=1, execution_mode=effective_mode(get_config(principal.person)),
                    skill_version=skill_version(), protocol='native-http',
                    human_submit=True, confirmed_submit=True, scopes=sorted(principal.scopes),
                    discovery=dict(read_only=True, flags=discovery_api.flags(get_config(principal.person))),
                    shortlist=dict(labels=shortlist_api.LABELS,orderings=['provisional','personalised'],
                                   rules_version='ranking-rules-v1',refresh_paid=False),
                    profile=dict(upload_max_bytes=intake.MAX_UPLOAD_BYTES, kinds=list(intake.KINDS),
                                 extensions=list(intake.EXTENSIONS)))

    @app.post('/api/agent/threads', status_code=201)
    def create_thread(principal=Depends(write)):
        with APIStore(principal.person) as store:
            return store.create_thread(skill_version())

    @app.get('/api/agent/threads/{thread_id}')
    def thread(thread_id: str, principal=Depends(read)):
        with APIStore(principal.person) as store:
            result = store.thread(thread_id)
            result['runs'] = [dict(row) for row in store.conn.execute(
                'SELECT id,state,created,updated FROM api_runs WHERE thread_id=? ORDER BY created', (thread_id,))]
            return result

    @app.post('/api/agent/threads/{thread_id}/runs', status_code=202)
    def start(thread_id: str, body: Message, idempotency_key: str = Header(min_length=1, max_length=128),
              principal=Depends(write)):
        if not body.message.strip():
            raise HTTPException(422, 'message_required')
        with APIStore(principal.person) as store:
            ident = store.enqueue(thread_id, {'message': body.message}, idempotency_key)
            return store.public_run(ident)

    @app.get('/api/agent/runs/{run_id}')
    def status(run_id: str, principal=Depends(read)):
        with APIStore(principal.person) as store:
            return store.public_run(run_id)

    @app.get('/api/agent/runs/{run_id}/events')
    async def events(run_id: str, request: Request, after: int = 0, principal=Depends(read)):
        try:
            after = max(after, int(request.headers.get('last-event-id', '0')))
            if not 0 <= after <= 2**63 - 1:
                raise ValueError
        except ValueError:
            raise HTTPException(422, 'invalid_event_cursor') from None
        with APIStore(principal.person) as store:
            store.raw_run(run_id)
        async def stream():
            cursor = after
            while not await request.is_disconnected():
                with APIStore(principal.person) as store:
                    state = store.raw_run(run_id)['state']  # state first: events committed after it are read below or next loop
                    batch = store.events(run_id, cursor)
                for item in batch:
                    cursor = item['id']
                    yield f'id: {cursor}\nevent: {item["type"]}\ndata: {encoded(item)}\n\n'
                if state not in ('queued', 'running') and len(batch) < 100:
                    break
                if not batch:
                    yield ': waiting\n\n'
                    await asyncio.sleep(0.5)
        return StreamingResponse(stream(), media_type='text/event-stream')

    @app.post('/api/agent/interactions/{interaction_id}/responses', status_code=202)
    def respond(interaction_id: str, body: InteractionResponse, principal=Depends(interact)):
        with APIStore(principal.person) as store:
            row = store.conn.execute('SELECT payload FROM api_interactions WHERE id=?', (interaction_id,)).fetchone()
            if row is None:
                raise KeyError('not_found')
            if json.loads(row['payload'])['type'] == 'approval' and 'approve' not in principal.scopes:
                raise HTTPException(403, 'approval_scope_required')
            resume, _ = store.respond(interaction_id, body.model_dump())
            return {'run_id': resume, 'state': 'queued' if resume else 'waiting_for_input'}

    @app.post('/api/agent/runs/{run_id}/cancel', status_code=202)
    def cancel(run_id: str, principal=Depends(write)):
        with APIStore(principal.person) as store:
            store.cancel(run_id)
            result=store.public_run(run_id)
        with users.use(principal.person):
            cfg=get_config(principal.person)
            if job_database(cfg).exists():
                with job_connection(cfg,write=True) as jobs:
                    if jobs.execute("SELECT 1 FROM sqlite_master WHERE name='selection_requests'").fetchone():
                        from pipeline.agentic import selection
                        selection.reconcile(jobs,run_id=run_id)
        return result

    @app.post('/api/agent/runs/{run_id}/retry', status_code=202)
    def retry(run_id: str, principal=Depends(write)):
        with APIStore(principal.person) as store:
            store.retry(run_id)
            return store.public_run(run_id)

    @app.get('/api/agent/artifacts/{artifact_id}')
    def artifact(artifact_id: str, principal=Depends(read)):
        with APIStore(principal.person) as store:
            row = store.conn.execute('SELECT * FROM api_artifacts WHERE id=?', (artifact_id,)).fetchone()
            if row is None:
                raise KeyError('not_found')
            try:
                raw = _read_artifact(row['path'], row['sha256'], data_root=users.user_dir(principal.person))
            except Exception:
                raise HTTPException(409, 'artifact_invalid') from None
            pdf = row['kind'] in ('cv', 'letter')
            return Response(raw, media_type='application/pdf' if pdf else 'application/json',
                headers={'Content-Disposition': f'attachment; filename="{row["kind"]}.{ "pdf" if pdf else "json"}"'})

    return app


def main(argv=None):
    import argparse
    import uvicorn
    parser = argparse.ArgumentParser(description='Native Jobwatch agent backend')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8914)
    parser.add_argument('--person', default=users.DEFAULT_USER, help='Person for offline backup/evaluation only')
    parser.add_argument('--backup', metavar='PATH', help='Make a consistent private SQLite backup and exit')
    parser.add_argument('--evaluate-run', metavar='RUN_ID', help='Evaluate a local run tool trajectory and exit (dev extra)')
    parser.add_argument('--expected-tools', nargs='*', default=[])
    parser.add_argument('--matching-comparison', metavar='PRIVATE_JSON', help='Compare saved, owner-reviewed matcher outputs offline; no models')
    parser.add_argument('--blind-output-dir', metavar='NEW_PRIVATE_DIR', help='Export anonymized matching packet and separate arm key instead of scoring')
    args = parser.parse_args(argv)
    if args.blind_output_dir and not args.matching_comparison:
        parser.error('--blind-output-dir requires --matching-comparison')
    if args.matching_comparison:
        from pipeline.agentic.evaluation import blind_matching_packet, compare_matching_runs
        import secrets
        try:
            root = users.user_dir(args.person).resolve()
            source = Path(args.matching_comparison).expanduser().resolve()
            source.relative_to(root)
            if source.stat().st_size > 32 * 1024 * 1024:
                raise ValueError
            raw = json.loads(source.read_text())
            if args.blind_output_dir:
                target = Path(args.blind_output_dir).expanduser().resolve()
                target.relative_to(root)
                packet, key = blind_matching_packet(raw, seed=secrets.randbits(128))
                target.mkdir(mode=0o700, parents=False, exist_ok=False)
                for name, value in (('packet.json', packet), ('private-arm-key.json', key)):
                    fd = os.open(target / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                    with os.fdopen(fd, 'w') as handle:
                        json.dump(value, handle, ensure_ascii=False, allow_nan=False)
                print('Private review packet and separate arm key created. Keep the key hidden during review.')
            else:
                print(json.dumps(compare_matching_runs(raw), allow_nan=False))
        except Exception:
            raise SystemExit('Matching comparison unavailable; check private paths, paired snapshots and complete owner labels.') from None
        return
    if args.backup:
        import sqlite3
        source = users.user_dir(args.person) / 'career-chat' / 'state.sqlite'
        if not source.is_file():
            raise SystemExit('No existing agent state for this person.')
        destination = Path(args.backup).expanduser()
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        with APIStore(args.person) as store, sqlite3.connect(destination) as target:
            store.conn.backup(target)
        print('Private agent state backup created.')
        return
    if args.evaluate_run:
        from pipeline.agentic.evaluation import evaluate_tools
        with APIStore(args.person) as store:
            events, after = [], 0
            while batch := store.events(args.evaluate_run, after):
                events.extend(batch)
                after = batch[-1]['id']
        print(json.dumps(evaluate_tools(events, args.expected_tools)))
        return
    from jobwatch.origin_guard import OriginRejected, check_bind
    try:
        check_bind(args.host)                 # loopback only, as the web board already requires
    except OriginRejected as exc:
        raise SystemExit(str(exc)) from None
    try:
        app = create_api()
    except Exception:
        raise SystemExit('Jobwatch API requires valid private credentials; see pipeline/agentic/CHAT.md') from None
    uvicorn.run(app, host=args.host, port=args.port, access_log=False)
