"""Protected application review, streamed browser and one-time missing-fact intake."""
from __future__ import annotations

import logging
import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from jobwatch import ledger
from jobwatch import db as dbm
from jobwatch.commands.state import SUBMITTED
from jobwatch.apply import submit_confirm
from jobwatch.web.browser_session import BrowserSessionError
from jobwatch.apply import paths
from jobwatch.web import actions as act
from jobwatch.apply.prepare import latest_preparation, prepare_application, record_owner_answer
from jobwatch.apply.paths import ensure_dir, safe_write_text
from pipeline.agentic.persistence import latest_result
from pipeline.agentic.liveness import latest_observation, observation_current
from pipeline.agentic.runtime import BatchBudget, JobBudget
from pipeline.agentic.service import configured_llm, snapshot_inventory, _config


REFUSALS = ('submit_confirmation_stale', 'submit_not_confirmable', 'submit_press_failed', 'browser_closed')
REFUSAL_TEXT = {
    'submit_confirmation_stale': 'Nothing was submitted: the application changed after you confirmed. Review the live page and confirm again.',
    'submit_not_confirmable': 'Nothing was submitted: this application is no longer waiting for a Submit confirmation.',
    'submit_press_failed': 'Nothing was submitted: the Submit button could not be pressed. Check the live page.',
    'browser_closed': 'Nothing was submitted: the application browser is closed.'}


from jobwatch.apply.browser import package_is_current


def register(app, config, conn_factory, render, sessions):
    from jobwatch.apply.browser import BrowserService
    import os
    from jobwatch.apply.browser_remote import RemoteBrowserService
    service = RemoteBrowserService() if os.environ.get('JOBWATCH_NATIVE_BROWSER_URL') else BrowserService(config, conn_factory, sessions)
    app_context = service.app_context
    auto_fill_ready = service.auto_fill_ready
    browser_status = service.browser_status
    confirmed_submit = service.confirmed_submit
    context = service.context
    preparation_context = service.preparation_context
    process_submit_requests = service.process_submit_requests
    settle_open_sessions = service.settle_open_sessions
    settle_submit = service.settle_submit
    start_preparation = service.start_preparation







    app.state.auto_fill_ready = auto_fill_ready

    @app.get('/job/{posting_id}/prepare')
    def preparation_page(request: Request, posting_id: int):
        return render(request, 'prepare.html', **preparation_context(posting_id))

    @app.get('/job/{posting_id}/prepare/status')
    def preparation_status(request: Request, posting_id: int):
        return render(request, '_preparation.html', **preparation_context(posting_id))

    @app.post('/job/{posting_id}/browser/open')
    def browser_open(request: Request, posting_id: int):
        job, package = app_context(posting_id)
        try:
            sessions.open(str(job['application_id']), job['url'])
        except Exception:
            return render(request, 'prepare.html', status=409, **preparation_context(
                posting_id, 'The application browser could not open. Your saved documents are still available.'))
        if preparation_context(posting_id)['can_prepare']:
            start_preparation(posting_id)
        return RedirectResponse(f'/job/{posting_id}/prepare', status_code=303)

    @app.post('/job/{posting_id}/prepare')
    def prepare(request: Request, posting_id: int):
        start_preparation(posting_id)
        return RedirectResponse(f'/job/{posting_id}/prepare', status_code=303)

    @app.post('/job/{posting_id}/answers')
    async def answer_missing(request: Request, posting_id: int):
        form = await request.form(max_fields=250)
        service.answer_missing(posting_id, form)
        return RedirectResponse(f'/job/{posting_id}/prepare', status_code=303)


    app.state.confirmed_submit = confirmed_submit


    app.state.process_submit_requests = process_submit_requests


    app.state.settle_open_sessions = settle_open_sessions

    @app.post('/job/{posting_id}/prepare/submit')
    async def prepare_submit(request: Request, posting_id: int):
        form = await request.form(max_fields=5)
        app_context(posting_id)
        reason = await run_in_threadpool(confirmed_submit, posting_id, str(form.get('digest') or ''), 'board')
        if reason:
            return render(request, 'prepare.html', status=409, **preparation_context(posting_id, REFUSAL_TEXT.get(
                reason, 'Jobwatch could not tell whether Submit was pressed. Check the live page before trying again.')))
        return RedirectResponse(f'/job/{posting_id}/prepare', status_code=303)

    @app.post('/job/{posting_id}/browser/action')
    async def browser_action(request: Request, posting_id: int):
        job, _ = app_context(posting_id)
        try:
            if int(request.headers.get('content-length', '0')) > 100_000:
                raise ValueError
            raw = await request.body()
            if len(raw) > 100_000:
                raise ValueError
            action = json.loads(raw)
            if not isinstance(action, dict):
                raise ValueError
            await run_in_threadpool(sessions.action, str(job['application_id']), action)
            return JSONResponse({'ok': True})
        except Exception:
            return JSONResponse({'ok': False, 'error': 'Browser control is unavailable while preparation runs.'}, status_code=409)

    @app.get('/job/{posting_id}/browser/stream')
    def browser_stream(posting_id: int):
        job, _ = app_context(posting_id)
        aid = str(job['application_id'])
        if not browser_status(aid)['open']:
            raise HTTPException(404, 'Open the application browser first.')
        def frames():
            # No screenshots are logged or persisted by the viewing stream.
            while browser_status(aid)['open']:
                try:
                    frame = sessions.snapshot(aid)
                    jpeg = frame['jpeg']
                    yield (b'--jobwatchframe\r\nContent-Type: image/jpeg\r\nContent-Length: ' +
                           str(len(jpeg)).encode() + b'\r\n\r\n' + jpeg + b'\r\n')
                    time.sleep(0.5)
                except Exception:
                    break
        return StreamingResponse(frames(), media_type='multipart/x-mixed-replace; boundary=jobwatchframe',
                                 headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})

    @app.post('/job/{posting_id}/browser/close')
    def browser_close(posting_id: int):
        job, _ = app_context(posting_id)
        sessions.close(str(job['application_id']))
        return RedirectResponse(f'/job/{posting_id}/prepare', status_code=303)

    @app.get('/candidate')
    def candidate_page(request: Request):
        conn = conn_factory()
        candidate = None
        candidate_key = None
        understanding = {'status': 'legacy', 'models': {}}
        statistics = {"status": "input_unavailable"}
        outcomes = None
        try:
            from jobwatch.candidate import approved
            from jobwatch import users
            from jobwatch.candidate.presentation import statistical_view
            from jobwatch.outcomes.readiness import outcome_readiness
            outcomes = outcome_readiness(conn)
            try:
                from jobwatch.candidate.assessment import assessment_run_key
                from jobwatch.candidate.contracts import CandidateError, content_hash, digest
                from jobwatch.candidate.evidence import career_profile_text
                from jobwatch.candidate.policy import default_policy
                bundle = approved.evidence(users.current())
                cfg = _config(config)
                statistics = statistical_view(bundle, cfg)
                if not cfg.get('autonomous_evaluation', False):
                    candidate_key = assessment_run_key(bundle.bundle_hash,
                        content_hash(career_profile_text(bundle).encode()),
                        digest(default_policy().model_dump(mode='json')), statistics['run_key'], cfg['evaluator_model'])
            except Exception as exc:
                if isinstance(exc, CandidateError) and str(exc) == 'no_profile_version':
                    statistics = {'status': 'input_unavailable'}
                elif str(exc) == 'source_missing':    # no approved source yet: the page says so, nothing to log
                    statistics = {'status': 'input_unavailable'}
                else:
                    logging.getLogger(__name__).exception('candidate page: statistics failed')
                    statistics = {'status': 'error', 'error': f'{type(exc).__name__}: {str(exc)[:200]}'}
            if _config(config).get('autonomous_evaluation', False):
                from jobwatch.candidate.presentation import current_understanding
                understanding = current_understanding(conn)
                candidate = understanding['candidate']
            elif conn.execute("SELECT 1 FROM sqlite_master WHERE name='agentic_runs'").fetchone():
                for row in conn.execute('SELECT posting_id FROM agentic_runs ORDER BY rowid DESC LIMIT 100'):
                    try:
                        result = latest_result(conn, row[0])
                    except Exception:
                        continue
                    if result and result.get('candidate') and result['candidate'].get('run_key') == candidate_key:
                        candidate = result['candidate']
                        break
        finally:
            conn.close()
        try:
            from jobwatch.profile_check import check as _check_profile
            profile_problems = _check_profile()
        except Exception:  # noqa: BLE001 - the check never breaks the page
            profile_problems = []
        return render(request, 'candidate.html', candidate=candidate, statistics=statistics, outcomes=outcomes,
                      profile_problems=profile_problems, understanding=understanding)

    @app.get('/job/{posting_id}/evaluation')
    def evaluation_page(request: Request, posting_id: int):
        job, package = context(posting_id)
        return render(request, 'evaluation.html', job=job, evaluation=package.get('evaluation') if package else None)
