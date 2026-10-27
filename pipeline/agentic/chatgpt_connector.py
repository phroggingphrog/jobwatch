"""Stage 1 of the ChatGPT connector: read-only tools plus MCP Apps widgets.

Tools only read. Submit, prepare and revise are not here (stages 2 and 3). Every read runs as the
authenticated person; no tool argument names a person. Reuses task_state, the same service the
chat agent's own jobs_overview / task_status tools call.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from urllib.parse import urlparse

from fastmcp import FastMCP
from fastmcp.tools import ToolResult

from jobwatch import users
from jobwatch.config import load_config
from pipeline.agentic import task_state, shortlist, selection
from jobwatch import preference_service
from pipeline.agentic.chat import dispatch, job_connection, job_database
from pipeline.agentic.contracts import AgenticEvaluation
from pipeline.agentic.persistence import latest_result
from pipeline.agentic.runtime import RuntimeErrorSafe, validate_model_payload
from pipeline.agentic import service

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


def _person_config(person: str):
    # Config eagerly reads per-person rules and searches, before a DB is opened.
    with users.use(person):
        return load_config()


def application_overview(person: str, limit: int = 50) -> dict:
    limit = max(1, min(int(limit), 100))
    config = _person_config(person)
    with users.use(person), job_connection(config) as conn:
        rows = task_state.jobs_overview(conn, limit)
        assessments = _assessment_projection(conn, config, [row['posting_id'] for row in rows])
        for row in rows:
            assessment = assessments[row['posting_id']]
            score = assessment.pop('_assessment_score')
            if assessment['assessment_state'] == 'current':
                row['score'] = score
            elif assessment['assessment_state'] != 'not_assessed':
                row['score'] = None
            row.update(assessment)
    return {'view': 'list', 'counts': task_state.overview_counts(rows), 'jobs': rows}


def overview(person: str, limit: int = 50, *, refresh: bool = False) -> dict:
    """Project the current canonical shortlist; activity is never a recommendation."""
    config = _person_config(person)
    with users.use(person):
        if not job_database(config).exists():
            return dict(shortlist._empty('not_built'), view='list', jobs=[], counts=task_state.overview_counts([]))
    with users.use(person), job_connection(config, write=refresh) as conn:
        if refresh:
            shortlist.build_shortlist(conn, config)
        result = shortlist.load_latest(conn, config=config, limit=max(1, min(int(limit), 100)))
        rows = []
        if result['status'] == 'ok':
            _, _, _, runs = preference_service.current_runs(conn, config)
            eligible = {r.posting_id for r in runs if (r.decision.route, r.decision.reason) == ('draft', 'eligible')}
            for entry in result['entries']:
                post = entry['posting']
                card = task_state.task_card(conn, entry['posting_id'])
                rows.append(dict(entry, employer=post.get('company'), title=post.get('title'),
                    score=entry['holistic_score'], state=card['state'], detail=card.get('message', ''),
                    can_prepare=entry['posting_id'] in eligible))
            checked = shortlist.load_latest(conn, config=config, limit=1)
            if checked['status'] != 'ok' or checked.get('shortlist_id') != result.get('shortlist_id'):
                result = shortlist._empty('stale')
                rows = []
        return dict(result, view='list', jobs=rows, counts=task_state.overview_counts([]))


def recommended_detail(person: str, posting_id: int) -> dict:
    listing = overview(person, 100)
    entry = next((row for row in listing['jobs'] if row['posting_id'] == posting_id), None)
    if entry is None:
        return dict(view='detail', found=False, posting_id=posting_id, shortlist_status=listing['status'])
    result = detail(person, posting_id)
    checked = overview(person, 100)
    if checked['status'] != 'ok' or checked.get('shortlist_id') != listing.get('shortlist_id'):
        return dict(view='detail', found=False, posting_id=posting_id, shortlist_status='stale')
    return dict(result, **{k: v for k, v in entry.items() if k not in result},
                shortlist_status='ok', shortlist_entry=entry)


def prepare_selected(person: str, posting_id: int, *, expected_entry_id: str,
                     expected_run_key: str, request_id: str, confirmed: bool) -> dict:
    if confirmed is not True:
        raise RuntimeErrorSafe('confirmation_required')
    config = _person_config(person)
    with users.use(person), job_connection(config, write=True) as conn:
        row = selection.request(conn, config, posting_ids=[posting_id],
            expected_entry_ids={str(posting_id): expected_entry_id},
            expected_run_keys={str(posting_id): expected_run_key}, request_id=request_id,
            actor='person', source='chat')
    state = 'queued' if row['state'] == 'pending_dispatch' else row['state']
    return dict(view='work', status='complete', answer=f'Preparation {state}. Nothing submitted.',
                posting_id=posting_id, state=state, selection_id=row['id'], authorises='preparation_only')


def _assessment_projection(conn, config, posting_ids: list[int]) -> dict[int, dict]:
    """Read validated assessments only when the canonical run key still matches current inputs."""
    results = {}
    candidate_ids = []
    for posting_id in posting_ids:
        try:
            result = latest_result(conn, posting_id, parse=frozenset({'evaluation'}))
        except Exception:
            result = {'evaluation': None}
        results[posting_id] = result
        if result is not None and result.get('evaluation') is not None:
            candidate_ids.append(posting_id)

    current_keys = {}
    for offset in range(0, len(candidate_ids), 20):
        batch = candidate_ids[offset:offset + 20]
        try:
            inventory = service.snapshot_inventory(conn, config, posting_ids=batch, limit=len(batch))
        except Exception:
            continue
        current_keys.update({row['posting_id']: row['run_key'] for row in inventory})

    projected = {}
    for posting_id, result in results.items():
        if result is None:
            projected[posting_id] = {
                'assessment_state': 'not_assessed', 'assessment_reason': None,
                'assessment_summary': None, '_assessment_score': None,
            }
            continue
        raw = result.get('evaluation')
        if raw is None:
            projected[posting_id] = {
                'assessment_state': 'incomplete', 'assessment_reason': None,
                'assessment_summary': None, '_assessment_score': None,
            }
            continue
        current_key = current_keys.get(posting_id)
        if (current_key is None or result.get('run_key') != current_key):
            projected[posting_id] = {
                'assessment_state': 'stale', 'assessment_reason': None,
                'assessment_summary': None, '_assessment_score': None,
            }
            continue
        try:
            evaluation = validate_model_payload(AgenticEvaluation, raw)
        except RuntimeErrorSafe:
            projected[posting_id] = {
                'assessment_state': 'incomplete', 'assessment_reason': None,
                'assessment_summary': None, '_assessment_score': None,
            }
            continue
        if evaluation.run_key.value != current_key:
            projected[posting_id] = {
                'assessment_state': 'stale', 'assessment_reason': None,
                'assessment_summary': None, '_assessment_score': None,
            }
            continue
        report = evaluation.report
        reason = result.get('reason') if type(result.get('reason')) is str else None
        projected[posting_id] = {
            'assessment_state': 'current', 'assessment_reason': reason,
            'assessment_summary': report.get('A', '')[:600],
            '_assessment_score': evaluation.global_score,
        }
    return projected


def detail(person: str, posting_id: int) -> dict:
    if type(posting_id) is not int or posting_id < 1:
        raise RuntimeErrorSafe('invalid_request')
    config = _person_config(person)
    with users.use(person), job_connection(config) as conn:
        conn.row_factory = sqlite3.Row
        post = conn.execute('SELECT title, company, location, url FROM postings WHERE id=?', (posting_id,)).fetchone()
        if post is None:
            return {'view': 'detail', 'posting_id': posting_id, 'found': False,
                    'assessment_state': 'not_assessed', 'assessment_reason': None,
                    'assessment_summary': None}
        has = lambda t: bool(conn.execute('SELECT 1 FROM sqlite_master WHERE name=?', (t,)).fetchone())
        review = conn.execute('SELECT score, reason, pros_json, cons_json FROM ad_reviews WHERE posting_id=?',
                              (posting_id,)).fetchone() if has('ad_reviews') else None
        card = task_state.task_card(conn, posting_id)
        assessment = _assessment_projection(conn, config, [posting_id])[posting_id]
        assessment_score = assessment.pop('_assessment_score')
        ready_digest = _application_and_digest(conn, posting_id)[1]
        draft = conn.execute('SELECT d.version FROM drafts d JOIN applications a ON a.id=d.application_id '
                             "WHERE a.posting_id=? AND d.status='ready' ORDER BY d.version DESC LIMIT 1",
                             (posting_id,)).fetchone() if has('drafts') and has('applications') else None
    return {'view': 'detail', 'posting_id': posting_id, 'found': True, 'employer': post['company'],
            'title': post['title'], 'location': post['location'], 'ad_url': _http_url(post['url']),
            'score': (assessment_score if assessment['assessment_state'] == 'current'
                      else (review['score'] if review and assessment['assessment_state'] == 'not_assessed' else None)),
            'why_it_fits': (assessment['assessment_summary'] if assessment['assessment_state'] == 'current'
                            else (review['reason'] if review and assessment['assessment_state'] == 'not_assessed' else None)),
            'pros': _list(review['pros_json']) if review else [], 'cons': _list(review['cons_json']) if review else [],
            'state': card['state'], 'state_detail': card.get('message') or (card.get('submit') or {}).get('reason') or '',
            **assessment,
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


def submit_reviewed(person: str, posting_id: int, confirm_digest: str) -> dict:
    """Queue the one press for the exact reviewed form. The web process re-checks the live form before pressing."""
    from jobwatch.apply import submit_confirm
    if type(posting_id) is not int or posting_id < 1 or type(confirm_digest) is not str:
        raise RuntimeErrorSafe('invalid_request')
    with users.use(person), job_connection(load_config(), write=True) as conn:
        application_id, current = _application_and_digest(conn, posting_id)
        if current is None:
            raise RuntimeErrorSafe('submit_not_ready')
        if not hmac.compare_digest(confirm_digest, current):
            raise RuntimeErrorSafe('submit_digest_mismatch')
        from pipeline.agentic import task_state
        blocked = task_state.retry_blocked(conn, posting_id)
        if blocked:
            raise RuntimeErrorSafe(blocked)
        approval = hashlib.sha256(('widget-submit:' + current).encode()).hexdigest()   # a double click queues once
        queued = submit_confirm.queue(conn, posting_id=posting_id, application_id=application_id,
                                      confirm_digest=current, approval=approval)
    return {'view': 'submit', 'posting_id': posting_id, **queued}


def _overview_text(data: dict) -> str:
    lines = [f"Shortlist {data['status']}: {len(data['jobs'])} current matches. Labels describe evidence fit, not approval to apply."]
    lines += [f"#{j['posting_id']} {j['employer'] or '?'} - {j['title'] or '?'}: {j['label']}; "
              f"{j['objective_fit']}; unresolved: {', '.join(j['unresolved']) or 'none recorded'}"
              for j in data['jobs'][:10]]
    return '\n'.join(lines)


def _detail_text(d: dict) -> str:
    if not d['found']:
        return f"No job {d['posting_id']} found."
    docs = 'documents ready' if d['documents_ready'] else 'no documents ready'
    score = f", score {d['score']}" if d['score'] is not None else ''
    assessment = f"Assessment {d['assessment_state']}"
    if d['assessment_state'] == 'current':
        assessment += f" ({d['assessment_reason']}): {d['assessment_summary']}"
    return (f"#{d['posting_id']} {d['employer'] or '?'} - {d['title'] or '?'}{score}. "
            f"Application state: {d['state']}; {docs}. {assessment}.")


def register(server: FastMCP, person_from_request) -> None:
    """Add the read-only tools and widget resources to an authenticated server."""

    @server.tool(name='jobs_overview', title='Jobs overview', annotations=READ_ONLY, meta={
        'ui': {'resourceUri': LIST_URI}, 'openai/outputTemplate': LIST_URI,
        'openai/toolInvocation/invoking': 'Reading your jobs', 'openai/toolInvocation/invoked': 'Jobs ready'})
    def jobs_overview_tool(limit: int = 50) -> ToolResult:
        """Read current canonical shortlist matches, including labelled evidence holds. Never raw assessment activity."""
        data = overview(person_from_request(), limit)
        return ToolResult(content=_overview_text(data), structured_content=data)

    @server.tool(name='applications_overview', annotations=READ_ONLY)
    def applications_overview_tool(limit: int = 50) -> dict:
        """Read application history only, never recommendations or assessment-only activity."""
        return application_overview(person_from_request(), limit)

    @server.tool(name='refresh_shortlist', annotations=READ_ONLY | {'readOnlyHint': False})
    def refresh_shortlist_tool(limit: int = 50) -> dict:
        """Rebuild the canonical shortlist from stored assessments without paid model work."""
        return overview(person_from_request(), limit, refresh=True)

    @server.tool(name='assessment_detail', annotations=READ_ONLY)
    def assessment_detail_tool(posting_id: int) -> dict:
        """Explicit diagnostic lookup, including exclusions; never a recommendation."""
        return detail(person_from_request(), posting_id)

    @server.tool(name='application_detail', annotations=READ_ONLY, meta={'ui': {'resourceUri': DETAIL_URI}})
    def application_detail_tool(posting_id: int) -> ToolResult:
        """Read an application's history and document state; not a recommendation."""
        person = person_from_request()
        data = detail(person, posting_id)
        meta = {'submit_digest': submit_digest(person, posting_id)} if data.get('can_submit') else None
        return ToolResult(content=_detail_text(data), structured_content=data, meta=meta)

    @server.tool(name='job_detail', title='Job detail', annotations=READ_ONLY, meta={
        'ui': {'resourceUri': DETAIL_URI}, 'openai/outputTemplate': DETAIL_URI,
        'openai/toolInvocation/invoking': 'Reading the job', 'openai/toolInvocation/invoked': 'Job ready'})
    def job_detail_tool(posting_id: int) -> ToolResult:
        """Employer, title, score, why it fits, state, whether documents are ready, and the ad link for one job.
        Read-only."""
        person = person_from_request()
        data = recommended_detail(person, posting_id)
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
    def prepare_application_tool(posting_id: int, expected_entry_id: str, expected_run_key: str,
                                 request_id: str, confirmed: bool) -> dict:
        """Only after explicit user consent, prepare one exact current eligible shortlist entry. Never Submit."""
        return prepare_selected(person_from_request(), posting_id, expected_entry_id=expected_entry_id,
            expected_run_key=expected_run_key, request_id=request_id, confirmed=confirmed)

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
app.appendChild(el('h1',null,'Your jobs'));app.appendChild(el('p','sub',d.meaning||'Current canonical shortlist'));
if(!d.jobs||!d.jobs.length){app.appendChild(el('p',null,'No current shortlist matches. Refresh the shortlist or inspect discovery progress.'));return}
var ul=el('ul');d.jobs.forEach(function(j){var li=el('li'),b=el('button','row');b.type='button';
b.setAttribute('aria-label',(j.employer||'Unknown employer')+', '+(j.title||'untitled')+', '+j.state+'. Open details.');
var g=el('span','grow');g.appendChild(el('div','t',j.title||'(untitled)'));g.appendChild(el('div','e',j.employer||'Unknown employer'));
g.appendChild(el('div','e',(j.label||'').replaceAll('_',' ')));g.appendChild(el('div','e',j.objective_fit||''));b.appendChild(g);
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
