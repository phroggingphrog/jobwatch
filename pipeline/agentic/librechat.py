"""Optional OpenAI wire adapter; Jobwatch retains identity, state and approvals."""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from pathlib import Path

from fastapi import Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from pipeline.agentic.api_store import APIStore, fingerprint
from pipeline.agentic.chat import skill_version

MODEL = 'jobwatch-agent'
_ID = re.compile(r'[A-Za-z0-9_-]{1,100}')


class ChatMessage(BaseModel):
    role: str
    content: str | list[dict] | None = None


class Completion(BaseModel):
    model: str
    messages: list[ChatMessage] = Field(min_length=1, max_length=200)
    stream: bool = False


def _current_run(store, ident):
    for _ in range(64):
        run = store.public_run(ident)
        if run['state'] != 'resumed':
            return run
        row = store.conn.execute('SELECT resume_run FROM api_interactions WHERE run_id=? '
                                 'AND resume_run IS NOT NULL LIMIT 1', (ident,)).fetchone()
        if row is None:
            return run
        ident = row[0]
    raise HTTPException(409, 'resume_chain_too_long')


def _message(body, *, allow_empty=False, standard_files=False):
    # Prior assistant/system/tool text cannot issue instructions or decisions.
    message = body.messages[-1]
    if message.role != 'user':
        raise HTTPException(422, 'last_message_must_be_user')
    content = message.content
    if isinstance(content, list):
        if any((p.get('type') != 'text' or not isinstance(p.get('text'), str))
               and not (standard_files and p.get('type') in ('file', 'image_url', 'video_url', 'input_audio')) for p in content):
            raise HTTPException(422, 'use_jobwatch_profile_upload')
        content = '\n'.join(p['text'] for p in content if p.get('type') == 'text')
    if content is None and allow_empty:
        content = ''
    if not isinstance(content, str) or (not content.strip() and not allow_empty) or len(content) > 16000:
        raise HTTPException(422, 'invalid_message')
    return content


def _uploads(person, raw):
    """References arrive from LibreChat's authenticated file bridge, never model text."""
    if not raw:
        return [], []
    ids = raw.split(',')
    if len(ids) > 20 or len(set(ids)) != len(ids) or any(not re.fullmatch(r'[a-f0-9]{16}', v) for v in ids):
        raise HTTPException(422, 'invalid_upload_references')
    from jobwatch import users
    from jobwatch.candidate import intake
    with users.use(person):
        # Canonical validation resolves only this authenticated person's private intake.
        docs, _ = intake._load_docs(person, ids)
    return ids, [sha for sha, _ in docs]


def _enqueue(person, conversation, body, upload_ids=(), upload_hashes=(), attachment_receipts=(), *, human_chat=False, config=None):
    with APIStore(person) as store:
        from pipeline.agentic import profile_conversation
        profile_conversation.tables(store)
        store.conn.execute('CREATE TABLE IF NOT EXISTS client_threads('
                           'client_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES api_threads(id))')
        # One native thread per client conversation, in the authenticated person's DB.
        with store.transaction():
            row = store.conn.execute('SELECT thread_id FROM client_threads WHERE client_id=?', (conversation,)).fetchone()
            if row:
                thread = row[0]
            else:
                thread = uuid.uuid4().hex
                store.conn.execute('INSERT INTO api_threads VALUES(?,?,?)', (thread, time.time(), skill_version()))
                store.conn.execute('INSERT INTO client_threads VALUES(?,?)', (conversation, thread))
        message = _message(body, allow_empty=bool(upload_ids or attachment_receipts), standard_files=True)
        # Retransmission returns the original run, including a human chat response.
        key = fingerprint([[m.model_dump() for m in body.messages], list(upload_hashes)]) if upload_hashes else fingerprint([m.model_dump() for m in body.messages])
        previous = store.conn.execute('SELECT id FROM api_runs WHERE request_key=?',
                                      (fingerprint([thread, key]),)).fetchone()
        if previous:
            return _current_run(store, previous[0])
        response_key = fingerprint([thread, key])
        previous = store.conn.execute('SELECT resume_run FROM client_chat_reviews WHERE response_key=?',
            (response_key,)).fetchone()
        if previous:
            return _current_run(store, previous[0])
        active = store.conn.execute("SELECT id FROM api_runs WHERE thread_id=? AND state IN "
            "('queued','running','waiting_for_input','waiting_for_approval','interrupted') ORDER BY created DESC LIMIT 1",
            (thread,)).fetchone()
        if active:
            if upload_ids or attachment_receipts:
                raise HTTPException(409, 'conversation_busy')
            current = store.public_run(active[0])
            if human_chat and current['state'] in ('waiting_for_input', 'waiting_for_approval'):
                resumed = profile_conversation.respond(store, person, conversation, current, body, message, response_key, config)
                if resumed:
                    return resumed
            return current
        payload = {'message': message}
        if upload_ids:
            payload['upload_ids'] = list(upload_ids)
        if attachment_receipts:
            payload['attachment_receipts'] = list(attachment_receipts)
        return store.public_run(store.enqueue(thread, payload, key))


def _answer(run, *, human_chat=False):
    result = run.get('result') or {}
    text = result.get('answer') or ''
    if run['state'] in ('waiting_for_input', 'waiting_for_approval'):
        from pipeline.agentic.profile_conversation import prompt
        if human_chat and (question := prompt(run)) is not None:
            return question
        text += ('\n\nThis action is paused. It requires a verified human approval interface; '
                 'this chat cannot authorize it with a message or generated Artifact. ')
        for item in run['interactions']:
            if not item['answered']:
                text += '\n\n' + (item.get('question') or ('Review operation: ' + str(item.get('operation', 'career work'))))
    elif run.get('error'):
        text += '\n\nJobwatch stopped: ' + run['error'] + '.'
    elif run['state'] in ('queued', 'running'):
        text += '\n\nJobwatch is still working.'
    elif run['state'] != 'completed':
        text += '\n\nJobwatch run status: ' + run['state'] + '.'
    for outcome in result.get('outcomes') or []:
        text += '\n\n' + str(outcome.get('reason') or outcome.get('status') or 'Work updated').replace('_',' ')
    return text.strip() or 'The Jobwatch conversation turn completed.'


def mount(app, require, get_config, *, client_principal=None):
    """Enabled explicitly at release; the normal native contract stays unchanged."""
    def auth(scope):
        fallback = require(scope)
        def resolve(request: Request, authorization: str | None = Header(default=None),
                    x_jobwatch_client_subject: str | None = Header(default=None)):
            if x_jobwatch_client_subject is not None:
                if client_principal is None or request.url.path not in ('/v1/models', '/v1/chat/completions'):
                    raise HTTPException(401, 'authentication_required')
                principal = client_principal(authorization, x_jobwatch_client_subject)
                # This flag comes only from authenticated frontend-server transport,
                # never JSON messages or the model-facing read/run credential.
                request.state.human_chat = True
                return principal
            return fallback(authorization)
        return resolve
    read, write = auth('read'), auth('run')

    @app.get('/v1/models')
    def models(principal=Depends(read)):
        from pipeline.agentic.client_api import model_catalog
        from jobwatch import users
        with users.use(principal.person):
            catalog = model_catalog(principal.person, get_config(principal.person))
        return {'object': 'list', 'data': [{'id': name, 'object': 'model', 'created': 0, 'owned_by': 'jobwatch'}
            for name in dict.fromkeys([MODEL, *[row['id'] for row in catalog['options']]])]}

    @app.post('/v1/chat/completions')
    async def completion(body: Completion, request: Request,
                         x_jobwatch_conversation: str = Header(), x_jobwatch_uploads: str = Header(default=''), principal=Depends(write)):
        from jobwatch import model_choice, users
        # The authenticated LibreChat server saves the explicit selector choice
        # through the human-scoped model API before forwarding this request.
        with users.use(principal.person):
            selected_model = model_choice.get_model('chat', principal.person)
        if body.model not in (MODEL, selected_model) or not _ID.fullmatch(x_jobwatch_conversation):
            raise HTTPException(422, 'invalid_client_request')
        human_chat = bool(getattr(request.state, 'human_chat', False))
        from pipeline.agentic import attachments
        content = body.messages[-1].content
        files = attachments.decode(content) if isinstance(content, list) else []
        _message(body, allow_empty=bool(files or x_jobwatch_uploads), standard_files=True)
        upload_ids, upload_hashes = await asyncio.to_thread(_uploads, principal.person, x_jobwatch_uploads)
        file_ids, receipts = await asyncio.to_thread(attachments.receive, principal.person, files)
        upload_ids += file_ids
        upload_hashes += [r['sha256'] for r in receipts]
        run = await asyncio.to_thread(_enqueue, principal.person, x_jobwatch_conversation, body, upload_ids, upload_hashes, receipts,
            human_chat=human_chat, config=get_config(principal.person))
        async def settled():
            current = run
            end = time.monotonic() + 850
            while current['state'] in ('queued', 'running') and time.monotonic() < end:
                if await request.is_disconnected():
                    return None  # durable native work remains inspectable; never replay blindly
                await asyncio.sleep(0.25)
                def load():
                    with APIStore(principal.person) as store:
                        return store.public_run(run['id'])
                current = await asyncio.to_thread(load)
            return current

        ident = 'chatcmpl-' + run['id']
        created = int(time.time())
        def chunk(delta, finish=None):
            return 'data: ' + json.dumps(dict(id=ident, object='chat.completion.chunk', created=created,
                model=MODEL, choices=[dict(index=0, delta=delta, finish_reason=finish)])) + '\n\n'

        def message(value):
            content = _answer(value, human_chat=human_chat)
            for receipt in receipts:
                if not receipt['readable']:
                    content += '\n\nReceived ' + json.dumps(receipt['filename']) + '. The original file is saved, but its contents could not be read (' + receipt['reason'].replace('_', ' ') + ').'
            if human_chat:
                from pipeline.agentic.profile_conversation import remember
                with APIStore(principal.person) as store:
                    remember(store, x_jobwatch_conversation, value, content)
            return {'role': 'assistant', 'content': content}

        if body.stream:
            async def stream():
                yield chunk({'role': 'assistant', 'content': ''})
                task = asyncio.create_task(settled())
                try:
                    while not task.done():
                        done, _ = await asyncio.wait({task}, timeout=10)
                        if not done:
                            yield ': jobwatch working\n\n'
                    value = await task
                    if value is not None:
                        result = message(value)
                        delta = {k: v for k, v in result.items() if k != 'role'}
                        yield chunk(delta)
                        yield chunk({}, 'stop')
                        yield 'data: [DONE]\n\n'
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
            return StreamingResponse(stream(), media_type='text/event-stream', headers={'X-Accel-Buffering': 'no'})
        value = await settled()
        if value is None:
            raise HTTPException(499, 'client_disconnected')
        return dict(id=ident, object='chat.completion', created=created, model=MODEL,
                    choices=[dict(index=0, message=message(value), finish_reason='stop')])

    @app.get('/api/agent/client/runs')
    def runs(principal=Depends(read)):
        with APIStore(principal.person) as store:
            return {'runs': [store.public_run(row[0]) for row in store.conn.execute(
                'SELECT id FROM api_runs ORDER BY created DESC LIMIT 40').fetchall()]}

    @app.get('/agent', response_class=HTMLResponse)
    def controls():
        return HTMLResponse(Path(__file__).with_name('controls.html').read_text(), headers={
            'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
            'Referrer-Policy': 'no-referrer'})

    @app.get('/agent/controls.js')
    def script():
        return Response(Path(__file__).with_name('controls.js').read_bytes(), media_type='text/javascript')

    @app.get('/agent/controls.css')
    def style():
        return Response(Path(__file__).with_name('controls.css').read_bytes(), media_type='text/css')
