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
_VIEW = re.compile(r'(?:jobwatch_view(?:_mcp_jobwatch)?|view_mcp_jobwatch)')


class ChatMessage(BaseModel):
    role: str
    content: str | list[dict] | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None


class Completion(BaseModel):
    model: str
    messages: list[ChatMessage] = Field(min_length=1, max_length=200)
    stream: bool = False
    tools: list[dict] = Field(default_factory=list, max_length=100)


def _view_tool(body):
    names = [t.get('function', {}).get('name', '') for t in body.tools if t.get('type') == 'function']
    names = [n for n in names if _VIEW.fullmatch(n)]
    return names[0] if len(names) == 1 else None


def _continuation(person, conversation, body):
    """Tool text is untrusted. Resolve only an own-conversation native run."""
    last = body.messages[-1]
    if last.role != 'tool' or len(body.messages) < 2:
        raise HTTPException(422, 'invalid_tool_continuation')
    previous = body.messages[-2]
    calls = previous.tool_calls or []
    if previous.role != 'assistant' or len(calls) != 1:
        raise HTTPException(422, 'invalid_tool_continuation')
    call = calls[0]
    try:
        ident = json.loads(call['function']['arguments'])['run_id']
        if (call['id'] != last.tool_call_id or not _ID.fullmatch(ident)
                or not _VIEW.fullmatch(call['function']['name'])):
            raise ValueError
        with APIStore(person) as store:
            if not store.conn.execute("SELECT 1 FROM sqlite_master WHERE name='client_threads'").fetchone():
                raise ValueError
            row = store.conn.execute('SELECT r.id FROM api_runs r JOIN client_threads c '
                'ON c.thread_id=r.thread_id WHERE r.id=? AND c.client_id=?', (ident, conversation)).fetchone()
            if row is None:
                raise ValueError
            return _current_run(store, ident)
    except (ValueError, TypeError, KeyError):
        raise HTTPException(422, 'invalid_tool_continuation') from None


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


def _answer(run, controls_url, *, inline=False):
    result = run.get('result') or {}
    text = result.get('answer') or ''
    if run['state'] in ('waiting_for_input', 'waiting_for_approval'):
        text += ('\n\nRespond in the Jobwatch panel below. ' if inline else
                 '\n\nReconnect the interactive Jobwatch card to answer here. ')
        for item in run['interactions']:
            if not item['answered']:
                text += '\n\n' + (item.get('question') or ('Review operation: ' + str(item.get('operation', 'career work'))))
    elif run.get('error'):
        text += '\n\nJobwatch stopped: ' + run['error'] + '.'
    elif run['state'] in ('queued', 'running'):
        text += ('\n\nJobwatch is working. Progress appears in the panel.' if inline else
                 '\n\nJobwatch is still working. Reconnect the interactive card for progress.')
    elif run['state'] != 'completed':
        text += '\n\nJobwatch run status: ' + run['state'] + '.'
    for outcome in result.get('outcomes') or []:
        if outcome.get('status') != 'view':
            text += '\n\n' + str(outcome.get('reason') or outcome.get('status') or 'Work updated').replace('_',' ')
    return text.strip() or 'The Jobwatch conversation turn completed.'


def mount(app, require, get_config):
    """Enabled explicitly at release; the normal native contract stays unchanged."""
    read, write = require('read'), require('run')
    controls_url = os.environ.get('JOBWATCH_AGENT_PUBLIC_URL', '').rstrip('/')
    if controls_url and not re.fullmatch(r'https://[A-Za-z0-9.-]+(?::[0-9]+)?', controls_url):
        raise ValueError('invalid_agent_public_url')

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
                         x_jobwatch_conversation: str = Header(), principal=Depends(write)):
        from jobwatch import model_choice, users
        # The authenticated LibreChat server saves the explicit selector choice
        # through the human-scoped model API before forwarding this request.
        with users.use(principal.person):
            selected_model = model_choice.get_model('chat', principal.person)
        if body.model not in (MODEL, selected_model) or not _ID.fullmatch(x_jobwatch_conversation):
            raise HTTPException(422, 'invalid_client_request')
        continuation = body.messages[-1].role == 'tool'
        if continuation:
            run = await asyncio.to_thread(_continuation, principal.person, x_jobwatch_conversation, body)
        else:
            _message(body)
            run = await asyncio.to_thread(_enqueue, principal.person, x_jobwatch_conversation, body)
        view = _view_tool(body) if not continuation else None
        inline = bool(view or continuation or os.environ.get('JOBWATCH_MCP_APP_ENABLED') == 'true')

        async def settled():
            current = run
            if view:
                return current  # mount the panel immediately; it reads durable progress itself
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
            if view:
                return {'role': 'assistant', 'content': '', 'tool_calls': [{
                    'id': 'call_' + run['id'], 'type': 'function', 'function': {
                        'name': view, 'arguments': json.dumps({'run_id': run['id']})}}]}
            return {'role': 'assistant', 'content': _answer(value, controls_url, inline=inline)}

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
                        if view:
                            delta['tool_calls'][0]['index'] = 0
                        yield chunk(delta)
                        yield chunk({}, 'tool_calls' if view else 'stop')
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
                    choices=[dict(index=0, message=message(value), finish_reason='tool_calls' if view else 'stop')])

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
