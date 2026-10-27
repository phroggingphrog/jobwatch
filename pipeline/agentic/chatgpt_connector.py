"""Stage 1 of the ChatGPT connector: read-only tools plus MCP Apps widgets.

Tools only read. Submit, prepare and revise are not here (stages 2 and 3). Every read runs as the
authenticated person; no tool argument names a person. Reuses task_state, the same service the
chat agent's own jobs_overview / task_status tools call.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from urllib.parse import urlparse

from fastmcp import FastMCP
from fastmcp.tools import ToolResult

from jobwatch import users
from jobwatch.config import load_config
from pipeline.agentic import task_state
from pipeline.agentic.chat import dispatch, job_connection
from pipeline.agentic.runtime import RuntimeErrorSafe

MIME = 'text/html;profile=mcp-app'
LIST_URI = 'ui://jobwatch/chatgpt-jobs-v1.html'
DETAIL_URI = 'ui://jobwatch/chatgpt-job-v1.html'
WORK = {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False, 'idempotentHint': False}
DECIDE = dict(WORK)
# Submit sends the application to the employer: destructive and open-world.
SUBMIT = {'readOnlyHint': False, 'destructiveHint': True, 'openWorldHint': True, 'idempotentHint': False}
READ_ONLY = {'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False, 'idempotentHint': True}
# The widgets are self-contained: no external scripts, styles or fonts, and they only call this server.
CSP = {'connectDomains': [], 'resourceDomains': []}

_COUNT_TEXT = (('needs_you', 'need you'), ('needs_info', 'need info'), ('outcome_unknown', 'outcome unknown'),
               ('submitted', 'submitted'))


def counts_text(counts: dict) -> str:
    parts = [f'{counts[key]} {label}' for key, label in _COUNT_TEXT if counts.get(key)]
    return ' · '.join(parts) or 'Nothing needs you'


def _http_url(url) -> str | None:
    parsed = urlparse(url or '')
    return url if parsed.scheme in ('http', 'https') and parsed.netloc else None


def _list(value) -> list[str]:
    try:
        items = json.loads(value) if value else []
    except ValueError:
        return []
    return [str(i)[:300] for i in items if isinstance(i, (str, int, float))][:8] if isinstance(items, list) else []


def overview(person: str, limit: int = 50) -> dict:
    limit = max(1, min(int(limit), 100))
    with users.use(person), job_connection(load_config()) as conn:
        rows = task_state.jobs_overview(conn, limit)
    return {'view': 'list', 'counts': task_state.overview_counts(rows), 'jobs': rows}


def detail(person: str, posting_id: int) -> dict:
    if type(posting_id) is not int or posting_id < 1:
        raise RuntimeErrorSafe('invalid_request')
    with users.use(person), job_connection(load_config()) as conn:
        conn.row_factory = sqlite3.Row
        post = conn.execute('SELECT title, company, location, url FROM postings WHERE id=?', (posting_id,)).fetchone()
        if post is None:
            return {'view': 'detail', 'posting_id': posting_id, 'found': False}
        has = lambda t: bool(conn.execute('SELECT 1 FROM sqlite_master WHERE name=?', (t,)).fetchone())
        review = conn.execute('SELECT score, reason, pros_json, cons_json FROM ad_reviews WHERE posting_id=?',
                              (posting_id,)).fetchone() if has('ad_reviews') else None
        card = task_state.task_card(conn, posting_id)
        ready_digest = _application_and_digest(conn, posting_id)[1]
        draft = conn.execute('SELECT d.version FROM drafts d JOIN applications a ON a.id=d.application_id '
                             "WHERE a.posting_id=? AND d.status='ready' ORDER BY d.version DESC LIMIT 1",
                             (posting_id,)).fetchone() if has('drafts') and has('applications') else None
    return {'view': 'detail', 'posting_id': posting_id, 'found': True, 'employer': post['company'],
            'title': post['title'], 'location': post['location'], 'ad_url': _http_url(post['url']),
            'score': review['score'] if review else None, 'why_it_fits': (review['reason'] if review else None),
            'pros': _list(review['pros_json']) if review else [], 'cons': _list(review['cons_json']) if review else [],
            'state': card['state'], 'state_detail': card.get('message') or (card.get('submit') or {}).get('reason') or '',
            'documents_ready': draft is not None, 'draft_version': draft['version'] if draft else None,
            'can_submit': ready_digest is not None and card['state'] in ('draft ready', 'awaiting browser press')}


# -- stage 2: hand heavy work to Jobwatch's own agent ---------------------------------------------------------
_PENDING: dict[str, dict] = {}      # interaction_id -> the interrupt a widget button may answer (memory only)
PENDING_SECONDS = 3600
_WIDGET_MODEL_CUTOFF = 'Approve/Reject are widget buttons; do not call decide yourself.'
_OPS = {'prepare_application': 'Prepare the application', 'revise_application': 'Revise the application'}


def _forget_expired() -> None:
    now = time.time()
    for key in [k for k, v in _PENDING.items() if v['expires'] <= now]:
        del _PENDING[key]


def _hand_off(person: str, posting_id: int, message: str) -> tuple[dict, dict]:
    """Run one agent turn. Returns (structured content for the model and widget, widget-only meta)."""
    if type(posting_id) is not int or posting_id < 1:
        raise RuntimeErrorSafe('invalid_request')
    thread_id = secrets.token_urlsafe(32)
    result = dispatch(person=person, thread_id=thread_id, message=message[:15000])
    base = {'view': 'work', 'posting_id': posting_id, 'thread_id': thread_id}
    return _outcome(person, base, result)


def _outcome(person: str, base: dict, result: dict) -> tuple[dict, dict]:
    declined: list[str] = []
    for _ in range(4):
        if result.get('status') != 'interrupted':
            break
        items = result.get('interactions') or []
        approvals = [i for i in items if i.get('type') == 'approval']
        if (len(items) == 1 and len(approvals) == 1 and approvals[0].get('operation') != 'submit_application'
                and approvals[0].get('binding')):
            item, interaction_id = approvals[0], secrets.token_urlsafe(16)
            _forget_expired()
            _PENDING[interaction_id] = {'person': person, 'thread_id': base['thread_id'], 'item': item,
                                        'checkpoint_id': result.get('checkpoint_id'),
                                        'expires': time.time() + PENDING_SECONDS}
            op = item.get('operation')
            data = base | {'status': 'awaiting_approval', 'interaction_id': interaction_id, 'operation': op,
                           'summary': f"Jobwatch wants to {op.replace('_', ' ')} for job {item.get('posting_id')}. "
                                      'This may use paid model calls and save drafts. It will not submit.',
                           'note': _WIDGET_MODEL_CUTOFF}
            # The binding digest goes in widget-only _meta, not in what the model reads.
            return data, {'binding': item['binding'].get('digest')}
        # Anything else (several items, a question, a submit approval) cannot be put to the person here:
        # decline it so the thread stays usable. A rejection authorises nothing.
        declined += [str(i.get('operation') or i.get('type')) for i in items]
        result = dispatch(person=person, thread_id=base['thread_id'], human_decision=True,
                          expected_checkpoint=result.get('checkpoint_id'),
                          approval_bindings=[i.get('binding') for i in items],
                          decisions=[{'type': 'reject'} if i.get('type') == 'approval' else
                                     {'type': 'respond', 'message': 'This client cannot ask the person for that. '
                                      'Do not infer or invent the answer.'} for i in items])
    data = base | {'status': 'complete' if result.get('status') != 'interrupted' else 'needs_chat',
                   'answer': result.get('answer', ''), 'tools': result.get('tools', [])}
    if declined:
        data['declined'] = sorted(set(declined))
    return data, {}


def decide(person: str, interaction_id: str, decision: str, binding: str) -> dict:
    """Answer one pending approval. Only an approval this person was shown, with its own binding digest."""
    _forget_expired()
    if decision not in ('approve', 'reject') or type(interaction_id) is not str or type(binding) is not str:
        raise RuntimeErrorSafe('invalid_request')
    pending = _PENDING.get(interaction_id)
    item = pending['item'] if pending else None
    if (pending is None or pending['person'] != person or item['operation'] == 'submit_application'
            or not hmac.compare_digest(binding, str(item['binding'].get('digest') or ''))):
        raise RuntimeErrorSafe('approval_not_found')
    del _PENDING[interaction_id]                      # one answer per approval
    result = dispatch(person=person, thread_id=pending['thread_id'], human_decision=True,
                      expected_checkpoint=pending['checkpoint_id'], approval_bindings=[item['binding']],
                      decisions=[{'type': decision}])
    data, meta = _outcome(person, {'view': 'work', 'posting_id': item.get('posting_id'),
                                   'thread_id': pending['thread_id']}, result)
    return data | {'decision': decision}, meta


# -- stage 3: Submit, only with the digest of the reviewed fill ----------------------------------------------
def _application_and_digest(conn, posting_id: int):
    from jobwatch.apply import prepare, submit_confirm
    from jobwatch.apply.paths import data_dir
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT id FROM applications WHERE posting_id=?', (posting_id,)).fetchone()
    if row is None:
        return None, None
    try:
        prepared = prepare.latest_preparation(data_dir(), str(row['id']))
    except prepare.PreparationRefused:
        return row['id'], None
    return row['id'], submit_confirm.digest(prepared)


def submit_digest(person: str, posting_id: int) -> str | None:
    """The reviewed fill's confirmation digest, or None when there is no reviewed fill to confirm."""
    with users.use(person), job_connection(load_config()) as conn:
        return _application_and_digest(conn, posting_id)[1]


def submit_reviewed(person: str, posting_id: int, confirm_digest: str, shown_hash: str | None = None) -> dict:
    """Queue the one press for the exact reviewed form. The web process re-checks the live form before pressing."""
    from jobwatch.apply import submit_confirm
    if type(posting_id) is not int or posting_id < 1 or type(confirm_digest) is not str:
        raise RuntimeErrorSafe('invalid_request')
    if shown_hash is not None:      # the JSON front passes it: refuse unless the person saw exactly what is now ready
        current_review, review_digest, needs_rebind = _review(person, posting_id)
        if not current_review.get('ready') or not hmac.compare_digest(str(shown_hash), current_review['shown_hash']):
            raise RuntimeErrorSafe('review_changed')
        if needs_rebind:
            # The form was edited after the fill and the person has now seen and confirmed exactly this edited form.
            if not hmac.compare_digest(confirm_digest, review_digest):
                raise RuntimeErrorSafe('submit_digest_mismatch')
            with users.use(person), job_connection(load_config()) as conn:
                blocked = task_state.retry_blocked(conn, posting_id)       # a refused Submit must not confirm the edit
            if blocked:
                raise RuntimeErrorSafe(blocked)
            with users.use(person):
                _live_form().rebind(person, posting_id, review_digest)
    with users.use(person), job_connection(load_config(), write=True) as conn:
        application_id, current = _application_and_digest(conn, posting_id)
        if current is None:
            raise RuntimeErrorSafe('submit_not_ready')
        if not hmac.compare_digest(confirm_digest, current):
            raise RuntimeErrorSafe('submit_digest_mismatch')
        blocked = task_state.retry_blocked(conn, posting_id)
        if blocked:
            raise RuntimeErrorSafe(blocked)
        approval = hashlib.sha256(('widget-submit:' + current).encode()).hexdigest()   # a double click queues once
        queued = submit_confirm.queue(conn, posting_id=posting_id, application_id=application_id,
                                      confirm_digest=current, approval=approval)
    return {'view': 'submit', 'posting_id': posting_id, **queued}


def status(person: str, posting_id: int) -> dict:
    """Plain state card for one posting (same logic as the task_status tool)."""
    if type(posting_id) is not int or posting_id < 1:
        raise RuntimeErrorSafe('invalid_request')
    with users.use(person), job_connection(load_config()) as conn:
        return task_state.task_card(conn, posting_id)


_DOC_LABEL = {'cv': ('CV', 'cv.pdf'), 'letter': ('Cover letter', 'letter.pdf')}


def _answer_text(value) -> str:
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    if isinstance(value, list):
        return ', '.join(str(v) for v in value)
    return '' if value is None else str(value)


_LIVE_REFUSALS = frozenset({'application_changed', 'final_control_changed', 'unsupported_form_review', 'form_review_unavailable',
                            'form_review_changed', 'application_not_ready', 'browser_unavailable'})


class _NativeLiveForm:
    """The live application form, read through the native browser API: the same review the web app's review and
    Submit use (BrowserService.review). `read` returns its dict; `rebind` records a corrected form against the digest
    the person saw (owner-review overlay, exactly what the web 'confirm this form' step does)."""

    def read(self, person: str, posting_id: int) -> dict:
        from jobwatch.apply import browser_remote
        try:
            return browser_remote.application_review(posting_id)
        except Exception:                      # noqa: BLE001 - only a fixed code ever leaves this module
            return {'status': 'blocked', 'reason': 'browser_unavailable'}

    def rebind(self, person: str, posting_id: int, digest: str) -> None:
        from jobwatch.apply import browser_remote
        try:
            browser_remote.application_review(posting_id, expected=digest)
        except Exception:                      # noqa: BLE001
            raise RuntimeErrorSafe('review_changed') from None


def _live_form():
    """The live-form reader, or None when this deployment has no native browser to ask (tests; board-only setups)."""
    return _NativeLiveForm() if os.environ.get('JOBWATCH_NATIVE_BROWSER_URL') else None


def _doc_rows(prepared: dict) -> list[dict]:
    names = prepared.get('document_names') if isinstance(prepared.get('document_names'), dict) else {}
    out = []
    for role, h in sorted((prepared.get('attached_documents') or {}).items()):
        label, generic = _DOC_LABEL.get(role, (role, role + '.pdf'))
        out.append({'role': role, 'label': label, 'file': str(names.get(role) or generic)[:200], 'sha256': str(h)[:12]})
    return out


def _live_answers(live: dict, prepared: dict) -> list[dict]:
    """The current form as question -> answer rows. File inputs are the documents (shown separately), passwords are
    never shown, and empty text rows and unselected radio options are noise. `source` is the fill-time source where
    the question was filled by Jobwatch, else 'form' (typed or changed by the person)."""
    sources = {str(r.get('question')): str(r.get('source') or '') for r in prepared.get('review_answers') or []
               if isinstance(r, dict)}
    rows = []
    for f in live.get('fields') or []:
        kind, value = str(f.get('type') or ''), str(f.get('value') or '')
        if kind in ('file', 'password') or not value or (kind == 'radio' and value == 'Not selected'):
            continue
        question = str(f.get('label') or '')[:500]
        rows.append({'question': question, 'answer': value[:2000], 'source': sources.get(question) or 'form'})
    return rows[:200]


def review(person: str, posting_id: int) -> tuple[dict, str | None]:
    """What the owner is approving. With a native browser the answers are read from the CURRENT form (so an edit made
    after the fill is what the person sees, hashes and confirms); otherwise they are the fill-time answers of the
    preparation. Attached documents carry the original file names. `shown_hash` covers exactly the shown content plus
    the digest, so Submit can refuse when anything the person saw has changed. The digest is never in the public
    review."""
    public, digest, _ = _review(person, posting_id)
    return public, digest


def _review(person: str, posting_id: int) -> tuple[dict, str | None, bool]:
    """(public review, digest, form_needs_rebind). The last is True when the live form differs from the recorded one,
    so Submit must record the person's confirmation of it first."""
    from jobwatch.apply import prepare, submit_confirm
    from jobwatch.apply.paths import data_dir
    if type(posting_id) is not int or posting_id < 1:
        raise RuntimeErrorSafe('invalid_request')
    base = {'posting_id': posting_id, 'found': False, 'ready': False, 'answers': [], 'documents': []}
    with users.use(person), job_connection(load_config()) as conn:
        conn.row_factory = sqlite3.Row
        post = conn.execute('SELECT title, company, url FROM postings WHERE id=?', (posting_id,)).fetchone()
        if post is None:
            return base, None, False
        base |= {'found': True, 'employer': post['company'], 'title': post['title'], 'ad_url': _http_url(post['url'])}
        card = task_state.task_card(conn, posting_id)
        base['state'] = card['state']
        row = conn.execute('SELECT id FROM applications WHERE posting_id=?', (posting_id,)).fetchone()
        if row is None:
            return base | {'reason': 'not_prepared'}, None, False
        try:
            prepared = prepare.latest_preparation(data_dir(), str(row['id']))
        except prepare.PreparationRefused:
            return base | {'reason': 'not_prepared'}, None, False
    recorded = submit_confirm.digest(prepared)
    if prepared is None or recorded is None:
        return base | {'reason': 'not_prepared'}, None, False
    out = base | {'documents': _doc_rows(prepared)}
    live_reader = _live_form()
    if live_reader is None:
        out['answers'] = [{'question': str(r.get('question') or r.get('key'))[:500], 'answer': _answer_text(r.get('value'))[:2000],
                           'source': str(r.get('source') or '')}
                          for r in prepared.get('review_answers') or [] if isinstance(r, dict) and r.get('value') is not None]
        digest, needs_rebind = recorded, False
    if card['state'] not in ('draft ready', 'awaiting browser press'):
        return out | {'reason': 'not_ready'}, None, False
    if live_reader is None:
        if (data_dir() / 'browser' / hashlib.sha256(str(row['id']).encode()).hexdigest() / prepared['run_id'] / 'owner-review.json').exists():
            # No browser to read: these are the fill-time answers and the owner changed the form since. Not offered.
            return out | {'reason': 'edited_in_browser'}, None, False
    else:
        with users.use(person):
            live = live_reader.read(person, posting_id)
        if not isinstance(live, dict) or live.get('status') == 'blocked' or not live.get('review_digest'):
            reason = str((live or {}).get('reason') or '')
            return out | {'reason': reason if reason in _LIVE_REFUSALS else 'browser_unavailable'}, None, False
        out['answers'] = _live_answers(live, prepared)
        digest = str(live['review_digest'])
        needs_rebind = live.get('confirmed_digest') != digest
    out['ready'] = True
    out['shown_hash'] = hashlib.sha256(json.dumps([out, digest], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return out, digest, needs_rebind

def _overview_text(data: dict) -> str:
    lines = [f"{counts_text(data['counts'])}. {len(data['jobs'])} jobs with activity."]
    lines += [f"#{j['posting_id']} {j['employer'] or '?'} - {j['title'] or '?'}: {j['state']}" for j in data['jobs'][:10]]
    return '\n'.join(lines)


def _detail_text(d: dict) -> str:
    if not d['found']:
        return f"No job {d['posting_id']} found."
    docs = 'documents ready' if d['documents_ready'] else 'no documents ready'
    score = f", score {d['score']}" if d['score'] is not None else ''
    return f"#{d['posting_id']} {d['employer'] or '?'} - {d['title'] or '?'}{score}. State: {d['state']}; {docs}."


def register(server: FastMCP, person_from_request) -> None:
    """Add the read-only tools and widget resources to an authenticated server."""

    @server.tool(name='jobs_overview', title='Jobs overview', annotations=READ_ONLY, meta={
        'ui': {'resourceUri': LIST_URI}, 'openai/outputTemplate': LIST_URI,
        'openai/toolInvocation/invoking': 'Reading your jobs', 'openai/toolInvocation/invoked': 'Jobs ready'})
    def jobs_overview_tool(limit: int = 50) -> ToolResult:
        """List the person's jobs with activity (newest first) with a plain state for each and counts of
        what needs them. Read-only. 'draft ready' is never 'submitted'."""
        data = overview(person_from_request(), limit)
        return ToolResult(content=_overview_text(data), structured_content=data)

    @server.tool(name='job_detail', title='Job detail', annotations=READ_ONLY, meta={
        'ui': {'resourceUri': DETAIL_URI}, 'openai/outputTemplate': DETAIL_URI,
        'openai/toolInvocation/invoking': 'Reading the job', 'openai/toolInvocation/invoked': 'Job ready'})
    def job_detail_tool(posting_id: int) -> ToolResult:
        """Employer, title, score, why it fits, state, whether documents are ready, and the ad link for one job.
        Read-only."""
        person = person_from_request()
        data = detail(person, posting_id)
        # The Submit digest is for the widget button only: it is in _meta, not in what the model reads.
        meta = {'submit_digest': submit_digest(person, posting_id)} if data.get('can_submit') else None
        return ToolResult(content=_detail_text(data), structured_content=data, meta=meta)

    def _work_result(data: dict, meta: dict) -> ToolResult:
        text = (data['summary'] + ' Waiting for the person to press Approve or Reject in the widget.'
                if data['status'] == 'awaiting_approval' else
                (data.get('answer') or 'Done.')[:1500])
        return ToolResult(content=text, structured_content=data, meta=meta or None)

    @server.tool(name='prepare_application', title='Prepare an application', annotations=WORK, meta={
        'ui': {'resourceUri': DETAIL_URI}, 'openai/outputTemplate': DETAIL_URI,
        'openai/widgetAccessible': True,
        'openai/toolInvocation/invoking': 'Handing to Jobwatch', 'openai/toolInvocation/invoked': 'Jobwatch replied'})
    def prepare_application_tool(posting_id: int, instructions: str = '') -> ToolResult:
        """Hand the heavy work of preparing an application (cover letter, CV, form fill) to Jobwatch's own agent.
        Returns the status and any approval it needs; the person approves with the widget buttons. Never submits."""
        message = f'Prepare the application for posting {posting_id}.' + (f' Instructions: {instructions}' if instructions else '')
        return _work_result(*_hand_off(person_from_request(), posting_id, message))

    @server.tool(name='revise_application', title='Revise an application', annotations=WORK, meta={
        'ui': {'resourceUri': DETAIL_URI}, 'openai/outputTemplate': DETAIL_URI,
        'openai/widgetAccessible': True,
        'openai/toolInvocation/invoking': 'Handing to Jobwatch', 'openai/toolInvocation/invoked': 'Jobwatch replied'})
    def revise_application_tool(posting_id: int, changes: str) -> ToolResult:
        """Hand a requested revision of an existing application draft to Jobwatch's own agent. Returns the status
        and any approval it needs; the person approves with the widget buttons. Never submits."""
        if not changes or not changes.strip():
            raise RuntimeErrorSafe('invalid_request')
        return _work_result(*_hand_off(person_from_request(), posting_id,
                                       f'Revise the application for posting {posting_id}. Changes: {changes}'))

    @server.tool(name='decide', title='Answer an approval (widget button)', annotations=DECIDE, meta={
        'ui': {'resourceUri': DETAIL_URI, 'visibility': ['app']}, 'openai/widgetAccessible': True,
        'openai/visibility': 'private'})
    def decide_tool(interaction_id: str, decision: str, binding: str) -> ToolResult:
        """Widget buttons only. Approve or reject one pending Jobwatch approval. The model must not call this."""
        data, meta = decide(person_from_request(), interaction_id, decision, binding)
        return _work_result(data, meta)

    @server.tool(name='submit_reviewed', title='Submit the reviewed application (widget button)', annotations=SUBMIT,
                 meta={'ui': {'resourceUri': DETAIL_URI, 'visibility': ['app']}, 'openai/widgetAccessible': True,
                       'openai/visibility': 'private'})
    def submit_reviewed_tool(posting_id: int, confirm_digest: str) -> ToolResult:
        """Widget Submit button only. Sends the reviewed application to the employer if confirm_digest matches the
        reviewed form. The model must not call this."""
        data = submit_reviewed(person_from_request(), posting_id, confirm_digest)
        return ToolResult(content=f"Submit {data['status']} for job {posting_id}.", structured_content=data)

    @server.tool(name='task_status', title='Task status', annotations=READ_ONLY)
    def task_status_tool(posting_id: int) -> ToolResult:
        """Plain state of the work on a posting: queued, drafting, draft ready, awaiting browser press, executing,
        submitted, outcome unknown, failed, cancelled, not started. Read-only."""
        if type(posting_id) is not int or posting_id < 1:
            raise RuntimeErrorSafe('invalid_request')
        with users.use(person_from_request()), job_connection(load_config()) as conn:
            card = task_state.task_card(conn, posting_id)
        return ToolResult(content=f"#{posting_id}: {card['state']}." + (' ' + card['message'] if card.get('message') else ''),
                          structured_content=card)

    for uri, name in ((LIST_URI, 'Jobwatch jobs list'), (DETAIL_URI, 'Jobwatch job detail')):
        server.resource(uri, name=name, mime_type=MIME,
                        meta={'ui': {'prefersBorder': True, 'csp': CSP}})(lambda: WIDGET_HTML)


WIDGET_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><title>Jobwatch</title>
<style>
:root{--bg:#fff;--fg:#1a1d21;--muted:#4b5563;--line:#d5d9e0;--card:#f5f6f8;--focus:#1d4ed8;
--warn:#8a3b00;--warnbg:#fff1e3;--bad:#9b1c1c;--badbg:#fde8e8;--ok:#14532d;--okbg:#e3f5e8;--info:#1e3a8a;--infobg:#e6edfd}
@media (prefers-color-scheme:dark){:root{--bg:#14171b;--fg:#eceef2;--muted:#aab2bf;--line:#363c46;--card:#1d2127;--focus:#8ab4ff;
--warn:#ffc78a;--warnbg:#3a2a16;--bad:#ffb4b4;--badbg:#401c1c;--ok:#a6e8b9;--okbg:#17321f;--info:#b6ccff;--infobg:#1f2c4d}}
*{box-sizing:border-box}
body{margin:0;padding:12px;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
h1{font-size:17px;margin:0 0 2px}h2{font-size:15px;margin:14px 0 4px}
.sub{color:var(--muted);margin:0 0 10px}
ul{list-style:none;margin:0;padding:0;border:1px solid var(--line);border-radius:8px;overflow:hidden}
li+li{border-top:1px solid var(--line)}
.row{display:flex;gap:10px;align-items:center;width:100%;padding:10px 12px;background:var(--card);color:inherit;border:0;
font:inherit;text-align:left;cursor:pointer;min-height:44px}
.row:hover{filter:brightness(.97)}
:focus-visible{outline:3px solid var(--focus);outline-offset:-3px}
.grow{flex:1;min-width:0}.t{font-weight:600;overflow-wrap:anywhere}.e{color:var(--muted);font-size:13px}
.badge{display:inline-flex;gap:4px;align-items:center;white-space:nowrap;border:1px solid currentColor;border-radius:999px;
padding:1px 9px;font-size:12px;font-weight:600}
.b-warn{color:var(--warn);background:var(--warnbg)}.b-bad{color:var(--bad);background:var(--badbg)}
.b-ok{color:var(--ok);background:var(--okbg)}.b-info{color:var(--info);background:var(--infobg)}
.score{font-variant-numeric:tabular-nums;color:var(--muted);font-size:13px}
button.back,a.ad{font:inherit;color:var(--focus);background:none;border:0;padding:6px 0;cursor:pointer;text-decoration:underline;min-height:32px}
dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;margin:8px 0}dt{color:var(--muted)}dd{margin:0;overflow-wrap:anywhere}
.pc{margin:4px 0;padding-left:20px;list-style:disc;border:0}.pc li{border:0;padding:1px 0}
.note{border:1px solid var(--line);border-radius:8px;padding:8px 10px;background:var(--card);margin:8px 0}
.slot{margin-top:12px}.btns{display:flex;gap:8px;flex-wrap:wrap}
.act{font:inherit;min-height:44px;padding:8px 16px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer}
.act.primary{background:var(--focus);color:var(--bg);border-color:var(--focus);font-weight:600}
.act.danger{background:var(--bad);color:var(--bg);border-color:var(--bad);font-weight:600}.act:disabled{opacity:.5;cursor:default}
h1[tabindex]:focus{outline:none}
</style></head><body>
<main id="app" aria-live="polite"><h1>Jobwatch</h1><p class="sub">Loading...</p></main>
<script>
(function(){
var app=document.getElementById('app'),pending={},nextId=1,listData=null,lastFocus=null;
function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e}
var BADGE={'draft ready':['b-warn','*'],'awaiting browser press':['b-warn','*'],'failed':['b-bad','x'],'expired':['b-bad','x'],
'outcome unknown':['b-bad','?'],'submitted':['b-ok','+'],'queued':['b-info','...'],'drafting':['b-info','...'],'executing':['b-info','...'],
'cancelled':['b-info','-'],'not started':['b-info','o']};
function badge(state){var b=BADGE[state]||['b-info','o'],s=el('span','badge '+b[0]);s.appendChild(el('span',null,b[1])).setAttribute('aria-hidden','true');s.appendChild(document.createTextNode(state));return s}
function request(method,params){var id=nextId++;window.parent.postMessage({jsonrpc:'2.0',id:id,method:method,params:params},'*');
return new Promise(function(res,rej){pending[id]={res:res,rej:rej};setTimeout(function(){if(pending[id]){delete pending[id];rej(new Error('timeout'))}},20000)})}
function callTool(name,args){
if(window.openai&&window.openai.callTool)return window.openai.callTool(name,args);
return request('tools/call',{name:name,arguments:args})}
function mt(r){return r&&(r._meta||r.meta||(r.result&&r.result._meta))||{}}
function sc(r){return r&&(r.structuredContent||(r.result&&r.result.structuredContent))||null}
var COUNTS=[['needs_you','need you'],['needs_info','need info'],['outcome_unknown','outcome unknown'],['submitted','submitted']];
function countsText(c){var p=[];COUNTS.forEach(function(k){if(c&&c[k[0]])p.push(c[k[0]]+' '+k[1])});return p.join(' · ')||'Nothing needs you'}
function renderList(d){listData=d;app.textContent='';
app.appendChild(el('h1',null,'Your jobs'));app.appendChild(el('p','sub',countsText(d.counts)));
if(!d.jobs||!d.jobs.length){app.appendChild(el('p',null,'No jobs with activity yet.'));return}
var ul=el('ul');d.jobs.forEach(function(j){var li=el('li'),b=el('button','row');b.type='button';
b.setAttribute('aria-label',(j.employer||'Unknown employer')+', '+(j.title||'untitled')+', '+j.state+'. Open details.');
var g=el('span','grow');g.appendChild(el('div','t',j.title||'(untitled)'));g.appendChild(el('div','e',j.employer||'Unknown employer'));
b.appendChild(g);if(j.score!=null)b.appendChild(el('span','score','Score '+j.score));b.appendChild(badge(j.state));
b.addEventListener('click',function(){open(j.posting_id,b)});li.appendChild(b);ul.appendChild(li)});app.appendChild(ul)}
function open(id,from){lastFocus=from||null;app.setAttribute('aria-busy','true');
callTool('job_detail',{posting_id:id}).then(function(r){var d=sc(r);if(d)renderDetail(d,true,mt(r));else fail()},fail)}
function fail(){app.removeAttribute('aria-busy');app.appendChild(el('p','note','Could not load that job. Try again.'))}
function renderDetail(d,fromList,meta){meta=meta||{};app.removeAttribute('aria-busy');app.textContent='';
if(fromList&&listData){var back=el('button','back','Back to jobs');back.type='button';back.addEventListener('click',function(){renderList(listData);
var rows=app.querySelectorAll('button.row');for(var i=0;i<rows.length;i++){if(lastFocus&&rows[i].getAttribute('aria-label')===lastFocus.getAttribute('aria-label')){rows[i].focus();break}}});app.appendChild(back)}
if(!d.found){app.appendChild(el('p',null,'That job was not found.'));return}
var h=el('h1',null,d.title||'(untitled)');h.tabIndex=-1;app.appendChild(h);app.appendChild(el('p','sub',(d.employer||'Unknown employer')+(d.location?' · '+d.location:'')));
var dl=el('dl');function row(k,v){dl.appendChild(el('dt',null,k));var dd=el('dd');if(typeof v==='string')dd.textContent=v;else dd.appendChild(v);dl.appendChild(dd)}
row('State',badge(d.state));if(d.state_detail)row('Detail',d.state_detail);
row('Score',d.score!=null?String(d.score):'Not scored');
row('Documents',d.documents_ready?'Ready'+(d.draft_version?' (draft v'+d.draft_version+')':''):'None ready');app.appendChild(dl);
if(d.why_it_fits){app.appendChild(el('h2',null,'Why it fits'));app.appendChild(el('p',null,d.why_it_fits))}
[['pros','In its favour'],['cons','Against']].forEach(function(k){if(d[k[0]]&&d[k[0]].length){app.appendChild(el('h2',null,k[1]));
var ul=el('ul','pc');d[k[0]].forEach(function(t){ul.appendChild(el('li',null,t))});app.appendChild(ul)}});
if(d.ad_url&&/^https?:\/\//.test(d.ad_url)){var a=el('a','ad','Open the job ad');a.href=d.ad_url;a.target='_blank';a.rel='noopener noreferrer';app.appendChild(a)}
var slot=el('div','slot');slot.id='actions-slot';app.appendChild(slot);
if(d.can_submit&&meta.submit_digest)submitButton(slot,d,meta.submit_digest);else slot.hidden=true;
h.focus()}
function msg(slot,text){var n=slot.querySelector('.status');if(!n){n=el('p','note status');n.setAttribute('role','status');slot.appendChild(n)}n.textContent=text}
function btn(label,cls,fn){var b=el('button','act '+cls,label);b.type='button';b.addEventListener('click',fn);return b}
function submitButton(slot,d,digest){
var box=el('div');var go=btn('Submit application','primary',function(){
box.textContent='';box.appendChild(el('p','note','This sends your application for '+(d.title||'this job')+' at '+(d.employer||'the employer')+' exactly as filled and reviewed. Nothing is sent if the form changed.'));
var row=el('div','btns');row.appendChild(btn('Send to employer','danger',function(){
row.querySelectorAll('button').forEach(function(x){x.disabled=true});
callTool('submit_reviewed',{posting_id:d.posting_id,confirm_digest:digest}).then(function(r){var s=sc(r)||{};
msg(slot,s.status==='queued'?'Queued. Jobwatch presses Submit within 15 minutes if the form is unchanged.':'Submit status: '+(s.status||'unknown')+'.')},
function(){msg(slot,'Not submitted. The reviewed form may have changed; open the job again.')})}));
row.appendChild(btn('Cancel','',function(){box.textContent='';box.appendChild(go)}));box.appendChild(row)});
box.appendChild(go);slot.appendChild(box)}
function renderWork(d,meta){app.removeAttribute('aria-busy');app.textContent='';
var h=el('h1',null,d.status==='awaiting_approval'?'Approval needed':'Jobwatch update');h.tabIndex=-1;app.appendChild(h);
var slot=el('div','slot');slot.id='actions-slot';
if(d.status==='awaiting_approval'){app.appendChild(el('p',null,d.summary));
var row=el('div','btns');['approve','reject'].forEach(function(k){row.appendChild(btn(k==='approve'?'Approve':'Reject',k==='approve'?'primary':'',function(){
row.querySelectorAll('button').forEach(function(x){x.disabled=true});
callTool('decide',{interaction_id:d.interaction_id,decision:k,binding:meta.binding||''}).then(function(r){var n=sc(r);if(n)renderWork(n,mt(r));else msg(slot,'No reply.')},
function(){msg(slot,'That approval is no longer available. Ask Jobwatch again.')})}))});slot.appendChild(row)}
else{app.appendChild(el('p',null,d.decision==='reject'?'Rejected. Nothing was done.':(d.answer||'Done.')));
if(d.declined)app.appendChild(el('p','note','Jobwatch could not ask you about: '+d.declined.join(', ')+'.'))}
app.appendChild(slot);h.focus()}
function show(d,m){if(!d)return;if(d.view==='detail')renderDetail(d,false,m);else if(d.view==='list')renderList(d);else if(d.view==='work')renderWork(d,m||{})}
window.addEventListener('message',function(ev){if(ev.source!==window.parent)return;var m=ev.data;if(!m||m.jsonrpc!=='2.0')return;
if(m.id!==undefined&&pending[m.id]){var p=pending[m.id];delete pending[m.id];m.error?p.rej(m.error):p.res(m.result);return}
if(m.method==='ui/notifications/tool-result')show(m.params&&m.params.structuredContent,m.params&&m.params._meta)},{passive:true});
window.addEventListener('openai:set_globals',function(){if(window.openai&&window.openai.toolOutput)show(window.openai.toolOutput,window.openai.toolResponseMetadata)});
if(window.openai&&window.openai.toolOutput)show(window.openai.toolOutput,window.openai.toolResponseMetadata);
else request('ui/initialize',{appInfo:{name:'jobwatch',version:'1'},appCapabilities:{},protocolVersion:'2025-06-18'}).then(function(){
window.parent.postMessage({jsonrpc:'2.0',method:'ui/notifications/initialized',params:{}},'*')},function(){});
window.__show=show;
})();
</script></body></html>
"""
