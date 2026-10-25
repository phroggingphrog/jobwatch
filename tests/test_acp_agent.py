"""ACP adapter driven in-process with a fake client; dispatch is replaced, no model is called."""
import asyncio
import time

import pytest

pytest.importorskip('acp')

from acp.schema import AllowedOutcome, DeniedOutcome, RequestPermissionResponse, TextContentBlock  # noqa: E402

from pipeline.agentic import acp_agent  # noqa: E402
from pipeline.agentic.runtime import RuntimeErrorSafe  # noqa: E402

APPROVAL = {'type': 'approval', 'interaction_id': 'a-0', 'posting_id': 7, 'operation': 'submit_application',
            'binding': None, 'summary': 'Submit job 7'}


class FakeClient:
    def __init__(self, choice='approve'):
        self.updates, self.requests, self.choice = [], [], choice

    async def session_update(self, session_id, update, **kw):
        self.updates.append(update)

    async def request_permission(self, session_id, tool_call, options, **kw):
        self.requests.append((tool_call, options))
        if self.choice == 'cancel':
            return RequestPermissionResponse(outcome=DeniedOutcome(outcome='cancelled'))
        return RequestPermissionResponse(outcome=AllowedOutcome(outcome='selected', option_id=self.choice))


def _setup(monkeypatch, tmp_path, client, script):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    calls = []

    def fake(**kw):
        calls.append(kw)
        kw['execution'].event('tool_started', tool='inspect_job')
        kw['execution'].event('tool_finished', tool='inspect_job')
        return script(kw)

    monkeypatch.setattr(acp_agent, 'dispatch', fake)
    agent = acp_agent.JobwatchACPAgent()
    agent.on_connect(client)
    return agent, calls


def _prompt(agent, sid, text):
    return agent.prompt(sid, [TextContentBlock(type='text', text=text)])


def test_initialize_session_prompt_updates(monkeypatch, tmp_path):
    client = FakeClient()
    agent, calls = _setup(monkeypatch, tmp_path, client,
                          lambda kw: {'status': 'completed', 'answer': 'hello', 'checkpoint_id': 'c1'})

    async def run():
        init = await agent.initialize(1)
        assert init.agent_info.name == 'jobwatch' and init.agent_capabilities.load_session is False
        sid = (await agent.new_session('/x')).session_id
        reply = await _prompt(agent, sid, 'hi')
        return reply, sid
    reply, sid = asyncio.run(run())
    assert reply.stop_reason == 'end_turn'
    assert [u.session_update for u in client.updates] == ['tool_call', 'tool_call_update', 'agent_message_chunk']
    assert client.updates[2].content.text == 'hello'
    assert calls[0]['thread_id'] == sid and calls[0]['message'] == 'hi' and not calls[0]['human_decision']


def test_permission_round_trip_approves_and_rejects(monkeypatch, tmp_path):
    def script(kw):
        if kw['decisions']:
            return {'status': 'completed', 'answer': 'done', 'checkpoint_id': 'c2'}
        return {'status': 'interrupted', 'answer': '', 'checkpoint_id': 'c1', 'interactions': [APPROVAL]}

    for choice, expected in (('approve', 'approve'), ('reject', 'reject')):
        client = FakeClient(choice)
        agent, calls = _setup(monkeypatch, tmp_path, client, script)

        async def run():
            sid = (await agent.new_session('/x')).session_id
            return await _prompt(agent, sid, 'submit it')
        assert asyncio.run(run()).stop_reason == 'end_turn'
        assert client.requests[0][0].raw_input == {'posting_id': 7, 'summary': 'Submit job 7'}
        assert calls[-1]['decisions'] == [{'type': expected}] and calls[-1]['human_decision'] is True
        assert calls[-1]['message'] is None and calls[-1]['expected_checkpoint'] == 'c1'


def test_cancelled_permission_stays_pending_then_new_prompt_rejects(monkeypatch, tmp_path):
    client = FakeClient('cancel')
    agent, calls = _setup(monkeypatch, tmp_path, client,
                          lambda kw: {'status': 'interrupted', 'checkpoint_id': 'c1', 'interactions': [APPROVAL]}
                          if not kw['decisions'] else {'status': 'completed', 'answer': 'ok'})

    async def run():
        sid = (await agent.new_session('/x')).session_id
        first = await _prompt(agent, sid, 'submit')
        second = await _prompt(agent, sid, 'never mind')
        return first, second
    first, second = asyncio.run(run())
    assert first.stop_reason == 'cancelled'
    assert calls[-1]['decisions'] == [{'type': 'reject'}] and calls[-1]['message'] == 'never mind'


def test_session_cancel_sets_the_turn_flag(monkeypatch, tmp_path):
    client = FakeClient()

    def script(kw):
        deadline = time.monotonic() + 3
        while not kw['execution'].cancelled() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert kw['execution'].cancelled() is True
        raise RuntimeErrorSafe('cancelled')
    agent, _ = _setup(monkeypatch, tmp_path, client, script)

    async def run():
        sid = (await agent.new_session('/x')).session_id
        task = asyncio.ensure_future(_prompt(agent, sid, 'long job'))
        await asyncio.sleep(0)       # the turn has started and cleared the flag...
        await agent.cancel(sid)      # ...so cancel now, before the worker thread reads it
        return await task
    assert asyncio.run(run()).stop_reason == 'cancelled'
