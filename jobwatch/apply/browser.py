"""Shared application browser workflow, independent of either frontend."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import HTTPException

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



class BrowserService:

    def __init__(self, config, conn_factory, sessions):
        self.config, self.conn_factory, self.sessions = (config, conn_factory, sessions)

    def browser_status(self, aid):
        try:
            status = self.sessions.status(aid)
            return dict(status, open=status.get('state') == 'ready')
        except Exception:
            return {'open': False, 'automation_active': False}

    def context(self, posting_id):
        if not 0 < posting_id < 2 ** 63:
            raise HTTPException(404, 'No such application')
        conn = self.conn_factory()
        try:
            row = conn.execute('SELECT p.id,p.title,p.company,p.url,p.source,p.description,a.id AS application_id,a.status FROM postings p LEFT JOIN applications a ON a.posting_id=p.id WHERE p.id=?', (posting_id,)).fetchone()
            if row is None:
                raise HTTPException(404, 'No such application')
            job = dict(row)
            try:
                package = latest_result(conn, posting_id)
                if package is not None:
                    package = dict(package, inputs_current=package_is_current(conn, self.config, posting_id, package))
            except Exception:
                package = None
            return (job, package)
        finally:
            conn.close()

    def app_context(self, posting_id):
        job, package = self.context(posting_id)
        if not job['application_id']:
            raise HTTPException(409, 'Prepare the application documents first.')
        return (job, package)

    def settle_submit(self, posting_id, aid, result=None):
        """After Submit was pressed (by the owner, or for their confirmation): confident confirmation -> Applied (same
        write as the status select); unsure -> a 'submit_unsure' event, which the job page turns into a one-line question."""
        result = result or (self.sessions.take_submit_result(aid) if aid else None)
        if not result:
            return
        conn = self.conn_factory()
        try:
            row = conn.execute('SELECT id,status FROM applications WHERE posting_id=?', (posting_id,)).fetchone()
            if row is not None:
                submit_confirm.verdict(conn, row['id'], result)
            if row is None or row['status'] in (*SUBMITTED, 'hired'):
                return
            last = conn.execute('SELECT kind FROM application_events WHERE application_id=? ORDER BY id DESC LIMIT 1', (row['id'],)).fetchone()
            source = 'submit-confirmed' if last and last['kind'] == 'submit_confirmed' else 'submit-detected'
            if result == 'confident':
                act.set_status(conn, posting_id, 'applied', source=source)
            else:
                ledger.upsert(conn, 'applications', 'application_events', {'application_id': row['id'], 'at': dbm.ts(), 'kind': 'submit_unsure', 'from_status': row['status'], 'to_status': None, 'actor': 'jobwatch', 'source': source, 'detail_json': '{}'})
        finally:
            conn.close()

    def preparation_context(self, posting_id, error=''):
        job, package = self.context(posting_id)
        aid = str(job['application_id']) if job['application_id'] else None
        if aid:
            self.settle_submit(posting_id, aid)
            job, package = self.context(posting_id)
        browser = self.browser_status(aid)
        prepared = latest_preparation(paths.data_dir(), aid) if aid else None
        if prepared and package and package.get('manifest'):
            package_hash = hashlib.sha256(json.dumps(package['manifest'], sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
            if prepared.get('package_hash') != package_hash:
                prepared = None
        can_prepare = bool(package and package.get('inputs_current') and (package.get('status') == 'ready') and package.get('manifest') and package.get('cv_pdf') and package.get('letter_pdf') and (job['status'] not in (*SUBMITTED, 'hired', 'rejected')))
        if not can_prepare:
            prepared = None
        if prepared and (not browser['open'] or browser.get('last_error') or prepared.get('session_id') != browser.get('target_id') or (prepared.get('owner_revision') != browser.get('owner_revision')) or (prepared.get('page_url_sha256') != browser.get('page_url_sha256'))):
            prepared = None
        return dict(job=job, package=package, browser=browser, prepared=prepared, can_prepare=can_prepare, confirm_digest=submit_confirm.digest(prepared) if browser['open'] else None, error=error)

    def start_preparation(self, posting_id, *, intake=None):
        job, package = self.app_context(posting_id)
        if not self.preparation_context(posting_id)['can_prepare']:
            raise HTTPException(409, 'A verified application package is needed before filling.')
        aid = str(job['application_id'])
        if not self.browser_status(aid)['open']:
            raise HTTPException(409, 'Open the application browser first.')
        try:
            worker_llm, reviewer_llm = (configured_llm(self.config), configured_llm(self.config))
            runtime_config = _config(self.config)
        except Exception:
            raise HTTPException(503, 'The configured model connection is unavailable.')

        def fill(page):
            current_job, current_package = self.context(posting_id)
            if not current_package or not current_package.get('inputs_current') or current_package.get('status') != 'ready' or (current_package['run_key'] != package['run_key']):
                raise ValueError('application_inputs_changed')
            if intake is not None:
                expected, replies = intake
                current = latest_preparation(paths.data_dir(), aid) or {}
                browser = self.browser_status(aid)
                if current.get('run_id') != expected['run_id'] or current.get('status') != 'needs_owner' or current.get('reason') != 'missing_profile_facts' or (current.get('package_hash') != expected['package_hash']) or (current.get('session_id') != browser.get('target_id')) or (current.get('owner_revision') != browser.get('owner_revision')) or (current.get('page_url_sha256') != browser.get('page_url_sha256')):
                    raise ValueError('application_inputs_changed')
                for ident, value in replies:
                    record_owner_answer(paths.data_dir(), aid, question_id=ident, value=value)
            run_id = uuid.uuid4().hex
            checkpoints = ensure_dir(paths.data_dir() / 'browser' / 'budgets')
            run_key = hashlib.sha256((package['run_key'] + run_id).encode()).hexdigest()
            batch = BatchBudget('browser-' + run_id, token_ceiling=runtime_config['batch_token_ceiling'], deadline=time.time() + runtime_config['batch_seconds'])

            def persist(value, **kwargs):
                safe_write_text(checkpoints / (run_id + '.json'), value.model_dump_json())
                return value
            budget = JobBudget(run_key, batch, persist=persist, token_ceiling=runtime_config['job_token_ceiling'], deadline=time.time() + runtime_config['job_seconds'])
            try:
                return prepare_application(page, application_id=aid, package_manifest=package['manifest'], document_paths={'cv': Path(package['cv_pdf']), 'letter': Path(package['letter_pdf'])}, profile_root=paths.profile_dir(), data_root=paths.data_dir(), job=job, budget=budget, llm=worker_llm, reviewer=reviewer_llm, worker_model=runtime_config['answer_model'], reviewer_model=runtime_config['reviewer_model'], allowed_hosts=[urlparse(page.url).hostname], owner_authorized=True)
            finally:
                batch.release(budget)
        try:
            self.sessions.prepare(aid, fill)
        except Exception:
            raise HTTPException(409, 'The application browser is busy or unavailable.') from None

    def auto_fill_ready(self):
        """Owner: 'it should be automatic'. Fill every READY job up to (never including) Submit."""
        conn = self.conn_factory()
        try:
            ids = [r[0] for r in conn.execute("SELECT DISTINCT posting_id FROM agentic_runs WHERE status='ready'")]
        except sqlite3.OperationalError:
            return
        finally:
            conn.close()
        for pid in ids:
            try:
                job, _ = self.context(pid)
                aid = job['application_id']
                if not aid or latest_preparation(paths.data_dir(), str(aid)) or (not self.preparation_context(pid)['can_prepare']):
                    continue
                if not self.browser_status(str(aid))['open']:
                    self.sessions.open(str(aid), job['url'])
                self.start_preparation(pid)
            except Exception:
                continue

    def confirmed_submit(self, posting_id, confirm, source):
        """Press final Submit for the fill the owner confirmed (board button or approved chat request). Returns None
        when pressed, else a fixed reason; nothing is pressed unless the live page still matches `confirm`."""
        state = self.preparation_context(posting_id)
        prepared = state['prepared']
        if not state['browser']['open']:
            return 'browser_closed'
        if state['browser']['automation_active'] or not confirm or submit_confirm.digest(prepared) != confirm:
            return 'submit_confirmation_stale'
        aid = str(state['job']['application_id'])
        try:
            self.sessions.confirm_submit(aid, confirm, prepared)
        except BrowserSessionError as exc:
            return str(exc) if str(exc) in REFUSALS else 'press_unknown'
        except Exception:
            return 'press_unknown'
        conn = self.conn_factory()
        try:
            ledger.upsert(conn, 'applications', 'application_events', {'application_id': int(aid), 'at': dbm.ts(), 'kind': 'submit_confirmed', 'from_status': state['job']['status'], 'to_status': None, 'actor': 'owner', 'source': source, 'detail_json': json.dumps({'confirmation': confirm[:16], 'run_id': prepared['run_id']})})
        finally:
            conn.close()
        return None

    def process_submit_requests(self):
        """Chat-approved Submits (submit_confirm.submit_requests, queued by the agent API): pressed only through
        confirmed_submit's live check, then the page is watched and the outcome recorded for submit_status."""
        conn = self.conn_factory()
        try:
            rows = submit_confirm.pending(conn)
        except sqlite3.Error:
            return
        finally:
            conn.close()
        for row in rows:
            status, reason = ('refused', None)
            try:
                job, _ = self.context(row['posting_id'])
                if time.time() >= row['expires_at']:
                    status = 'expired'
                elif job['application_id'] != row['application_id']:
                    reason = 'application_changed'
                else:
                    reason = self.confirmed_submit(row['posting_id'], row['digest'], 'agent-api')
                    if reason is None:
                        status = 'pressed'
                    elif reason == 'press_unknown':
                        status = 'unsure'
            except Exception:
                reason = reason or 'submit_failed'
            conn = self.conn_factory()
            try:
                submit_confirm.settle(conn, row['id'], status, reason)
            finally:
                conn.close()

    def settle_open_sessions(self):
        """Record a Submit seen in an open browser even when no prepare page is polling (the page used to be the only
        place settle_submit ran)."""
        for aid in getattr(self.sessions, 'open_applications', lambda: [])():
            conn = self.conn_factory()
            try:
                row = conn.execute('SELECT posting_id FROM applications WHERE id=?', (int(aid),)).fetchone()
            finally:
                conn.close()
            if row is not None:
                self.settle_submit(row['posting_id'], aid)

    def review(self, posting_id, *, expected=None):
        """Read live fields; explicitly rebind a corrected form only to the snapshot the human saw."""
        from jobwatch.apply.prepare import record_owner_review
        from jobwatch.apply.submit_confirm import form_state, record_control
        job, package = self.app_context(posting_id)
        aid = str(job['application_id'])
        prepared = latest_preparation(paths.data_dir(), aid)
        with self.conn_factory() as conn:
            current_package = bool(package and package_is_current(conn, self.config, posting_id, package))
        conn.close()
        if not prepared or not current_package:
            raise HTTPException(409, 'application_not_ready')
        manifest_hash = hashlib.sha256(json.dumps(package['manifest'], sort_keys=True,
            separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        if prepared.get('package_hash') != manifest_hash or prepared.get('status') != 'ready_for_owner':
            raise HTTPException(409, 'application_not_ready')
        def capture(page):
            status = self.sessions.status(aid)
            if (status.get('target_id') != prepared.get('session_id') or
                    status.get('page_url_sha256') != prepared.get('page_url_sha256')):
                raise HTTPException(409, 'application_changed')
            control = record_control(page, prepared['final_control'])
            if control != prepared['final_control']:
                raise HTTPException(409, 'final_control_changed')
            before = form_state(page)
            fields = []
            for frame in page.frames:
                try:
                    if frame.locator('[contenteditable="true"], [role="combobox"]:not(input):not(select)').count():
                        raise HTTPException(409, 'unsupported_form_review')
                    rows = frame.evaluate('''() => Array.from(document.querySelectorAll('input,select,textarea'))
                      .filter(e=>e.type!=='hidden'&&!/^(g-recaptcha|h-captcha|cf-turnstile)-response$/.test(e.name||e.id||''))
                      .map(e=>({label:(e.labels?.[0]?.innerText||e.getAttribute('aria-label')||e.name||e.id||e.tagName).slice(0,500),
                        type:e.type||e.tagName,value:e.type==='password'?'[private]':
                        (e.type==='checkbox'||e.type==='radio')?(e.checked?'Selected':'Not selected'):
                        e.type==='file'?Array.from(e.files||[]).map(f=>f.name).join(', '):
                        e.tagName==='SELECT'?Array.from(e.selectedOptions).map(o=>o.textContent).join(', '):e.value||''}))''')
                except HTTPException:
                    raise
                except Exception:
                    raise HTTPException(409, 'form_review_unavailable') from None
                fields.extend(rows)
            if len(fields) > 500 or sum(len(str(v['value'])) for v in fields) > 100000 or before != form_state(page):
                raise HTTPException(409, 'form_review_changed')
            current = dict(prepared, owner_revision=status['owner_revision'], form_state=before)
            digest = submit_confirm.digest(current)
            if not digest:
                raise HTTPException(409, 'submit_not_confirmable')
            if expected is not None:
                if expected != digest:
                    raise HTTPException(409, 'form_review_changed')
                record_owner_review(paths.data_dir(),aid,expected=prepared,current=current)
            return {'posting_id': posting_id, 'employer': job['company'], 'title': job['title'], 'url': page.url,
                    'fields': fields, 'documents': prepared['attached_documents'], 'review_digest': digest,
                    'confirmed_digest': digest if expected is not None or submit_confirm.digest(prepared) == digest else None}
        def inspected(page):
            # Browser task failures deliberately hide exception details. Carry only our fixed
            # refusal codes across that boundary, never page content or arbitrary exceptions.
            try:
                return capture(page)
            except HTTPException as exc:
                return {'status':'blocked','reason':exc.detail}
        result = self.sessions.with_page(aid, inspected, timeout=30)
        if expected is not None and result.get('status') == 'blocked':
            raise HTTPException(409,result['reason'])
        return result


    def answer_missing(self, posting_id, form):
        state = self.preparation_context(posting_id)
        if state['browser']['automation_active']:
            raise HTTPException(409, 'Wait for preparation to finish before updating answers.')
        prepared = state['prepared'] or {}
        if not prepared or prepared.get('status') != 'needs_owner' or prepared.get('reason') != 'missing_profile_facts' or (not prepared.get('run_id')) or (form.get('preparation_run_id') != prepared['run_id']):
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
                    if not value or len(set(value)) != len(value) or any((not item.strip() for item in value)):
                        raise ValueError
                elif not isinstance(value, str) or not value.strip() or len(form.getlist('answer_' + ident)) != 1:
                    raise ValueError
                options = question.get('options') or []
                allowed = {str(option.get('value', option.get('label', ''))) if isinstance(option, dict) else str(option) for option in options}
                selected = value if isinstance(value, list) else [value]
                if allowed and any((str(item) not in allowed for item in selected)):
                    raise ValueError
                maximum = question.get('maxlength')
                if isinstance(value, str) and (len(value) > 8000 or (type(maximum) is int and maximum > 0 and (len(value) > maximum))):
                    raise ValueError
                replies.append((ident, value))
        except Exception:
            raise HTTPException(400, 'Check each answer matches the available choices.') from None
        self.start_preparation(posting_id, intake=(dict(prepared), replies))
