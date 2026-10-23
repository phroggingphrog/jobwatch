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


def _message(body):
    # Prior assistant/system/tool text cannot issue instructions or decisions.
    message = body.messages[-1]
    if message.role != 'user':
        raise HTTPException(422, 'last_message_must_be_user')
    content = message.content
    if isinstance(content, list):
        if any(p.get('type') != 'text' or not isinstance(p.get('text'), str) for p in content):
            raise HTTPException(422, 'use_jobwatch_profile_upload')
        content = '\n'.join(p['text'] for p in content)
    if not isinstance(content, str) or not content.strip() or len(content) > 16000:
        raise HTTPException(422, 'invalid_message')
    return content


def _enqueue(person, conversation, body):
    with APIStore(person) as store:
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
        message = _message(body)
        # Retransmission returns the original run. A pending decision is only shown;
        # no message (including "approve") can consume an interaction.
        key = fingerprint([m.model_dump() for m in body.messages])
        previous = store.conn.execute('SELECT id FROM api_runs WHERE request_key=?',
                                      (fingerprint([thread, key]),)).fetchone()
        if previous:
            return _current_run(store, previous[0])
        active = store.conn.execute("SELECT id FROM api_runs WHERE thread_id=? AND state IN "
            "('queued','running','waiting_for_input','waiting_for_approval','interrupted') ORDER BY created DESC LIMIT 1",
            (thread,)).fetchone()
        if active:
            return store.public_run(active[0])
        return store.public_run(store.enqueue(thread, {'message': message}, key))


def _answer(run, controls_url):
    result = run.get('result') or {}
    text = result.get('answer') or ''
    if run['state'] in ('waiting_for_input', 'waiting_for_approval'):
        text += '\n\nJobwatch needs your response in the protected controls page. '
        for item in run['interactions']:
            if not item['answered']:
                text += '\n\n' + (item.get('question') or ('Review operation: ' + str(item.get('operation', 'career work'))))
    elif run.get('error'):
        text += '\n\nJobwatch stopped: ' + run['error'] + '.'
    elif run['state'] in ('queued', 'running'):
        text += '\n\nJobwatch is still working. Check its controls page for progress.'
    elif run['state'] != 'completed':
        text += '\n\nJobwatch run status: ' + run['state'] + '.'
    for outcome in result.get('outcomes') or []:
        text += '\n\nOutcome: ' + json.dumps(outcome, ensure_ascii=False)
    if controls_url:
        text += f'\n\n[Jobwatch controls, uploads and documents]({controls_url}/agent#run={run["id"]})'
    return text.strip() or 'The Jobwatch conversation turn completed.'


def mount(app, require):
    """Enabled explicitly at release; the normal native contract stays unchanged."""
    read, write = require('read'), require('run')
    controls_url = os.environ.get('JOBWATCH_AGENT_PUBLIC_URL', '').rstrip('/')
    if controls_url and not re.fullmatch(r'https://[A-Za-z0-9.-]+(?::[0-9]+)?', controls_url):
        raise ValueError('invalid_agent_public_url')

    @app.get('/v1/models')
    def models(principal=Depends(read)):
        return {'object': 'list', 'data': [{'id': MODEL, 'object': 'model', 'created': 0, 'owned_by': 'jobwatch'}]}

    @app.post('/v1/chat/completions')
    async def completion(body: Completion, request: Request,
                         x_jobwatch_conversation: str = Header(), principal=Depends(write)):
        if body.model != MODEL or not _ID.fullmatch(x_jobwatch_conversation):
            raise HTTPException(422, 'invalid_client_request')
        _message(body)
        run = await asyncio.to_thread(_enqueue, principal.person, x_jobwatch_conversation, body)

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
                        yield chunk({'content': _answer(value, controls_url)})
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
                    choices=[dict(index=0, message={'role': 'assistant', 'content': _answer(value, controls_url)}, finish_reason='stop')])

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
