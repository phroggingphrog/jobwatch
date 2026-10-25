"""Agent Client Protocol (ACP) adapter: run the Jobwatch chat agent inside Toad or any ACP client.

Speaks ACP over stdio (`jobwatch-acp`). The adapter only translates; Jobwatch's own gates stay
authoritative (exact-form digests, one turn per person, `human_decision=True` on every answer).

- session/new      -> a new chat thread id for the current person
- session/prompt   -> `chat.dispatch()`; `Execution(emit=...)` events become session/update
                      notifications (agent_message_chunk, tool_call, tool_call_update)
- approvals        -> session/request_permission (Approve / Reject); the choice is sent back as
                      `decisions=[...]`. A new prompt while an approval is pending rejects it.
- questions        -> the question is shown as a message; the next prompt is the answer
- session/cancel   -> the same cancel flag the TUI uses (`Execution(cancelled=...)`)

No filesystem or terminal capability is used or advertised: the client's files are never touched.
"""
from __future__ import annotations

import asyncio
import threading
import uuid
from typing import Any

from jobwatch import users
from jobwatch.config import load_config
from pipeline.agentic.chat import dispatch
from pipeline.agentic.execution import Execution
from pipeline.agentic.runtime import RuntimeErrorSafe

_MAX_ROUNDS = 8


class _Session:
    def __init__(self, person: str, thread_id: str) -> None:
        self.person = person
        self.thread_id = thread_id
        self.checkpoint: str | None = None
        self.pending: list[dict] = []
        self.busy = False
        self.cancel = threading.Event()


class JobwatchACPAgent:
    """Implements the ACP `Agent` protocol; `conn` is the client connection."""

    def __init__(self) -> None:
        self.conn: Any = None
        self.sessions: dict[str, _Session] = {}

    def on_connect(self, conn: Any) -> None:
        self.conn = conn

    # ------------------------------------------------------------ lifecycle
    async def initialize(self, protocol_version: int, client_capabilities: Any = None,
                         client_info: Any = None, **kwargs: Any):
        from acp.schema import AgentCapabilities, Implementation, InitializeResponse, PromptCapabilities
        return InitializeResponse(
            protocol_version=min(protocol_version, 1),
            agent_capabilities=AgentCapabilities(load_session=False,
                                                 prompt_capabilities=PromptCapabilities()),
            agent_info=Implementation(name='jobwatch', title='Jobwatch career agent', version='0.1.0'),
        )

    async def new_session(self, cwd: str = '', mcp_servers: Any = None, **kwargs: Any):
        from acp.schema import NewSessionResponse
        sid = f'acp-{uuid.uuid4().hex[:16]}'
        self.sessions[sid] = _Session(users.current(), sid)
        return NewSessionResponse(session_id=sid)

    async def authenticate(self, method_id: str, **kwargs: Any):
        return None

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        session = self.sessions.get(session_id)
        if session:
            session.cancel.set()

    # --------------------------------------------------------------- prompt
    async def prompt(self, session_id: str, prompt: list, **kwargs: Any):
        from acp.schema import PromptResponse
        session = self.sessions.get(session_id)
        if session is None:
            raise ValueError('unknown session')
        text = '\n'.join(getattr(b, 'text', '') for b in prompt if getattr(b, 'type', '') == 'text').strip()
        if not text:
            await self._say(session_id, 'Send some text to ask Jobwatch.')
            return PromptResponse(stop_reason='end_turn')
        if session.busy:
            await self._say(session_id, 'This session is already working on a turn.')
            return PromptResponse(stop_reason='end_turn')
        session.busy = True
        session.cancel.clear()
        try:
            return PromptResponse(stop_reason=await self._turn(session_id, session, text))
        finally:
            session.busy = False

    async def _turn(self, sid: str, session: _Session, text: str) -> str:
        message: str | None = text
        decisions: list[dict] | None = None
        if session.pending:
            if all(i['type'] == 'question' for i in session.pending):
                message, decisions = None, [{'type': 'respond', 'message': text} for _ in session.pending]
            else:   # a new prompt supersedes an unanswered approval: reject it, then ask afresh
                decisions = [{'type': 'reject'} for _ in session.pending]
            session.pending = []
        for _ in range(_MAX_ROUNDS):
            try:
                result = await self._dispatch(sid, session, message, decisions)
            except RuntimeErrorSafe as exc:
                code = str(exc)
                if code == 'cancelled':
                    return 'cancelled'
                await self._say(sid, 'Another turn for this person is already running; try again shortly.'
                                if code == 'person_busy' else f'Jobwatch could not run this turn: {code}')
                return 'end_turn'
            session.checkpoint = result.get('checkpoint_id') or session.checkpoint
            if result.get('answer'):
                await self._say(sid, str(result['answer']))
            pending = [i for i in (result.get('interactions') or []) if i.get('type') in ('approval', 'question')]
            if not pending:
                return 'end_turn'
            if any(i['type'] == 'question' for i in pending):
                session.pending = pending
                for item in pending:
                    if item['type'] == 'question':
                        await self._say(sid, str(item.get('question') or 'Jobwatch asks:'))
                return 'end_turn'
            decisions = []
            for item in pending:
                choice = await self._ask_permission(sid, item)
                if choice is None:           # client cancelled the request: leave it pending
                    session.pending = pending
                    return 'cancelled'
                decisions.append({'type': 'approve' if choice else 'reject'})
            message = None
        await self._say(sid, 'Stopped after several rounds of approvals; send another message to continue.')
        return 'max_turn_requests'

    async def _dispatch(self, sid: str, session: _Session, message: str | None,
                        decisions: list[dict] | None) -> dict:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        execution = Execution(uuid.uuid4().hex,
                              emit=lambda kind, data: loop.call_soon_threadsafe(queue.put_nowait, (kind, data)),
                              cancelled=session.cancel.is_set)

        def call() -> dict:
            with users.use(session.person):
                return dispatch(person=session.person, thread_id=session.thread_id, message=message,
                                decisions=decisions, human_decision=bool(decisions), config=load_config(),
                                execution=execution, expected_checkpoint=session.checkpoint)

        future = asyncio.ensure_future(asyncio.to_thread(call))
        future.add_done_callback(lambda _f: queue.put_nowait(None))
        tools: dict[str, list[str]] = {}
        while (item := await queue.get()) is not None:
            await self._forward(sid, item[0], item[1], tools)
        return future.result()

    # ---------------------------------------------------------- translation
    async def _forward(self, sid: str, kind: str, data: dict, tools: dict[str, list[str]]) -> None:
        from acp.helpers import start_tool_call, update_tool_call
        name = str(data.get('tool') or data.get('name') or 'tool')
        if kind == 'tool_started':
            call_id = f'{name}-{uuid.uuid4().hex[:8]}'
            tools.setdefault(name, []).append(call_id)
            await self.conn.session_update(sid, start_tool_call(call_id, name, kind='other', status='in_progress'))
        elif kind == 'tool_finished' and tools.get(name):
            await self.conn.session_update(sid, update_tool_call(tools[name].pop(0), status='completed'))
        elif kind == 'execution_error':
            await self._say(sid, f'Error: {data.get("error") or "execution error"}')

    async def _say(self, sid: str, text: str) -> None:
        from acp.helpers import update_agent_message_text
        await self.conn.session_update(sid, update_agent_message_text(text))

    async def _ask_permission(self, sid: str, item: dict) -> bool | None:
        """True = approve, False = reject, None = the client cancelled the request."""
        from acp.schema import PermissionOption, ToolCallUpdate
        operation = str(item.get('operation') or 'operation')
        title = f'{operation}: {item.get("summary") or "needs your approval"}'
        raw = {k: item[k] for k in ('posting_id', 'summary') if item.get(k) is not None}
        reply = await self.conn.request_permission(
            session_id=sid,
            tool_call=ToolCallUpdate(tool_call_id=str(item.get('interaction_id') or operation), title=title,
                                     kind='other', status='pending', raw_input=raw),
            options=[PermissionOption(option_id='approve', name='Approve', kind='allow_once'),
                     PermissionOption(option_id='reject', name='Reject', kind='reject_once')])
        outcome = reply.outcome
        if getattr(outcome, 'outcome', '') != 'selected':
            return None
        return outcome.option_id == 'approve'


def main() -> int:
    try:
        from acp import run_agent
    except ImportError:
        raise SystemExit('jobwatch-acp needs the acp extra: uv pip install -e ".[acp]"')
    asyncio.run(run_agent(JobwatchACPAgent()))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
