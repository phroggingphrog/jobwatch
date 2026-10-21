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


def package_is_current(conn, config, posting_id, package):
    """Bind UI readiness to today's exact ad, profile, policy and runtime inputs."""
    try:
        rows = snapshot_inventory(conn, config, posting_ids=[posting_id], limit=1)
        posting = conn.execute('SELECT url FROM postings WHERE id=?', (posting_id,)).fetchone()
        return bool(rows and posting and rows[0]['run_key'] == package['run_key']
                    and observation_current(latest_observation(conn, posting_id),
                        posting_id=posting_id, url=posting[0], ad_hash=rows[0]['ad_hash']))
    except Exception:
        return False


def register(app, config, conn_factory, render, sessions):
    def browser_status(aid):
        try:
            status = sessions.status(aid)
            return dict(status, open=status.get('state') == 'ready')
        except Exception:
            return {'open': False, 'automation_active': False}

    def context(posting_id):
        if not 0 < posting_id < 2**63:
            raise HTTPException(404, 'No such application')
        conn = conn_factory()
        try:
            row = conn.execute('SELECT p.id,p.title,p.company,p.url,p.source,p.description,a.id AS application_id,a.status '
                               'FROM postings p LEFT JOIN applications a ON a.posting_id=p.id WHERE p.id=?',
                               (posting_id,)).fetchone()
            if row is None:
                raise HTTPException(404, 'No such application')
            job = dict(row)
            try:
                package = latest_result(conn, posting_id)
                if package is not None:
                    package = dict(package, inputs_current=package_is_current(conn, config, posting_id, package))
            except Exception:
                package = None
            return job, package
        finally:
            conn.close()

    def app_context(posting_id):
        job, package = context(posting_id)
        if not job['application_id']:
            raise HTTPException(409, 'Prepare the application documents first.')
        return job, package

    def settle_submit(posting_id, aid):
        """After the owner pressed Submit: confident confirmation -> Applied (same write as the status select);
        unsure -> a 'submit_unsure' event, which the job page turns into a one-line question."""
        result = sessions.take_submit_result(aid) if aid else None
        if not result:
            return
        conn = conn_factory()
        try:
            row = conn.execute('SELECT id,status FROM applications WHERE posting_id=?', (posting_id,)).fetchone()
            if row is None or row['status'] in (*SUBMITTED, 'hired'):
                return
            last = conn.execute("SELECT kind FROM application_events WHERE application_id=? ORDER BY id DESC LIMIT 1",
                                (row['id'],)).fetchone()
            source = 'submit-confirmed' if last and last['kind'] == 'submit_confirmed' else 'submit-detected'
            if result == 'confident':
                act.set_status(conn, posting_id, 'applied', source=source)
            else:
                ledger.upsert(conn, 'applications', 'application_events', {
                    'application_id': row['id'], 'at': dbm.ts(), 'kind': 'submit_unsure', 'from_status': row['status'],
                    'to_status': None, 'actor': 'jobwatch', 'source': source, 'detail_json': '{}'})
        finally:
            conn.close()

    def preparation_context(posting_id, error=''):
        job, package = context(posting_id)
        aid = str(job['application_id']) if job['application_id'] else None
        if aid:
            settle_submit(posting_id, aid)
            job, package = context(posting_id)
        browser = browser_status(aid)
        prepared = latest_preparation(paths.data_dir(), aid) if aid else None
        if prepared and package and package.get('manifest'):
            package_hash = hashlib.sha256(json.dumps(package['manifest'], sort_keys=True,
                separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
            if prepared.get('package_hash') != package_hash:
                prepared = None
        can_prepare = bool(package and package.get('inputs_current') and package.get('status') == 'ready' and package.get('manifest')
                           and package.get('cv_pdf') and package.get('letter_pdf')
                           and job['status'] not in (*SUBMITTED, 'hired', 'rejected'))
        if not can_prepare:
            prepared = None
        if prepared and (not browser['open'] or browser.get('last_error')
                         or prepared.get('session_id') != browser.get('target_id')
                         or prepared.get('owner_revision') != browser.get('owner_revision')
                         or prepared.get('page_url_sha256') != browser.get('page_url_sha256')):
            prepared = None
        return dict(job=job, package=package, browser=browser, prepared=prepared, can_prepare=can_prepare,
                    confirm_digest=submit_confirm.digest(prepared) if browser['open'] else None, error=error)

    def start_preparation(posting_id, *, intake=None):
        job, package = app_context(posting_id)
        if not preparation_context(posting_id)['can_prepare']:
            raise HTTPException(409, 'A verified application package is needed before filling.')
        aid = str(job['application_id'])
        if not browser_status(aid)['open']:
            raise HTTPException(409, 'Open the application browser first.')
        try:
            worker_llm, reviewer_llm = configured_llm(config), configured_llm(config)
            runtime_config = _config(config)
        except Exception:
            raise HTTPException(503, 'The configured model connection is unavailable.')
        def fill(page):
            current_job, current_package = context(posting_id)
            if (not current_package or not current_package.get('inputs_current')
                    or current_package.get('status') != 'ready' or current_package['run_key'] != package['run_key']):
                raise ValueError('application_inputs_changed')
            if intake is not None:
                expected, replies = intake
                current = latest_preparation(paths.data_dir(), aid) or {}
                browser = browser_status(aid)
                if (current.get('run_id') != expected['run_id'] or current.get('status') != 'needs_owner'
                        or current.get('reason') != 'missing_profile_facts'
                        or current.get('package_hash') != expected['package_hash']
                        or current.get('session_id') != browser.get('target_id')
                        or current.get('owner_revision') != browser.get('owner_revision')
                        or current.get('page_url_sha256') != browser.get('page_url_sha256')):
                    raise ValueError('application_inputs_changed')
                # The manager now holds the preparation lock: owner browser
                # controls cannot race these explicit replies or the next fill.
                for ident, value in replies:
                    record_owner_answer(paths.data_dir(), aid, question_id=ident, value=value)
            run_id = uuid.uuid4().hex
            checkpoints = ensure_dir(paths.data_dir() / 'browser' / 'budgets')
            run_key = hashlib.sha256((package['run_key'] + run_id).encode()).hexdigest()
            batch = BatchBudget('browser-' + run_id, token_ceiling=runtime_config['batch_token_ceiling'],
                                deadline=time.time() + runtime_config['batch_seconds'])
            def persist(value, **kwargs):
                safe_write_text(checkpoints / (run_id + '.json'), value.model_dump_json())
                return value
            budget = JobBudget(run_key, batch, persist=persist, token_ceiling=runtime_config['job_token_ceiling'],
                               deadline=time.time() + runtime_config['job_seconds'])
            try:
                return prepare_application(page, application_id=aid, package_manifest=package['manifest'],
                    document_paths={'cv': Path(package['cv_pdf']), 'letter': Path(package['letter_pdf'])},
                    profile_root=paths.profile_dir(), data_root=paths.data_dir(), job=job,
                    budget=budget, llm=worker_llm, reviewer=reviewer_llm,
                    worker_model=runtime_config['answer_model'], reviewer_model=runtime_config['reviewer_model'],
                    allowed_hosts=[urlparse(page.url).hostname], owner_authorized=True)
            finally:
                batch.release(budget)
        try:
            sessions.prepare(aid, fill)
        except Exception:
            raise HTTPException(409, 'The application browser is busy or unavailable.') from None

    def auto_fill_ready():
        """Owner: 'it should be automatic'. Fill every READY job up to (never including) Submit."""
        conn = conn_factory()
        try:
            ids = [r[0] for r in conn.execute("SELECT DISTINCT posting_id FROM agentic_runs WHERE status='ready'")]
        except sqlite3.OperationalError:            # no agentic_runs table yet (nothing drafted): nothing is ready
            return
        finally:
            conn.close()
        for pid in ids:
            try:
                job, _ = context(pid)
                aid = job['application_id']
                if not aid or latest_preparation(paths.data_dir(), str(aid)) or not preparation_context(pid)['can_prepare']:
                    continue
                if not browser_status(str(aid))['open']:
                    sessions.open(str(aid), job['url'])
                start_preparation(pid)
            except Exception:
                continue

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
        state = preparation_context(posting_id)
        if state['browser']['automation_active']:
            raise HTTPException(409, 'Wait for preparation to finish before updating answers.')
        prepared = state['prepared'] or {}
        if (not prepared or prepared.get('status') != 'needs_owner'
                or prepared.get('reason') != 'missing_profile_facts'
                or not prepared.get('run_id') or form.get('preparation_run_id') != prepared['run_id']):
            raise HTTPException(400, 'These questions have changed. Refresh and try again.')
        questions = {item['question_id']: item for item in prepared.get('missing', [])}
        supplied = [(key[7:], value) for key, value in form.items() if key.startswith('answer_')]
        if not supplied or {ident for ident, _ in supplied} != set(questions):
            raise HTTPException(400, 'These questions have changed. Refresh and try again.')
        replies = []
        try:
            for ident, value in supplied:
                question = questions[ident]
                if question.get('type') == 'checkbox' or question.get('kind') == 'radio':
                    if value not in ('true', 'false'):
                        raise ValueError
                    value = value == 'true'
                elif question.get('multiple') or question.get('type') == 'select-multiple':
                    value = form.getlist('answer_' + ident)
                    if not value or len(set(value)) != len(value) or any(not item.strip() for item in value):
                        raise ValueError
                elif not isinstance(value, str) or not value.strip() or len(form.getlist('answer_' + ident)) != 1:
                    raise ValueError
                options = question.get('options') or []
                allowed = {str(option.get('value', option.get('label', ''))) if isinstance(option, dict) else str(option)
                           for option in options}
                selected = value if isinstance(value, list) else [value]
                if allowed and any(str(item) not in allowed for item in selected):
                    raise ValueError
                maximum = question.get('maxlength')
                if isinstance(value, str) and (len(value) > 8000 or type(maximum) is int and maximum > 0 and len(value) > maximum):
                    raise ValueError
                replies.append((ident, value))
        except Exception:
            raise HTTPException(400, 'Check each answer matches the available choices.') from None
        start_preparation(posting_id, intake=(dict(prepared), replies))
        return RedirectResponse(f'/job/{posting_id}/prepare', status_code=303)

    def confirmed_submit(posting_id, confirm, source):
        """Press final Submit for the fill the owner confirmed (board button or approved chat request). Returns None
        when pressed, else a fixed reason; nothing is pressed unless the live page still matches `confirm`."""
        state = preparation_context(posting_id)
        prepared = state['prepared']
        if state['browser']['automation_active'] or not confirm or submit_confirm.digest(prepared) != confirm:
            return 'submit_confirmation_stale'
        aid = str(state['job']['application_id'])
        conn = conn_factory()
        try:
            ledger.upsert(conn, 'applications', 'application_events', {
                'application_id': int(aid), 'at': dbm.ts(), 'kind': 'submit_confirmed', 'from_status': state['job']['status'],
                'to_status': None, 'actor': 'owner', 'source': source,
                'detail_json': json.dumps({'confirmation': confirm[:16], 'run_id': prepared['run_id']})})
        finally:
            conn.close()
        try:
            sessions.confirm_submit(aid, confirm, prepared)
        except BrowserSessionError as exc:
            return str(exc) if str(exc) in ('submit_confirmation_stale', 'submit_not_confirmable') else 'browser_unavailable'
        except Exception:
            return 'browser_unavailable'
        return None

    app.state.confirmed_submit = confirmed_submit

    @app.post('/job/{posting_id}/prepare/submit')
    async def prepare_submit(request: Request, posting_id: int):
        form = await request.form(max_fields=5)
        app_context(posting_id)
        reason = await run_in_threadpool(confirmed_submit, posting_id, str(form.get('digest') or ''), 'board')
        if reason:
            return render(request, 'prepare.html', status=409, **preparation_context(
                posting_id, 'Nothing was submitted: the application changed after you confirmed. Review the live page and confirm again.'))
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
        statistics = {"status": "input_unavailable"}
        outcomes = None
        try:
            from jobwatch.candidate.evidence import snapshot_evidence
            from jobwatch.candidate.presentation import statistical_view
            from jobwatch.outcomes.readiness import outcome_readiness
            outcomes = outcome_readiness(conn)
            try:
                from jobwatch.candidate.assessment import assessment_run_key
                from jobwatch.candidate.contracts import content_hash, digest
                from jobwatch.candidate.evidence import career_profile_text
                from jobwatch.candidate.policy import default_policy
                bundle = snapshot_evidence(paths.profile_dir())
                cfg = _config(config)
                statistics = statistical_view(bundle, cfg)
                candidate_key = assessment_run_key(bundle.bundle_hash,
                    content_hash(career_profile_text(bundle).encode()),
                    digest(default_policy().model_dump(mode='json')), statistics['run_key'], cfg['evaluator_model'])
            except Exception as exc:
                logging.getLogger(__name__).exception('candidate page: statistics failed')
                statistics = {'status': 'error', 'error': f'{type(exc).__name__}: {str(exc)[:200]}'}
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='agentic_runs'").fetchone():
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
                      profile_problems=profile_problems)

    @app.get('/job/{posting_id}/evaluation')
    def evaluation_page(request: Request, posting_id: int):
        job, package = context(posting_id)
        return render(request, 'evaluation.html', job=job, evaluation=package.get('evaluation') if package else None)
