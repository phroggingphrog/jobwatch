"""The jobwatch web board: FastAPI + Jinja2 + HTMX, loopback only (PLAN-web.md, BUI-91).

Reads go through `queries.py`, writes through `actions.py` (which use the ledger / state APIs).
Template contexts are listed in `web/CONTRACT.md`; keep that file true when you change a route.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import math
import os
import re
import sqlite3
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pipeline import store as pstore

from .. import db as dbm
from .. import users
from ..apply import paths as apaths
from ..config import Config, load_config
from ..origin_guard import OriginRejected, check_web_host, check_web_post
from . import actions as act
from . import queries as q

HERE = Path(__file__).resolve().parent
FILE_NAMES = {"cv.pdf": "application/pdf", "letter.pdf": "application/pdf", "summary.md": "text/markdown"}
CSP = ("default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; script-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
TABLE_COLS = [("ai_fit", "Score"), ("archetype", "Archetype"), ("ai_view", "AI view"), ("fit", "Fit /100"),
              ("title", "Title"), ("company", "Company"), ("location", "Location"),
              ("arm", "Job type"), ("tier", "Tier"), ("sector", "Sector"), ("sources", "Sources"),
              ("wt", "Work type"), ("salary", "Salary"), ("listed", "Listed"), ("first_seen", "First seen"),
              ("flags", "Flags"), ("status", "Status")]
DEFAULT_COLS = ["ai_fit", "title", "company", "archetype", "location", "salary", "listed", "status", "ai_view"]
CSV_SAFE = re.compile(r"^[=+\-@\t\r]")
MAX_ID = 2**63 - 1                  # SQLite INTEGER: a bigger id would raise OverflowError, not find nothing


def _page_no(v) -> int:
    """A page number from the query string: ASCII digits only, anything else is page 1, huge is the last page."""
    v = (v or "").strip()
    if not (v.isascii() and v.isdigit()):
        return 1
    return int(v) if len(v) <= 18 else 10**18


def create_app(config: Config | None = None) -> FastAPI:
    config = config or load_config()
    db_path = config.db_path
    reg = q.Registry(lambda: config)

    c0 = dbm.connect(db_path)                          # migrate once at start-up
    pstore.ensure(c0)                                  # the pipeline's tables (the board reads pipeline_state)
    from jobwatch.preferences import PreferenceStore
    PreferenceStore(c0).ensure()
    c0.close()

    from .browser_session import BrowserSessionManager
    from .prepare_routes import register as register_preparation
    from jobwatch.apply.browser_remote import RemoteBrowserSessions
    sessions = RemoteBrowserSessions() if os.environ.get('JOBWATCH_NATIVE_BROWSER_URL') else BrowserSessionManager()

    def for_each_person(fn):
        """Run background work once per person, as that person (their DB, folders and browser sessions)."""
        for name in users.list_users():
            if name != users.DEFAULT_USER and not users.db_path(name).exists():
                continue                            # never create a DB from a background loop
            try:
                with users.use(name):
                    fn()
            except Exception:                       # one person's failure never stops the others
                logging.getLogger(__name__).exception("background work failed for one person")

    @asynccontextmanager
    async def lifespan(app):
        async def recover_interviews():
            from jobwatch.interview_prep import queued_posting_ids, queued_subject_ids
            from pipeline.agentic.contracts import AgenticError
            from jobwatch.candidate.contracts import CandidateError
            def schedule(pending):
                conn = conn_()
                try:
                    for posting_id in (*queued_posting_ids(conn, config), *queued_subject_ids(conn, config)):
                        try: queue_interview(posting_id, pending, existing_only=True)
                        except HTTPException: pass  # Changed or unavailable sources stay private.
                except (AgenticError, CandidateError, sqlite3.Error, OSError):
                    pass
                finally: conn.close()
            for name in users.list_users():     # each person's own queue, run as that person (their DB, profile and drafts)
                if name != users.DEFAULT_USER and not users.db_path(name).exists(): continue   # never create a DB here
                try:
                    with users.use(name):
                        pending = BackgroundTasks()
                        await asyncio.to_thread(schedule, pending)
                        await pending()
                except Exception:
                    logging.getLogger(__name__).exception("interview recovery failed for one person")
        async def auto_fill_loop():
            while True:
                await asyncio.sleep(60)
                try:
                    await asyncio.to_thread(for_each_person, app.state.auto_fill_ready)
                except Exception:                  # one bad tick (locked db, missing table) must not end auto-fill for good
                    logging.getLogger(__name__).exception("auto-fill tick failed")
        async def submit_loop():
            while True:                            # approved chat Submits and Submits seen with no prepare page open
                await asyncio.sleep(5)
                try:
                    await asyncio.to_thread(for_each_person, app.state.process_submit_requests)
                    await asyncio.to_thread(for_each_person, app.state.settle_open_sessions)
                except Exception:
                    logging.getLogger(__name__).exception("submit tick failed")
        recovery = asyncio.create_task(recover_interviews())
        filler = asyncio.create_task(auto_fill_loop())
        submitter = asyncio.create_task(submit_loop())
        try:
            yield
        finally:
            filler.cancel()
            submitter.cancel()
            try:
                await recovery
            finally:
                sessions.close_all()

    app = FastAPI(title="jobwatch", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.for_each_person = for_each_person
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    env = templates.env
    def safe_url(u):
        """Only http(s) links are ever rendered as hrefs (no javascript: or data: from a posting)."""
        return u if isinstance(u, str) and u[:8].lower() == "https://" or (
            isinstance(u, str) and u[:7].lower() == "http://") else "#"

    def interview_source_url(value):
        from urllib.parse import urlsplit
        import ipaddress
        if not isinstance(value, str) or any(ord(c) < 33 for c in value): return ''
        try:
            parsed = urlsplit(value)
            host = parsed.hostname or ''
            if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443): return ''
            if not host or '.' not in host or host.endswith(('.local', '.localhost')): return ''
            try:
                if not ipaddress.ip_address(host).is_global: return ''
            except ValueError: pass
            return value
        except ValueError: return ''

    env.filters['interview_source_url'] = interview_source_url
    env.filters["safe_url"] = safe_url
    env.globals.update(
        ago=q.ago, absolute=q.absolute, short_location=q.short_location, commute_km=q.commute_km, salary_display=q.salary_display,
        arm_label=q.arm_label, src_label=q.src_label, flag_label=q.flag_label, STATE_LABEL=q.STATE_LABEL,
        WORK_TYPES=q.WORK_TYPES, WITHIN=q.WITHIN, TABS=q.TABS, STATUS_RAIL=q.STATUS_RAIL, SORTS=q.SORTS,
        WARN=q.WARN, APP_STATES=q.APP_STATES, TABLE_COLS=TABLE_COLS, SOURCE_LABEL=q.SOURCE_LABEL,
        AI_VIEWS=q.AI_VIEWS, HIDE_REASONS=q.HIDE_REASONS, RIGHTS_TEXT=q.RIGHTS_TEXT, SENIORITY_TEXT=q.SENIORITY_TEXT,
        AD_KIND_LABEL=q.AD_KIND_LABEL, BLOCKING_RIGHTS=q.BLOCKING_RIGHTS, hide_label=q.hide_label,
        hide_sentence=q.hide_sentence, ai_view_text=q.ai_view_text, row_ai_text=q.row_ai_text,
        score_display=q.score_display, score_label=q.score_label, score_class=q.score_class,
        SCORE_FLOORS=q.SCORE_FLOORS, SCORE_FLOOR_LABEL=q.SCORE_FLOOR_LABEL, HOURS_TEXT=q.HOURS_TEXT,
        WORK_MODE_TEXT=q.WORK_MODE_TEXT, LOCATION_TEXT=q.LOCATION_TEXT, IMPORTANCE_TEXT=q.IMPORTANCE_TEXT,
        TIER_TEXT=q.TIER_TEXT, TIER_WHY=q.TIER_WHY, MATCH_TEXT=q.MATCH_TEXT, REC_TEXT=q.REC_TEXT, REC_WORDS=q.REC_WORDS, rec_key=q.rec_key,
        LEGIT_TEXT=q.LEGIT_TEXT, DIM_LABEL=q.DIM_LABEL)

    def conn_():
        c = sqlite3.connect(str(config.db_path), timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=30000")
        c.execute("PRAGMA foreign_keys=ON")
        return c

    # -- guards ------------------------------------------------------------------------------------
    @app.middleware("http")
    async def guard(request: Request, call_next):
        site, mode = request.headers.get("sec-fetch-site"), request.headers.get("sec-fetch-mode")
        if site == "cross-site" and mode != "navigate":        # another site's img/fetch/form: never ours
            return PlainTextResponse("forbidden: cross-site request", status_code=403)
        try:
            check_web_host(dict(request.headers))
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                check_web_post(dict(request.headers))
        except OriginRejected as exc:
            return PlainTextResponse(f"forbidden: {exc}", status_code=403)
        resp = await call_next(request)
        resp.headers["Content-Security-Policy"] = CSP  # every page uses the app's own fonts
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    from .auth_routes import install_auth; install_auth(app)   # sign-in (off unless JOBWATCH_SESSION_SECRET)

    # -- helpers -----------------------------------------------------------------------------------
    def hx(request: Request) -> bool:
        return request.headers.get("hx-request") == "true"

    def render(request: Request, name: str, conn=None, status: int = 200, **ctx) -> HTMLResponse:
        base = {"nav": q.nav_counts(conn) if conn is not None else {}, "now": datetime.now(UTC),
                "path": request.url.path}
        return templates.TemplateResponse(request, name, {**base, **ctx}, status_code=status)

    def one_row(conn, posting_id: int) -> dict | None:
        rows = q.load_rows(conn, "all", ids=[posting_id], reg=reg.refresh())
        if rows:
            q.add_teasers(conn, rows)
        return rows[0] if rows else None

    def filtered(conn, f: q.Filters):
        rows = q.load_rows(conn, f.scope, f.q, f.x, reg=reg.refresh())
        rows, counts = q.apply_filters(rows, f)
        return q.sort_rows(rows, f.sort, f.dir), counts

    def page_of(rows: list, page: int, size: int):
        pages = max(1, math.ceil(len(rows) / size))
        page = min(max(1, page), pages)
        return rows[(page - 1) * size: page * size], page, pages

    def ok_id(n: int) -> int:
        """A row id from the URL: anything SQLite cannot hold, or below 1, is simply 'not there' (404)."""
        if not 1 <= n <= MAX_ID:
            raise HTTPException(404, "No such item")
        return n

    def job_ctx(conn, posting_id: int) -> dict:
        ok_id(posting_id)
        d = q.job_detail(conn, posting_id, reg.refresh())
        if d is None:
            raise HTTPException(404, "No such job")
        from pipeline.agentic import jev_skills
        jev = {"fit": jev_skills.latest(conn, posting_id, "fit"),
               "requirements": jev_skills.latest(conn, posting_id, "requirements")}
        return {"job": d, "app": d["app"], "draft": act.draft_state(conn, posting_id),
                "files_ok": bool(d["app"]), "jev": jev}

    # -- board -------------------------------------------------------------------------------------
    app.state.browser_sessions = sessions
    register_preparation(app, config, conn_, render, sessions)
    from .accounts_routes import register as register_accounts
    register_accounts(app, config, conn_, render, sessions)
    from .preference_routes import register as register_preferences
    register_preferences(app, config, conn_, render)
    from .answers_routes import register as register_answers
    register_answers(app, config, conn_, render)
    from .models_routes import register as register_models
    register_models(app, config, conn_, render)
    from .chat_routes import register as register_chat
    register_chat(app, config, conn_, render)
    from .onboarding_routes import register as register_onboarding
    register_onboarding(app, config, conn_, render)
    from .google_routes import register as register_google
    register_google(app, config, conn_, render)
    APP_SHELL = Path(__file__).resolve().parent / "static" / "app" / "index.html"

    @app.get("/app", response_class=HTMLResponse)
    def app_preview():
        """The rebuilt app before it takes over "/" (JOBWATCH_UI=app)."""
        return FileResponse(APP_SHELL, media_type="text/html", headers={"Cache-Control": "no-store"})

    @app.get("/pebble")
    def old_pebble_link():
        return RedirectResponse("/", status_code=308)

    @app.get("/", response_class=HTMLResponse)
    def board(request: Request):
        """The app: the shared shell (base.html) with the single-page views drawn into it by static/v3/v3.js."""
        return render(request, "app.html", None)

    @app.get("/old", response_class=HTMLResponse)
    def old_board():
        return FileResponse(APP_SHELL, media_type="text/html", headers={"Cache-Control": "no-store"})

    # Old server-rendered pages: their place in the app (GET only; the pages are gone).
    @app.get("/classic")
    def old_classic():
        return RedirectResponse("/", status_code=307)

    @app.get("/table")
    def old_table():
        return RedirectResponse("/#table", status_code=307)

    @app.get("/applications")
    def old_applications():
        return RedirectResponse("/#applications", status_code=307)

    @app.get("/job/{posting_id}")
    def old_job(posting_id: int):
        return RedirectResponse(f"/#job/{posting_id}", status_code=307)

    @app.get("/job/{posting_id}/pane")
    def old_job_pane(posting_id: int):
        return RedirectResponse(f"/#job/{posting_id}", status_code=307)

    @app.get("/s/{search_id}")
    def open_search(search_id: int):
        ok_id(search_id)
        conn = conn_()
        try:
            row = conn.execute("SELECT query_json FROM saved_searches WHERE id=?", (search_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "No such saved search")
            import json
            f = q.Filters.from_params(json.loads(row["query_json"] or "{}"))
            act.touch_search(conn, search_id)
            return RedirectResponse("/?" + f.query(), status_code=303)
        finally:
            conn.close()

    def run_job_action(conn, posting_id: int, action: str, status: str, notes: str, background_tasks) -> str:
        """One place for every job action, used by the classic page and the JSON API alike."""
        if action == "save":
            return act.save(conn, posting_id)[1]
        if action == "hide":
            act.hide(conn, posting_id)
            return "Hidden"
        if action == "unhide":
            act.set_status(conn, posting_id, "interested")
            return "Moved back to Saved"
        if action == "applied":
            act.set_status(conn, posting_id, "applied")
            return "Marked applied"
        if action == "status":
            act.set_status(conn, posting_id, status)
            if status == "interview":
                maybe_queue_interview(conn, posting_id, background_tasks)
            return f"Status: {q.STATE_LABEL.get(status, status)}"
        if action == "notes":
            act.set_notes(conn, posting_id, notes)
            return "Notes saved"
        if action == "draft":
            act.start_draft(conn, config.db_path, posting_id, config=config)
            return "Drafting your CV and letter… this takes a few minutes"
        raise HTTPException(404, "Unknown action")

    # -- table -------------------------------------------------------------------------------------
    @app.get("/table.csv")
    def table_csv(request: Request):
        conn = conn_()
        try:
            f = q.Filters.from_params(request.query_params)
            rows, _ = filtered(conn, f)
        finally:
            conn.close()

        def safe(v):
            s = "" if v is None else str(v)
            return "'" + s if CSV_SAFE.match(s) else s

        def gen():
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["id", "title", "company", "location", "job type", "tier", "sector", "sources",
                        "work type", "salary", "listed", "first seen", "flags", "status", "score", "archetype",
                        "recommendation", "ai view", "ai reason", "url"])
            yield buf.getvalue()
            for r in rows:
                buf.seek(0)
                buf.truncate()
                w.writerow([safe(x) for x in (
                    r["id"], r["title"], r["company"], q.short_location(r["location"]), q.arm_label(r["arm"]),
                    r["tier"], r["sector"], " ".join(q.src_label(s) for s in r["srcs"]), r["wt"],
                    q.salary_display(r), q.absolute(r["posted_at"] or r["first_seen_at"]), r["first_seen_at"],
                    " ".join(q.flag_label(x) for x in r["flags"]), r["status"],
                    r["score_text"] if r["score5"] is not None else "", r["archetype"],
                    q.REC_WORDS.get(q.rec_key(r), ""),
                    q.row_ai_text(r), r["ai"]["reason"] if r["ai"] else "", r["url"])])
                yield buf.getvalue()
        return StreamingResponse(gen(), media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": 'attachment; filename="jobwatch-jobs.csv"'})

    # -- applications ------------------------------------------------------------------------------
    def kanban_ctx(conn) -> dict:
        apps = q.applications(conn, apaths.drafts_dir())
        cols = [(s, q.STATE_LABEL[s], [a for a in apps if a["status"] == s]) for s in q.KANBAN]
        drafting = [a for a in apps if a["status"] == "drafting"]
        if drafting and cols:
            cols[1] = (cols[1][0], cols[1][1], drafting + cols[1][2])      # 'Drafting' shows in Drafted
        closed = [a for a in apps if a["status"] in q.KANBAN_CLOSED]
        from pipeline.agentic.service import enabled
        return {"followup_drafting_enabled": enabled(config), "cols": cols, "closed": closed, "total": len(apps),
                "agentic_items": [a for a in apps if a.get("agentic")]}

    followup_active = set()
    followup_lock = threading.Lock()

    @app.get('/applications/{posting_id}/followup-draft', response_class=HTMLResponse)
    def followup_draft_page(request: Request, posting_id: int, channel: str = "email"):
        from jobwatch.followup_drafts import load_draft
        if channel not in {'email','linkedin'}: raise HTTPException(status_code=422)
        from pipeline.agentic.service import enabled
        from pipeline.agentic.contracts import AgenticError
        from jobwatch.followup_events import FollowupEventError
        from jobwatch.candidate.contracts import CandidateError
        ok_id(posting_id)
        conn = conn_()
        try:
            row = conn.execute('SELECT a.id,p.title,p.company FROM applications a JOIN postings p ON p.id=a.posting_id WHERE p.id=?',(posting_id,)).fetchone()
            if row is None: raise HTTPException(status_code=404)
            state = {'status':'disabled','draft':None,'reason':None}
            if enabled(config):
                try:
                    state = load_draft(conn,row['id'],channel=channel)
                    with followup_lock:
                        if state['status'] == 'missing' and users.scoped(row['id'],channel) in followup_active:
                            state = {'status':'running','draft':None,'reason':None}
                except (AgenticError,FollowupEventError,CandidateError): state = {'status':'unavailable','draft':None,'reason':None}
            name = '_followup_draft_status.html' if hx(request) else 'followup_draft.html'
            return render(request,name,conn,posting_id=posting_id,job=dict(row),draft_state=state,channel=channel)
        finally: conn.close()

    @app.post('/applications/{posting_id}/followup-draft')
    def followup_draft_start(request: Request, posting_id: int, background_tasks: BackgroundTasks, channel: str = Form("email"), retry: bool = Form(False)):
        from jobwatch.followup_drafts import capture, generate
        if channel not in {'email','linkedin'}: raise HTTPException(status_code=422)
        from jobwatch.candidate.evidence import snapshot_evidence
        from pipeline.agentic.service import enabled
        from pipeline.agentic.contracts import AgenticError
        from jobwatch.followup_events import FollowupEventError
        from jobwatch.candidate.contracts import CandidateError
        ok_id(posting_id)
        if not enabled(config): raise HTTPException(status_code=409,detail='Follow-up drafting is not enabled.')
        conn = conn_()
        try:
            row=conn.execute('SELECT id FROM applications WHERE posting_id=?',(posting_id,)).fetchone()
            if row is None:raise HTTPException(status_code=404)
            application_id=row['id']
            try: capture(conn,application_id,snapshot_evidence(apaths.profile_dir()),channel=channel)
            except (AgenticError,FollowupEventError,CandidateError):
                raise HTTPException(status_code=409,detail='Confirm the application dates, current job ad and profile before drafting.') from None
        finally:conn.close()
        key=users.scoped(application_id,channel)      # application ids are per-person too
        with followup_lock:
            if key in followup_active:
                return RedirectResponse(f'/applications/{posting_id}/followup-draft?channel={channel}',status_code=303)
            followup_active.add(key)
        def work():
            c=None
            try:
                c=conn_()
                generate(c,application_id,config,channel=channel,retry=retry)
            except Exception:
                # Public state comes from the durable record or a fresh source check.
                # Never expose private provider/validation exception text.
                pass
            finally:
                if c is not None: c.close()
                with followup_lock: followup_active.discard(key)
        background_tasks.add_task(work)
        return RedirectResponse(f'/applications/{posting_id}/followup-draft?channel={channel}',status_code=303)

    interview_active = set()
    interview_lock = threading.Lock()
    interview_fields = (
        ('invite', 'Interview invite'), ('panelist_profiles', 'Panelist profiles you supplied'),
        ('story_bank', 'Your story bank'), ('prior_compensation', 'Previously stated compensation'),
        ('coffee_chat', 'Coffee-chat notes'), ('prior_round_notes', 'Prior-round notes'))
    interview_labels = {'reported': 'Reported', 'jd_inference': 'JD-derived inference',
        'inference': 'Inference', 'advice': 'Advice', 'unknown': 'Unknown',
        'candidate': 'Primary candidate evidence', 'anecdote': 'Owner anecdote'}

    def interview_url(reference):
        return f'/interview-prep/subjects/{reference}' if type(reference) is str else f'/jobs/{reference}/interview-prep'

    def interview_job(conn, posting_id):
        if type(posting_id) is str:
            from jobwatch.interview_subjects import load_subject
            from pipeline.agentic.contracts import AgenticError
            try:subject=load_subject(conn,posting_id)
            except AgenticError:raise HTTPException(status_code=404) from None
            ad=subject['ad']
            return {'id':posting_id,'title':ad.title,'company':ad.company,'jd_source':{'owner_supplied':'Saved description supplied by you','structured_ats':'Structured employer job record','browser':'Browser-verified visible description'}.get(ad.acquisition,ad.acquisition),'standalone':True,'ad_text':ad.text,'source_url':ad.source_url,'acquired_at':ad.acquired_at}
        ok_id(posting_id)
        row = conn.execute('SELECT id,title,company FROM postings WHERE id=?', (posting_id,)).fetchone()
        if row is None: raise HTTPException(status_code=404)
        return dict(row)

    def interview_state(conn, posting_id):
        from jobwatch.interview_prep import load_report
        from pipeline.agentic.service import enabled
        from pipeline.agentic.contracts import AgenticError
        from jobwatch.candidate.contracts import CandidateError
        state = {'status': 'disabled', 'report': None}
        if enabled(config):
            try:
                state = load_report(conn, posting_id, config)
                if state['status'] == 'queued': state = {'status': 'running', 'report': None}
                with interview_lock:
                    if state['status'] == 'missing' and users.scoped(posting_id) in interview_active:
                        state = {'status': 'running', 'report': None}
            except (AgenticError, CandidateError):
                state = {'status': 'unavailable', 'report': None}
        return state

    @app.get('/jobs/{posting_id}/interview-prep', response_class=HTMLResponse)
    def interview_page(request: Request, posting_id: int):
        from jobwatch.interview_inputs import load_inputs
        from pipeline.agentic.contracts import AgenticError
        conn = conn_()
        try:
            job = interview_job(conn, posting_id)
            try:
                if type(posting_id) is str:
                    from jobwatch.interview_subjects import load_subject
                    subject=load_subject(conn,posting_id)
                    inputs,revision=subject['inputs'],subject['revision']
                else:inputs, revision = load_inputs(conn, posting_id)
            except AgenticError:
                raise HTTPException(status_code=409, detail='Private interview notes need verification.') from None
            state = interview_state(conn, posting_id)
            return render(request, '_interview_prep_status.html' if hx(request) else 'interview_prep.html', conn,
                posting_id=posting_id, prep_url=interview_url(posting_id), job=job, prep_state=state, inputs=inputs.model_dump(), revision=revision,
                input_fields=interview_fields, kind_labels=interview_labels)
        finally: conn.close()

    @app.post('/jobs/{posting_id}/interview-prep/inputs')
    def interview_save_inputs(posting_id: int, revision: int = Form(...), invite: str = Form(''),
            panelist_profiles: str = Form(''), story_bank: str = Form(''), prior_compensation: str = Form(''),
            coffee_chat: str = Form(''), prior_round_notes: str = Form('')):
        from jobwatch.interview_inputs import InterviewInputs, save_inputs
        from pipeline.agentic.contracts import AgenticError
        from pydantic import ValidationError
        conn = conn_()
        try:
            interview_job(conn, posting_id)
            try:
                value = InterviewInputs(invite=invite, panelist_profiles=panelist_profiles, story_bank=story_bank,
                    prior_compensation=prior_compensation, coffee_chat=coffee_chat, prior_round_notes=prior_round_notes)
                if type(posting_id) is str:
                    from jobwatch.interview_subjects import save_subject_inputs
                    save_subject_inputs(conn,posting_id,value,expected_revision=revision)
                else:save_inputs(conn, posting_id, value, expected_revision=revision)
            except (AgenticError, ValidationError):
                raise HTTPException(status_code=409, detail='Notes were not saved. Reopen this page to check the latest revision and note lengths before trying again.') from None
        finally: conn.close()
        return RedirectResponse(interview_url(posting_id), status_code=303)

    @app.post('/jobs/{posting_id}/interview-prep')
    def interview_start(posting_id: int, background_tasks: BackgroundTasks, retry: bool = Form(False)):
        from jobwatch.interview_prep import capture, generate
        from jobwatch.candidate.evidence import snapshot_evidence
        from jobwatch.candidate.contracts import CandidateError
        from pipeline.agentic.contracts import AgenticError
        from pipeline.agentic.service import enabled
        if not enabled(config): raise HTTPException(status_code=409, detail='Interview preparation is not enabled.')
        conn = conn_()
        try:
            interview_job(conn, posting_id)
            try: capture(conn, posting_id, snapshot_evidence(apaths.profile_dir()), config)
            except (AgenticError, CandidateError):
                raise HTTPException(status_code=409, detail='Check the full job ad, current profile and private interview notes before preparing.') from None
        finally: conn.close()
        queue_interview(posting_id, background_tasks, retry=retry)
        return RedirectResponse(interview_url(posting_id), status_code=303)

    def queue_interview(posting_id, background_tasks, *, retry=False, existing_only=False):
        from jobwatch.interview_prep import enqueue
        from pipeline.agentic.contracts import AgenticError
        from jobwatch.candidate.contracts import CandidateError
        if not retry and not existing_only:
            conn = None
            try:
                conn = conn_()
                if not enqueue(conn, posting_id, config): return
            except (AgenticError, CandidateError, sqlite3.Error, OSError):
                raise HTTPException(status_code=409, detail='Interview preparation could not be queued. Check the current sources and try again.') from None
            finally:
                if conn is not None: conn.close()
        key = users.scoped(posting_id)         # ids are per-person: one person's run must not block another's
        with interview_lock:
            if key in interview_active:
                return
            interview_active.add(key)
        def work():
            c = None
            released = False
            attempt_retry = retry
            try:
                c = conn_()
                from jobwatch.interview_prep import generate, is_queued
                while True:
                    generate(c, posting_id, config, retry=attempt_retry, queued_only=not attempt_retry)
                    # A note edit may have queued a new snapshot while this posting was active.
                    # Check and release together so a concurrent requester cannot lose its wakeup.
                    with interview_lock:
                        if not is_queued(c, posting_id, config):
                            interview_active.discard(key)
                            released = True
                            break
                    attempt_retry = False
            except Exception:
                # Only durable state is public; provider exceptions may contain private notes.
                pass
            finally:
                if c is not None: c.close()
                if not released:
                    with interview_lock: interview_active.discard(key)
        background_tasks.add_task(work)
    def maybe_queue_interview(conn, posting_id, background_tasks):
        from jobwatch.interview_prep import should_prepare_after_interview
        from pipeline.agentic.contracts import AgenticError
        from jobwatch.candidate.contracts import CandidateError
        try:
            if should_prepare_after_interview(conn, posting_id, config):
                queue_interview(posting_id, background_tasks)
        except (AgenticError, CandidateError):
            pass

    @app.get('/jobs/{posting_id}/interview-prep/download')
    def interview_download(posting_id: int):
        conn = conn_()
        try:
            job = interview_job(conn, posting_id)
            state = interview_state(conn, posting_id)
            if state['status'] != 'ready':
                raise HTTPException(status_code=409, detail='A current reviewed report is not available.')
            report = state['report']
            lines = [f"Interview preparation: {job['title']}", job['company'] or '',
                'Private report — independently reviewed; no messages sent.',
                f'Snapshot: {report.snapshot_hash}', f'Reviewed report: {report.proposal.draft_hash}']
            if job.get('jd_source'):lines.append('JD source: '+job['jd_source'])
            for section in report.proposal.sections:
                lines.extend(['', section.title])
                for item in section.items:
                    lines.extend([f'[{interview_labels[item.kind]}] {item.topic}', item.text])
                    if item.audience: lines.append(f'Audience: {item.audience}')
                    if item.question: lines.append(f'Question: {item.question}')
                    if item.answer:
                        lines.append('Answer grounding: ' + ('Owner-supplied fact' if item.answer_grounding == 'owner_fact' else 'Primary candidate evidence'))
                        lines.extend(f'{k.title()}: {v}' for k, v in item.answer.model_dump().items())
                    for citation in (*item.citations, *item.answer_citations):
                        lines.append(f'Evidence ({citation.source_id}, {citation.content_hash}): {citation.quote}')
            lines.extend(['', f'Sources ({len(report.sources)})'])
            for source in report.sources:
                lines.append(f'{source.source_id} — {source.kind}; accessed: {source.accessed_at or "not recorded"}; hash: {source.content_hash}')
                if source.url and interview_source_url(source.url): lines.append(source.url)
            return PlainTextResponse('\n'.join(lines), headers={
                'Content-Disposition': f'attachment; filename="interview-prep-{posting_id}.txt"',
                'Cache-Control': 'private, no-store'})
        finally: conn.close()


    @app.get('/interview-prep',response_class=HTMLResponse)
    def interview_url_entry(request:Request):
        conn=conn_()
        try:
            from jobwatch.interview_subjects import load_subject
            from pipeline.agentic.contracts import AgenticError
            subjects=[]
            for row in conn.execute('SELECT subject_id FROM interview_subjects ORDER BY rowid DESC LIMIT 100'):
                try:subjects.append(load_subject(conn,row['subject_id']))
                except AgenticError:continue
            return render(request,'interview_url.html',conn,error=None,subjects=subjects)
        finally:conn.close()

    OPEN_ERROR = 'The complete job description could not be verified. Check the URL, or paste the full description and role title below. Closed postings require a saved description.'

    def open_interview(conn, url, pasted_jd, title, company):
        """Find or create the interview-prep subject for a job URL. Returns (reference, error text)."""
        from datetime import datetime,timezone
        from jobwatch.interview_ad import InterviewAd,InterviewAdUnavailable,ats_target
        from jobwatch.interview_browser import acquire_ad
        from jobwatch.interview_subjects import create_subject
        from jobwatch.interview_prep import matching_posting
        from pipeline.agentic.contracts import AgenticError
        from jobwatch.candidate.contracts import CandidateError
        try:
            ats_target(url)
            existing=matching_posting(conn,url,config,title=title,company=company)
            if existing:return existing,''
            if pasted_jd:
                if not title.strip():raise InterviewAdUnavailable('interview_title_required')
                ad=InterviewAd(url,url,title,company,pasted_jd,datetime.now(timezone.utc).isoformat(),'owner_supplied')
            else:
                ad=acquire_ad(url)
                existing=matching_posting(conn,url,config,title=ad.title,company=ad.company)
                if existing:return existing,''
            return create_subject(conn,ad),''
        except (InterviewAdUnavailable,AgenticError,CandidateError):
            return None,OPEN_ERROR

    @app.post('/interview-prep/open')
    def interview_url_open(request:Request,url:str=Form(...),pasted_jd:str=Form(''),
            title:str=Form(''),company:str=Form('')):
        conn=conn_()
        try:
            ref,error=open_interview(conn,url,pasted_jd,title,company)
            if ref is not None:return RedirectResponse(interview_url(ref),status_code=303)
            return render(request,'interview_url.html',conn,
                status=409,entry_url=url,entry_title=title,entry_company=company,entry_jd=pasted_jd,error=error)
        finally:conn.close()

    @app.get('/interview-prep/subjects/{subject_id}',response_class=HTMLResponse)
    def interview_subject_page(request:Request,subject_id:str):
        return interview_page(request,subject_id)

    @app.post('/interview-prep/subjects/{subject_id}')
    def interview_subject_start(subject_id:str,background_tasks:BackgroundTasks,retry:bool=Form(False)):
        return interview_start(subject_id,background_tasks,retry)

    @app.post('/interview-prep/subjects/{subject_id}/inputs')
    def interview_subject_inputs(subject_id:str,revision:int=Form(...),invite:str=Form(''),
            panelist_profiles:str=Form(''),story_bank:str=Form(''),prior_compensation:str=Form(''),
            coffee_chat:str=Form(''),prior_round_notes:str=Form('')):
        return interview_save_inputs(subject_id,revision,invite,panelist_profiles,story_bank,
            prior_compensation,coffee_chat,prior_round_notes)

    @app.get('/interview-prep/subjects/{subject_id}/download')
    def interview_subject_download(subject_id:str):return interview_download(subject_id)


    # -- JSON for the app's interview-preparation and follow-up draft pages (same logic as the classic pages) --
    def ref_of(ref: str):
        return int(ref) if ref.isdigit() else ref

    def prep_json(state):
        out = {"status": state["status"], "report": None}
        r = state.get("report")
        if r is not None:
            d = r.model_dump(mode="json")
            for src in d.get("sources") or []:
                src["url"] = interview_source_url(src.get("url") or "")
            out["report"] = d
        return out

    @app.get("/api/interview")
    def api_interview_list():
        from jobwatch.interview_subjects import load_subject
        from pipeline.agentic.contracts import AgenticError
        conn = conn_()
        try:
            subjects = []
            for row in conn.execute('SELECT subject_id FROM interview_subjects ORDER BY rowid DESC LIMIT 100'):
                try:
                    sj = load_subject(conn, row['subject_id'])
                    subjects.append({"id": sj["subject_id"], "title": sj["ad"].title, "company": sj["ad"].company, "at": sj["ad"].acquired_at})
                except AgenticError:
                    continue
            return as_json({"subjects": subjects})
        finally:
            conn.close()

    @app.post("/api/interview/open")
    async def api_interview_open(request: Request):
        b = await request.json()
        url, jd, title, company = (str(b.get(k) or "") for k in ("url", "pasted_jd", "title", "company"))
        def run():
            conn = conn_()
            try:
                ref, error = open_interview(conn, url, jd, title, company)
                return ({"ref": str(ref)}, 200) if ref is not None else ({"error": error}, 409)
            finally:
                conn.close()
        out, code = await run_in_threadpool(run)
        return as_json(out, code)

    @app.get("/api/interview/{ref}")
    def api_interview(ref: str):
        from jobwatch.interview_inputs import load_inputs
        from pipeline.agentic.contracts import AgenticError
        pid = ref_of(ref)
        conn = conn_()
        try:
            job = interview_job(conn, pid)
            try:
                if type(pid) is str:
                    from jobwatch.interview_subjects import load_subject
                    sj = load_subject(conn, pid)
                    inputs, revision = sj['inputs'], sj['revision']
                else:
                    inputs, revision = load_inputs(conn, pid)
            except AgenticError:
                raise HTTPException(status_code=409, detail='Private interview notes need verification.') from None
            job["source_link"] = interview_source_url(job.get("source_url") or "")
            return as_json({"job": job, "state": prep_json(interview_state(conn, pid)), "inputs": inputs.model_dump(),
                            "revision": revision, "fields": interview_fields, "kinds": interview_labels, "ref": str(pid)})
        finally:
            conn.close()

    @app.post("/api/interview/{ref}/inputs")
    async def api_interview_inputs(ref: str, request: Request):
        b = await request.json()
        def run():
            keys = ("invite", "panelist_profiles", "story_bank", "prior_compensation", "coffee_chat", "prior_round_notes")
            interview_save_inputs(ref_of(ref), int(b.get("revision") or 0), **{k: str(b.get(k) or "") for k in keys})
            return {"toast": "Private context saved"}
        return as_json(await run_in_threadpool(run))

    @app.post("/api/interview/{ref}/start")
    async def api_interview_start(ref: str, request: Request, background_tasks: BackgroundTasks):
        try:
            b = await request.json()
        except Exception:
            b = {}
        await run_in_threadpool(interview_start, ref_of(ref), background_tasks, bool(b.get("retry")))
        return as_json({"toast": "Preparation started"})

    @app.get("/api/followup-draft/{posting_id}")
    def api_followup_draft(posting_id: int, channel: str = "email"):
        from jobwatch.followup_drafts import load_draft
        from pipeline.agentic.service import enabled
        from pipeline.agentic.contracts import AgenticError
        from jobwatch.followup_events import FollowupEventError
        from jobwatch.candidate.contracts import CandidateError
        if channel not in {'email', 'linkedin'}:
            raise HTTPException(status_code=422)
        ok_id(posting_id)
        conn = conn_()
        try:
            row = conn.execute('SELECT a.id,p.title,p.company FROM applications a JOIN postings p ON p.id=a.posting_id WHERE p.id=?', (posting_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404)
            state = {'status': 'disabled', 'draft': None, 'reason': None}
            if enabled(config):
                try:
                    state = load_draft(conn, row['id'], channel=channel)
                    with followup_lock:
                        if state['status'] == 'missing' and users.scoped(row['id'], channel) in followup_active:
                            state = {'status': 'running', 'draft': None, 'reason': None}
                except (AgenticError, FollowupEventError, CandidateError):
                    state = {'status': 'unavailable', 'draft': None, 'reason': None}
            d = state.get("draft")
            prop = d.proposal.model_dump(mode="json") if d is not None else None
            return as_json({"job": dict(row), "status": state["status"], "proposal": prop, "channel": channel})
        finally:
            conn.close()

    @app.post("/api/followup-draft/{posting_id}")
    async def api_followup_draft_start(posting_id: int, request: Request, background_tasks: BackgroundTasks):
        b = await request.json()
        await run_in_threadpool(followup_draft_start, request, posting_id, background_tasks, str(b.get("channel") or "email"), bool(b.get("retry")))
        return as_json({"toast": "Draft started"})

    # -- inbox -------------------------------------------------------------------------------------
    def inbox_ctx(conn) -> dict:
        d = {"open": q.proposals(conn, True), "closed": q.proposals(conn, False)}
        for p in d["open"] + d["closed"]:
            p["ev_flag_labels"] = [q.flag_label(x) for x in (p.get("ev_flags") or [])]
            p["flags_list"] = list(p.get("ev_flags") or [])
            when = p.get("decided_at") or p.get("received_at")
            p["when_ago"], p["received_ago"] = q.ago(when), q.ago(p.get("received_at"))
        return d

    @app.get("/inbox")
    def old_inbox_link():
        return RedirectResponse("/#inbox", status_code=307)

    # -- sources, insights -------------------------------------------------------------------------
    @app.get("/sources")
    def old_sources_link():
        return RedirectResponse("/#sources", status_code=307)

    @app.get("/insights")
    def old_insights_link():
        return RedirectResponse("/#insights", status_code=307)

    # -- JSON API for the new UI (owner 2026-10-18: "Rebuild new UI properly") ---------------------
    # Every endpoint returns exactly what the classic page renders, from the same functions, so the
    # new UI can never show less than the old one.
    def as_json(obj, status: int = 200):
        import json as _json
        def plain(o):
            if isinstance(o, sqlite3.Row):
                return dict(o)
            if isinstance(o, (set, tuple)):
                return list(o)
            return str(o)
        return Response(_json.dumps(obj, default=plain), status_code=status, media_type="application/json",
                        headers={"Cache-Control": "no-store"})

    def board_payload(conn, request: Request, size: int):
        f = q.Filters.from_params(request.query_params)
        rows, counts = filtered(conn, f)
        page_rows, page, pages = page_of(rows, _page_no(request.query_params.get("page")), size)
        q.add_teasers(conn, page_rows)
        for r in page_rows:
            r["salary"] = q.salary_display(r)
            r["where"] = q.short_location(r.get("location")) + q.commute_km(r.get("location"))
            r["arm_label"] = q.arm_label(r.get("arm"))
            r["sector_label"] = q.arm_label(r["sector"]) if r.get("sector") else ""
            r["src_labels"] = [q.src_label(x) for x in (r.get("srcs") or [])]
            r["ai_text"] = q.row_ai_text(r)
            r["listed_ago"] = q.ago(r["listed_dt"]) if r.get("listed_dt") else ""
            r["first_seen_ago"] = q.ago(r.get("first_seen_at"))
            r["hide_sentence"] = q.hide_sentence((r.get("ai") or {}).get("hide_reason")) if r.get("ai_state") == "hide" else ""
            r["rights_note"] = q.RIGHTS_TEXT.get("valid_work_rights", "")
            if r.get("score5") is not None:
                r["score_label"], r["score_class"] = q.score_label(r["score5"]), q.score_class(r["score5"])
        return {"rows": page_rows, "total": len(rows), "page": page, "pages": pages, "size": size, "counts": counts,
                "filters": {k: getattr(f, k) for k in vars(f)}, "progress": q.ai_progress(conn),
                "summary": f.summary(), "active": f.active_count(), "ai_text": q.ai_view_text(f.ai, f.why),
                "saved": q.saved_searches(conn, reg.refresh())}

    @app.get("/api/board")
    def api_board(request: Request):
        conn = conn_()
        try:
            return as_json(board_payload(conn, request, q.PAGE_SIZE))
        finally:
            conn.close()

    @app.get("/api/table")
    def api_table(request: Request):
        conn = conn_()
        try:
            return as_json(board_payload(conn, request, q.TABLE_PAGE_SIZE))
        finally:
            conn.close()

    @app.get("/api/job/{posting_id}")
    def api_job(posting_id: int):
        conn = conn_()
        try:
            ctx = job_ctx(conn, posting_id)
            j = ctx["job"]
            ai = j.get("ai") or {}
            j["salary"] = q.salary_display(j)
            # the same computed wording the classic templates print, so both pages say the same thing
            j["where"] = (q.short_location(j.get("location")) or "") + (q.commute_km(j.get("location")) or "")
            j["posted_ago"] = q.ago(j["listed_dt"]) if j.get("listed_dt") else ""
            j["posted_abs"] = q.absolute(j["listed_dt"]) if j.get("listed_dt") else ""
            j["src_labels"] = [q.src_label(x) for x in (j.get("srcs") or [])]
            j["arm_label"] = q.arm_label(j.get("arm")) if j.get("arm") else ""
            j["arm_labels"] = [q.arm_label(x) for x in (j.get("arms") or [])]
            j["wt_label"] = q.WORK_TYPES.get(j.get("wt"), j.get("wt"))
            if ai.get("reviewed_at"):
                ai["reviewed_ago"] = q.ago(ai["reviewed_at"])
            j["hide_sentence"] = q.hide_sentence(ai.get("hide_reason")) if ai.get("hide_reason") else ""
            if j.get("score5") is not None:
                j["score_label"], j["score_class"] = q.score_label(j["score5"]), q.score_class(j["score5"])
            rk = q.rec_key(j)
            j["rec_key"], j["rec_word"] = rk, (q.REC_WORDS.get(rk) if rk else "")
            for sgt in j.get("sightings") or []:
                sgt["label"], sgt["ago"] = q.src_label(sgt.get("source")), q.ago(sgt.get("first_seen_at"))
            for e in j.get("events") or []:
                e["ago"], e["abs"] = q.ago(e.get("at")), q.absolute(e.get("at"))
            files = (ctx.get("draft") or {}).get("files") or {}
            def furl(v):
                if not isinstance(v, str) or ".." in v:
                    return ""
                if v.startswith("/files/drafts/"):
                    return v
                return "/files/drafts/" + v.rsplit("/drafts/", 1)[1] if "/drafts/" in v else ""
            ctx["draft_links"] = {k: furl(files.get(k) or files.get(k + ("_md" if k == "summary" else "_pdf")))
                                  for k in ("cv", "letter", "summary")}
            if ctx.get("draft", {}).get("started"):
                ctx["draft"]["started_ago"] = q.ago(ctx["draft"]["started"])
            q.mark_viewed(conn, posting_id)
            return as_json(ctx)
        finally:
            conn.close()

    @app.post("/api/job/{posting_id}/{action}")
    async def api_job_action(request: Request, posting_id: int, action: str, background_tasks: BackgroundTasks):
        ok_id(posting_id)
        try:
            body = await request.json()
        except Exception:
            body = {}
        def run():
            conn = conn_()
            try:
                try:
                    toast = run_job_action(conn, posting_id, action, str(body.get("status") or ""),
                                           str(body.get("notes") or ""), background_tasks)
                except act.ActionError as exc:
                    return {"error": str(exc)}, 400
                return {"toast": toast, "job": one_row(conn, posting_id), "draft": act.draft_state(conn, posting_id)}, 200
            finally:
                conn.close()
        out, code = await run_in_threadpool(run)
        return as_json(out, code)

    def decorate_apps(ctx):
        for a in [x for c in ctx["cols"] for x in c[2]] + ctx["closed"]:
            a["where"] = (q.short_location(a.get("location")) + q.commute_km(a.get("location"))) if a.get("location") else ""
            a["last_ago"], a["last_abs"] = q.ago(a.get("last_at")), q.absolute(a.get("last_at"))
            a["updated_ago"], a["updated_abs"] = q.ago(a.get("updated_at")), q.absolute(a.get("updated_at"))
        return ctx

    @app.get("/api/applications")
    def api_applications():
        conn = conn_()
        try:
            return as_json(decorate_apps(kanban_ctx(conn)))
        finally:
            conn.close()

    @app.get("/api/inbox")
    def api_inbox():
        conn = conn_()
        try:
            return as_json(inbox_ctx(conn))
        finally:
            conn.close()

    @app.post("/api/inbox/{proposal_id}/{decision}")
    def api_inbox_decide(proposal_id: int, decision: str, background_tasks: BackgroundTasks):
        ok_id(proposal_id)
        conn = conn_()
        try:
            try:
                flash = act.decide_proposal(conn, proposal_id, decision)
                if decision == "approve":
                    pr = conn.execute("SELECT a.posting_id FROM outcome_proposals o JOIN applications a ON a.id=o.application_id WHERE o.id=? AND o.status='approved' AND o.proposed_status='interview'", (proposal_id,)).fetchone()
                    if pr and pr["posting_id"]:
                        maybe_queue_interview(conn, pr["posting_id"], background_tasks)
            except act.ActionError as exc:
                return as_json({"error": str(exc)}, 400)
            return as_json({"toast": flash, **inbox_ctx(conn)})
        finally:
            conn.close()

    @app.post("/api/applications/{posting_id}/followup")
    async def api_followup(request: Request, posting_id: int):
        from datetime import date
        from jobwatch.followup_events import FollowupEventError, record_event
        from jobwatch.place import person_timezone
        LOCAL = person_timezone()
        ok_id(posting_id)
        b = await request.json()
        action, occurred_at, due_on = str(b.get("action") or ""), str(b.get("occurred_at") or ""), str(b.get("due_on") or "")
        def run():
            conn = conn_()
            try:
                row = conn.execute("SELECT id FROM applications WHERE posting_id=?", (posting_id,)).fetchone()
                if row is None:
                    return {"error": "This job is not tracked as an application."}, 404
                try:
                    when = None
                    if action not in {"pin", "clear_pin"}:
                        when = datetime.fromisoformat(occurred_at)
                        if when.tzinfo is None:
                            first, second = when.replace(tzinfo=LOCAL, fold=0), when.replace(tzinfo=LOCAL, fold=1)
                            if first.utcoffset() != second.utcoffset() or first.astimezone(UTC).astimezone(LOCAL).replace(tzinfo=None) != when:
                                raise ValueError("ambiguous local time")
                            when = first
                    record_event(conn, row["id"], action, operation_id=str(b.get("operation_id") or ""),
                                 owner_confirmed=bool(b.get("owner_confirmed")), occurred_at=when,
                                 due_on=date.fromisoformat(due_on) if action == "pin" else None,
                                 channel=str(b.get("channel") or "") if action == "sent" else None)
                except (ValueError, FollowupEventError):
                    return {"error": "Could not record this follow-up. Confirm the event, check its date and your application status, then try again."}, 422
                return {"toast": "Follow-up saved", **decorate_apps(kanban_ctx(conn))}, 200
            finally:
                conn.close()
        out, code = await run_in_threadpool(run)
        return as_json(out, code)

    @app.post("/api/searches")
    async def api_add_search(request: Request):
        from urllib.parse import parse_qs
        b = await request.json()
        conn = conn_()
        try:
            f = q.Filters.from_params({k: v for k, v in parse_qs(str(b.get("qs") or "")[:2000]).items()})
            act.save_search(conn, str(b.get("name") or ""), f.as_dict())
            return as_json({"toast": "Search saved", "saved": q.saved_searches(conn, reg.refresh())})
        except act.ActionError as exc:
            return as_json({"error": str(exc)}, 400)
        finally:
            conn.close()

    @app.post("/api/searches/{search_id}/{what}")
    def api_search_do(search_id: int, what: str):
        ok_id(search_id)
        conn = conn_()
        try:
            if what == "delete":
                act.delete_search(conn, search_id)
            elif what == "open":
                act.touch_search(conn, search_id)
            else:
                raise HTTPException(404)
            return as_json({"toast": "Saved search removed" if what == "delete" else "", "saved": q.saved_searches(conn, reg.refresh())})
        finally:
            conn.close()

    @app.get("/api/sources")
    def api_sources(sector: str = "", enabled: str = ""):
        conn = conn_()
        try:
            reg.refresh()
            health = q.health_rows(conn)
            for h in health:
                h["last_ok_ago"] = q.ago(h["last_ok_at"]) if h.get("last_ok_at") else ""
            return as_json({"health": health, "sectors": reg.sectors(),
                            "employers": q.employer_rows(conn, reg, sector[:60], enabled if enabled in ("0", "1") else "")})
        finally:
            conn.close()

    @app.get("/api/insights")
    def api_insights():
        conn = conn_()
        try:
            d = q.insights(conn, reg.refresh())
            d["by_arm"] = [[a, t, n, q.arm_label(a)] for a, t, n in d["by_arm"]]
            d["by_src"] = [[a, n, q.src_label(a)] for a, n in d["by_src"]]
            d["by_sector"] = [[a, n, str(a).capitalize()] for a, n in d["by_sector"]]
            d["series"] = [[str(a), n] for a, n in d["series"]]
            return as_json(d)
        finally:
            conn.close()

    @app.get("/api/meta")
    def api_meta():
        """Labels the UI shows, from the same tables the classic pages use."""
        return as_json({"ai_views": q.AI_VIEWS, "hide_reasons": q.HIDE_REASONS, "states": q.STATE_LABEL,
                        "work_types": q.WORK_TYPES, "within": q.WITHIN, "sorts": q.SORTS,
                        "score_floors": [[f, q.SCORE_FLOOR_LABEL[f]] for f in q.SCORE_FLOORS],
                        "app_states": q.APP_STATES, "warn": q.WARN, "rights_text": q.RIGHTS_TEXT,
                        "blocking_rights": list(q.BLOCKING_RIGHTS), "seniority_text": q.SENIORITY_TEXT,
                        "ad_kind_label": q.AD_KIND_LABEL, "hours_text": q.HOURS_TEXT, "work_mode_text": q.WORK_MODE_TEXT,
                        "location_text": q.LOCATION_TEXT, "importance_text": q.IMPORTANCE_TEXT, "tier_text": q.TIER_TEXT,
                        "tier_why": q.TIER_WHY, "match_text": q.MATCH_TEXT, "legit_text": q.LEGIT_TEXT,
                        "dim_label": q.DIM_LABEL, "table_cols": TABLE_COLS, "default_cols": DEFAULT_COLS,
                        "status_rail": q.STATUS_RAIL, "source_label": q.SOURCE_LABEL, "tabs": q.TABS, "score_floor_values": list(q.SCORE_FLOORS),
                        "hide_labels": {k: q.hide_label(k) for k in q.HIDE_LABEL}, "flag_text": {"offer_review": "Review it yourself"}})

    @app.get("/api/chat")
    def api_chat(request: Request):
        from jobwatch import notify as nt
        from .chat_routes import SUGGESTIONS, ask_card, chat_history
        qp = request.query_params
        ask = ask_card([x for x in qp.get("skip", "").split(",") if x], verify=bool(qp.get("verify")),
                       change=qp.get("change") or None)
        conn = conn_()
        try:
            msgs = chat_history(conn)
            nt.mark_read(conn)                      # opening Chat reads everything, so the badge clears
            return as_json({"messages": msgs, "suggestions": SUGGESTIONS, "ask": ask})
        finally:
            conn.close()

    @app.post("/api/chat/ask")
    async def api_chat_ask(request: Request):
        """Answer, keep, skip or change one quick question from Chat."""
        from .chat_routes import ask_answer
        p = await request.json()
        return as_json(ask_answer(str(p.get("field", "")), str(p.get("choice", "")), str(p.get("other", "")),
                                  ",".join(p.get("skip") or [])))

    @app.post("/api/chat")
    async def api_chat_send(request: Request):
        """Save the owner's message, then the model answers. It can only read the board; a failure is text."""
        from jobwatch import notify as nt
        from .chat_routes import answer
        try:
            payload = await request.json()
        except Exception:
            return as_json({"error": "Send JSON"}, 415)
        text = str((payload or {}).get("text") or "").strip()[:4000]
        if not text:
            return as_json({"error": "Empty message"}, 422)
        def talk() -> str:
            conn = conn_()
            try:
                nt.add(conn, "owner", text)
                try:
                    reply = answer(conn) or "No reply this time. Your message is saved."
                except Exception as exc:  # noqa: BLE001 - keep the owner's message whatever happens
                    reply = f"No reply this time ({type(exc).__name__}). Your message is saved."
                nt.add(conn, "assistant", reply)
                return reply
            finally:
                conn.close()
        return as_json({"reply": await run_in_threadpool(talk)})

    @app.get("/api/nav")
    def api_nav():
        conn = conn_()
        try:
            return as_json(q.nav_counts(conn))
        finally:
            conn.close()

    # -- files, health -----------------------------------------------------------------------------
    @app.get("/files/drafts/{path:path}")
    def draft_file(path: str):
        root = apaths.drafts_dir().resolve()            # the signed-in person's drafts, never the owner's
        target = (root / path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            raise HTTPException(404)
        if target.name not in FILE_NAMES or not target.is_file():
            raise HTTPException(404)
        return FileResponse(target, media_type=FILE_NAMES[target.name],
                            headers={"Content-Disposition": f'inline; filename="{target.name}"'})

    @app.get("/healthz")
    def healthz():
        return PlainTextResponse("ok")


    def accepts_json_first(accept: str) -> bool:
        """The first, highest-ranked media type of an Accept header is application/json. A browser's 'text/html, ...,
        application/json;q=0.1' is HTML; '*/*' (curl) is HTML too."""
        best, best_q = "", 0.0
        for part in accept.split(",")[:20]:
            media, *params = (x.strip() for x in part.split(";"))
            quality = 1.0
            for param in params:
                if param.lower().startswith("q="):
                    try:
                        quality = float(param[2:])
                    except ValueError:
                        quality = 0.0
            if quality > best_q:                                 # the first of equal rank wins
                best, best_q = media.lower(), quality
        return best == "application/json" or best.endswith("+json")

    def wants_json(request: Request) -> bool:
        """Script callers (fetch with Accept: application/json first, or X-Requested-With)."""
        h = request.headers
        return (accepts_json_first(h.get("accept", ""))
                or "x-requested-with" in h
                or (request.url.path.startswith("/api/") and "text/html" not in h.get("accept", "")))

    @app.exception_handler(404)
    async def not_found(request: Request, exc):
        message = str(getattr(exc, "detail", "") or "Not found")
        if wants_json(request):
            return JSONResponse({"error": message}, status_code=404)
        return render(request, "error.html", None, status=404, message=message)

    @app.exception_handler(RequestValidationError)
    async def bad_params(request: Request, exc):
        """A malformed id or number in the URL: the same page as a missing one, never a JSON dump.
        JSON callers get JSON, htmx partials a short fragment (never a whole page inside the results pane)."""
        in_path = any(e.get("loc", ("",))[0] == "path" for e in exc.errors())
        status, message = (404, "No such item") if in_path else (422, "That request has an invalid value")
        if wants_json(request):
            return JSONResponse({"error": message}, status_code=status)
        if hx(request):
            return HTMLResponse(f'<p class="error-note" role="alert">{message}</p>', status_code=status)
        return render(request, "error.html", None, status=status, code=None if in_path else 422, message=message)

    return app
