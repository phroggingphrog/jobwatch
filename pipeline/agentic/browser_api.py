"""Native application/browser operations shared by the chat and website frontends."""
from __future__ import annotations

import asyncio
import base64
from typing import Literal
import hashlib
import os
import time

from fastapi import Depends, Header, HTTPException
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jobwatch import users, db
from jobwatch.apply import submit_confirm, paths
from jobwatch.apply.browser import BrowserService
from jobwatch.web.browser_session import BrowserSessionManager, BrowserSessionError
from pipeline.agentic.chat import job_database

PREFIX = '/api/agent/applications'


class ReviewBody(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    digest: str = Field(pattern=r'^[0-9a-f]{64}$')


class OpenBody(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    restart: bool = False
    preparation_run_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    package_key: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')


class WebsiteOperation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    operation: Literal['context','app_context','preparation_context','start_preparation','answer_missing','settle_submit','confirmed_submit',
                       'manager_status','manager_open','manager_action','manager_close','manager_snapshot']
    posting_id: int | None = Field(default=None, gt=0, lt=2**63)
    application_id: str | None = Field(default=None, pattern=r'^[A-Za-z0-9_-]{1,128}$')
    arguments: dict = Field(default_factory=dict)


class BrowserAnswers(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    preparation_run_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    answers: dict[str, str | bool | list[str]] = Field(min_length=1, max_length=250)


def mount(app, require, get_config, *, sessions=None):
    if sessions is None and os.environ.get('JOBWATCH_NATIVE_BROWSER_ENABLED') != 'true':
        return
    sessions = sessions or BrowserSessionManager()
    read, human = require('read'), require('approve')

    def service(person):
        cfg = get_config(person)
        def connection():
            if not job_database(cfg).exists():
                raise HTTPException(404, 'not_found')
            return db.connect(job_database(cfg))
        return BrowserService(cfg, connection, sessions)

    def state(person, posting_id):
        s = service(person)
        value = s.preparation_context(posting_id)
        job = value['job']
        with s.conn_factory() as conn:
            outcome = submit_confirm.outcome(conn, posting_id)
        conn.close()
        prepared = value['prepared'] or {}
        from jobwatch.apply.prepare import latest_preparation
        previous = latest_preparation(paths.data_dir(), str(job['application_id'])) if job['application_id'] else None
        return {'posting_id': posting_id, 'title': job['title'], 'company': job['company'],
                'application_id': job['application_id'], 'can_prepare': value['can_prepare'],
                'restart_required':bool(previous and not prepared),
                'previous_preparation_run_id':previous.get('run_id') if previous else None,
                'package_key':(value['package'] or {}).get('run_key'),
                'browser': value['browser'], 'status': prepared.get('status'),
                'missing': prepared.get('missing', []), 'reason':prepared.get('reason'), 'preparation_run_id': prepared.get('run_id'), 'submission': outcome}

    @app.exception_handler(BrowserSessionError)
    async def unavailable(request, exc):
        # No page content, browser URLs, exceptions or credentials in diagnostics.
        return JSONResponse({'error': 'browser_unavailable'}, status_code=409)

    @app.get(PREFIX)
    def listing(principal=Depends(read)):
        with users.use(principal.person):
            s = service(principal.person)
            if not job_database(s.config).exists():
                return {'applications': []}
            conn = s.conn_factory()
            try:
                ids = [row[0] for row in conn.execute('SELECT posting_id FROM applications ORDER BY id DESC LIMIT 50')]
            finally:
                conn.close()
            return {'applications': [state(principal.person, pid) for pid in ids]}

    @app.get(PREFIX+'/{posting_id}')
    def application(posting_id: int, principal=Depends(read)):
        with users.use(principal.person):
            return state(principal.person, posting_id)

    @app.post(PREFIX+'/{posting_id}/open')
    def open_application(posting_id: int, body: OpenBody | None = None, principal=Depends(human)):
        with users.use(principal.person):
            s = service(principal.person)
            job, package = s.app_context(posting_id)
            current = s.preparation_context(posting_id)
            if not current['can_prepare']:
                raise HTTPException(409, 'verified_package_required')
            aid = str(job['application_id'])
            from jobwatch.apply.prepare import latest_preparation
            previous = latest_preparation(paths.data_dir(), aid)
            body = body or OpenBody()
            if body.restart:
                conn = s.conn_factory()
                try:
                    outcome = submit_confirm.outcome(conn, posting_id)
                finally:
                    conn.close()
                if outcome and outcome['status'] in ('pending','pressed','submitted','unsure'):
                    raise HTTPException(409,'submission_already_pending_or_uncertain')
                if (not previous or previous.get('run_id') != body.preparation_run_id or
                        not package or package['run_key'] != body.package_key):
                    raise HTTPException(409,'application_changed')
                if current['browser']['automation_active']:
                    raise HTTPException(409,'browser_busy')
                # Only this separate host-confirmed action starts a fresh fill. Passive reopening
                # and duplicate actions with an old preparation reference never repeat paid work.
                if not current['browser']['open']:
                    sessions.open(aid,job['url'])
                s.start_preparation(posting_id)
            else:
                if previous and not current['prepared']:
                    raise HTTPException(409,'restart_confirmation_required')
                if not current['browser']['open']:
                    sessions.open(aid,job['url'])
                if not previous and not s.browser_status(aid)['automation_active']:
                    s.start_preparation(posting_id)
            return state(principal.person, posting_id)

    @app.post(PREFIX+'/{posting_id}/answers', status_code=202)
    def answers(posting_id: int, body: BrowserAnswers, principal=Depends(human)):
        from starlette.datastructures import FormData
        values = [('preparation_run_id',body.preparation_run_id)]
        for key,value in body.answers.items():
            for item in value if isinstance(value,list) else [value]:
                values.append(('answer_'+key,str(item).lower() if isinstance(item,bool) else item))
        with users.use(principal.person):
            service(principal.person).answer_missing(posting_id,FormData(values))
            return state(principal.person,posting_id)

    @app.get(PREFIX+'/{posting_id}/review')
    def review(posting_id: int, principal=Depends(human)):
        with users.use(principal.person):
            try:
                return service(principal.person).review(posting_id)
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
                return {'status':'blocked','reason':exc.detail}

    @app.post(PREFIX+'/{posting_id}/review')
    def update_review(posting_id: int, body: ReviewBody, principal=Depends(human)):
        with users.use(principal.person):
            return service(principal.person).review(posting_id, expected=body.digest)

    @app.get(PREFIX+'/{posting_id}/frame')
    def frame(posting_id: int, principal=Depends(human)):
        with users.use(principal.person):
            job, _ = service(principal.person).app_context(posting_id)
            image = sessions.snapshot(str(job['application_id']))
            return Response(image.jpeg, media_type='image/jpeg', headers={'Cache-Control': 'no-store'})

    @app.post(PREFIX+'/{posting_id}/submit', status_code=202)
    def submit(posting_id: int, body: ReviewBody, key: str = Header(alias='Idempotency-Key'), principal=Depends(human)):
        if not key or len(key) > 200:
            raise HTTPException(422, 'invalid_request')
        with users.use(principal.person):
            s = service(principal.person)
            # The human must have seen this exact current form, not a model description.
            review = s.review(posting_id)
            if review.get('confirmed_digest') != body.digest:
                raise HTTPException(409, 'form_review_changed')
            job, _ = s.app_context(posting_id)
            conn = s.conn_factory()
            try:
                approval = hashlib.sha256((principal.person+':'+key).encode()).hexdigest()
                submit_confirm.ensure(conn)
                conn.execute('BEGIN IMMEDIATE')
                existing = conn.execute('SELECT status,posting_id,digest FROM submit_requests WHERE approval=?', (approval,)).fetchone()
                if existing:
                    if existing[1] != posting_id or existing[2] != body.digest:
                        raise HTTPException(409,'request_key_changed')
                    return {'status': existing[0]}
                latest = submit_confirm.outcome(conn, posting_id)
                if latest and latest['status'] in ('pending', 'pressed', 'submitted', 'unsure'):
                    raise HTTPException(409, 'submission_already_pending_or_uncertain')
                return submit_confirm.queue(conn, posting_id=posting_id, application_id=job['application_id'],
                                            confirm_digest=body.digest, approval=approval)
            finally:
                conn.close()

    @app.post('/api/agent/browser/website')
    def website(body: WebsiteOperation, principal=Depends(human)):
        with users.use(principal.person):
            s = service(principal.person)
            args = body.arguments
            if body.operation.startswith('manager_'):
                aid = body.application_id
                if aid == 'accounts':
                    if body.operation == 'manager_open':
                        from jobwatch.web.accounts_routes import SITES
                        if args.get('url') not in {value[1] for value in SITES.values()}:
                            raise HTTPException(422, 'invalid_account_site')
                else:
                    conn = s.conn_factory()
                    try:
                        job = conn.execute('SELECT p.url FROM applications a JOIN postings p ON p.id=a.posting_id WHERE a.id=?', (aid,)).fetchone()
                    finally:
                        conn.close()
                    if job is None:
                        raise HTTPException(404, 'not_found')
                    if body.operation == 'manager_open' and args.get('url') != job['url']:
                        raise HTTPException(409, 'application_changed')
                if body.operation == 'manager_open':
                    value = sessions.open(aid, args['url'])
                elif body.operation == 'manager_status':
                    try:
                        value = sessions.status(aid)
                    except BrowserSessionError:
                        value = {'open':False,'state':'closed','automation_active':False}
                elif body.operation == 'manager_action':
                    value = sessions.action(aid, args)
                elif body.operation == 'manager_close':
                    value = sessions.close(aid)
                else:
                    snapshot = sessions.snapshot(aid)
                    value = {'jpeg':base64.b64encode(snapshot.jpeg).decode(),'width':snapshot.width,'height':snapshot.height}
                return {'value':value}
            if body.posting_id is None:
                raise HTTPException(422, 'posting_required')
            if body.operation == 'context':
                value = s.context(body.posting_id)
            elif body.operation == 'app_context':
                value = s.app_context(body.posting_id)
            elif body.operation == 'preparation_context':
                value = s.preparation_context(body.posting_id, error=str(args.get('error','')))
            elif body.operation == 'start_preparation':
                value = s.start_preparation(body.posting_id, intake=args.get('intake'))
            elif body.operation == 'answer_missing':
                from starlette.datastructures import FormData
                value = s.answer_missing(body.posting_id,FormData(args.get('form',[])))
            elif body.operation == 'settle_submit':
                job,_ = s.app_context(body.posting_id)
                value = s.settle_submit(body.posting_id,str(job['application_id']))
            else:
                value = s.confirmed_submit(body.posting_id,str(args.get('confirm','')),'board')
            return {'value':value}

    app.state.application_service = service
    app.state.browser_sessions = sessions

    async def run(stopping):
        last_fill = 0
        while not stopping.is_set():
            fill = time.monotonic() - last_fill >= 60
            if fill:
                last_fill = time.monotonic()
            for person in users.list_users():
                with users.use(person):
                    if not job_database(get_config(person)).exists():
                        continue
                    s = service(person)
                    try:
                        if fill:
                            await asyncio.to_thread(s.auto_fill_ready)
                        await asyncio.to_thread(s.process_submit_requests)
                        await asyncio.to_thread(s.settle_open_sessions)
                    except Exception:
                        pass  # per-person faults never expose page content or stop another person's executor
            await asyncio.sleep(1)
    app.state.browser_worker = run
