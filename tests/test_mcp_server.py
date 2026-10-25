"""The optional MCP adapter: what it can put to a person, and what it does with the rest.

These tests pin documented behaviour rather than asserting it is the behaviour we want. On this
path the connected MCP host is the human-approval boundary: there is one bearer token, it carries
no scope separation, and an accepted elicitation becomes an approval. CHAT.md says so; the native
HTTP API is the path with a separate approve-scoped credential.
"""
import json
import types

import pytest

pytest.importorskip('fastmcp')

from mcp.types import ElicitResult                                              # noqa: E402

from pipeline.agentic import mcp_server                                         # noqa: E402
from pipeline.agentic.chat import GATED                                         # noqa: E402
from pipeline.agentic.runtime import RuntimeErrorSafe                           # noqa: E402

PRESENTABLE = ('run_career_ops', 'assess_job', 'prepare_application', 'prepare_interview',
               'draft_followup', 'submit_application')


def approval(operation, index=0):
    return {'type': 'approval', 'interaction_id': f'approval-{index}', 'operation': operation,
            'posting_id': 42, 'binding': {'operation': operation, 'arguments': {'application_id': 42}},
            'summary': 'Tool execution requires approval'}


def test_the_adapter_words_six_operations_and_names_the_rest():
    requests, unpresentable = mcp_server._requests([approval(op, i) for i, op in enumerate(GATED)])
    assert sorted(unpresentable) == sorted(set(GATED) - set(PRESENTABLE))
    assert len(requests) == len(PRESENTABLE)
    for operation in PRESENTABLE:
        _, request = mcp_server._input_request(approval(operation), 0)
        assert '42' in request.params.message


def test_an_operation_it_cannot_word_is_rejected_so_the_thread_stays_usable(monkeypatch):
    """Raising left the interrupt checkpointed, and every later message on the thread hit it again."""
    calls = []

    def fake_dispatch(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {'status': 'interrupted', 'checkpoint_id': 'cp-1', 'interactions': [approval('profile_confirm')]}
        return {'status': 'complete', 'answer': 'I cannot confirm your profile from this client.',
                'todos': [], 'tools': ['profile_confirmation']}

    monkeypatch.setattr(mcp_server, 'dispatch', fake_dispatch)
    ctx = types.SimpleNamespace(request_state=None, input_responses=None)
    result = mcp_server._turn(person='owner', operation='start', message='Confirm my profile', ctx=ctx)
    assert result['status'] == 'complete' and result['refused_operations'] == ['profile_confirm']
    assert calls[1]['decisions'] == [{'type': 'reject'}] and calls[1]['human_decision'] is True
    assert calls[1]['expected_checkpoint'] == 'cp-1'


def test_a_turn_that_only_offers_unpresentable_work_does_not_loop_forever(monkeypatch):
    monkeypatch.setattr(mcp_server, 'dispatch', lambda **kwargs: {
        'status': 'interrupted', 'checkpoint_id': 'cp', 'interactions': [approval('select_jobs')]})
    ctx = types.SimpleNamespace(request_state=None, input_responses=None)
    with pytest.raises(RuntimeErrorSafe) as exc:
        mcp_server._turn(person='owner', operation='start', message='Select everything', ctx=ctx)
    assert exc.value.code == 'unsupported_chat_interaction'


def test_a_presentable_approval_is_still_handed_to_the_host(monkeypatch):
    monkeypatch.setattr(mcp_server, 'dispatch', lambda **kwargs: {
        'status': 'interrupted', 'checkpoint_id': 'cp', 'interactions': [approval('submit_application')]})
    ctx = types.SimpleNamespace(request_state=None, input_responses=None)
    result = mcp_server._turn(person='owner', operation='start', message='Submit it', ctx=ctx, thread_id='t1')
    state = json.loads(result.request_state)
    assert list(result.input_requests) == ['interaction_0']
    assert state['person'] == 'owner' and state['thread_id'] == 't1' and state['checkpoint_id'] == 'cp'
    assert 'SENDS the application to the employer' in result.input_requests['interaction_0'].params.message


def test_whatever_the_host_returns_decides_the_approval():
    """Documented limitation: this adapter has no second credential, so the host's bit is the approval."""
    interactions = [approval('submit_application')]
    accepted = mcp_server._resume_decisions(interactions, {'interaction_0': ElicitResult(action='accept', content={'approve': True})})
    assert accepted == [{'type': 'approve'}]
    for response in (ElicitResult(action='accept', content={'approve': False}),
                     ElicitResult(action='decline', content={'approve': True}),
                     ElicitResult(action='cancel', content=None)):
        assert mcp_server._resume_decisions(interactions, {'interaction_0': response}) == [{'type': 'reject'}]
    with pytest.raises(RuntimeErrorSafe) as exc:
        mcp_server._resume_decisions(interactions, {})
    assert exc.value.code == 'human_response_required'


def test_a_declined_question_never_becomes_an_answer():
    question = [{'type': 'question', 'interaction_id': 'q', 'question': 'Which days can you work?'}]
    answered = mcp_server._resume_decisions(question, {'interaction_0': ElicitResult(action='accept', content={'answer': 'Tuesdays'})})
    assert answered == [{'type': 'respond', 'message': 'Tuesdays'}]
    for content in ({'answer': '   '}, {'answer': 7}, {}):
        declined = mcp_server._resume_decisions(question, {'interaction_0': ElicitResult(action='accept', content=content)})
        assert declined[0]['type'] == 'respond' and 'declined to answer' in declined[0]['message']


@pytest.mark.parametrize('bad', [
    {'version': 2}, {'person': 'someone-else'}, {'operation': 'start'}, {'thread_id': 7}, {'interactions': {}}])
def test_request_state_is_bound_to_this_person_thread_and_operation(bad):
    good = {'version': 1, 'person': 'owner', 'operation': 'continue', 'thread_id': 't1', 'interactions': []}
    ctx = types.SimpleNamespace(request_state=json.dumps(good | bad), input_responses=None)
    with pytest.raises(RuntimeErrorSafe) as exc:
        mcp_server._state(ctx, person='owner', operation='continue', thread_id='t1')
    assert exc.value.code == 'invalid_chat_interaction_state'


# --- ChatGPT connector stage 1: read-only tools + widgets -------------------------------------------------

import asyncio                                                                  # noqa: E402
from fastmcp import Client                                                      # noqa: E402
from jobwatch import db as dbm, users                                           # noqa: E402
from pipeline.agentic import chatgpt_connector as cc                            # noqa: E402

TOKEN = 'x' * 40


@pytest.fixture
def two_people(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('JOBWATCH_DB', str(tmp_path / 'jobwatch.db'))
    monkeypatch.setattr(users, 'base_dir', lambda: tmp_path)
    for name, company in (('owner', 'Acme Pty'), ('guest', 'Secret Co')):
        with users.use(name):
            conn = dbm.connect(users.db_path())
            conn.execute("INSERT INTO postings(id,source,source_id,url,url_hash,dedupe_key,title,company,first_seen_at,last_seen_at)"
                         " VALUES(1,'s','1','https://example.com/ad','h','d','Data Analyst',?, 't','t')", (company,))
            conn.execute("INSERT INTO applications(posting_id,status,created_at,updated_at) VALUES(1,'drafted','t','2026-10-25T10:00:00')")
            conn.execute("INSERT INTO ad_reviews(posting_id,content_hash,prompt_version,model,verdict,reviewed_at,score,reason,pros_json)"
                         " VALUES(1,'c',1,'m','show','t',4.2,'Matches your SQL work.','[\"SQL\"]')")
            conn.execute("INSERT INTO selection_requests(id,person,request_key,input_hash,manifest_json,state,created_at,updated_at)"
                         " VALUES('s1',?,'k','h',?,'completed','t','2026-10-25T10:00:00')",
                         (name, json.dumps({'request': {'posting_ids': [1]}})))
            conn.commit(); conn.close()
    return tmp_path


def _call(person, name, args, monkeypatch):
    monkeypatch.setattr(mcp_server, '_person_from_request', lambda: person)
    server = mcp_server.create_server(token=TOKEN, person='owner')

    async def go():
        async with Client(server) as c:
            return await c.call_tool(name, args)
    return asyncio.run(go())


def test_read_tools_and_widgets_are_listed_with_the_mcp_apps_fields():
    server = mcp_server.create_server(token=TOKEN, person='owner')

    async def go():
        async with Client(server) as c:
            return await c.list_tools(), await c.list_resources(), [await c.read_resource(u) for u in (cc.LIST_URI, cc.DETAIL_URI)]
    tools, resources, contents = asyncio.run(go())
    by = {t.name: t for t in tools}
    assert {'career_ops_start_chat', 'career_ops_continue_chat', 'jobs_overview', 'job_detail', 'task_status'} <= set(by)
    for name in ('jobs_overview', 'job_detail', 'task_status'):
        assert by[name].annotations.read_only_hint is True and by[name].annotations.destructive_hint is False
    assert by['jobs_overview'].meta['ui']['resourceUri'] == cc.LIST_URI
    assert by['job_detail'].meta['ui']['resourceUri'] == cc.DETAIL_URI
    assert {str(r.uri) for r in resources} >= {cc.LIST_URI, cc.DETAIL_URI}
    for r in resources:
        if str(r.uri) in (cc.LIST_URI, cc.DETAIL_URI):
            assert r.mime_type == 'text/html;profile=mcp-app'
    for c in contents:
        assert c[0].mime_type == "text/html;profile=mcp-app" and "tools/call" in c[0].text and "cdn" not in c[0].text


def test_overview_and_detail_return_structured_content_for_this_person_only(two_people, monkeypatch):
    res = _call('owner', 'jobs_overview', {}, monkeypatch)
    sc = res.structured_content
    assert sc['view'] == 'list' and sc['counts']['needs_you'] == 1
    assert sc['jobs'][0]['employer'] == 'Acme Pty' and sc['jobs'][0]['state'] == 'draft ready'
    assert '1 need you' in res.content[0].text
    d = _call('owner', 'job_detail', {'posting_id': 1}, monkeypatch).structured_content
    assert d['employer'] == 'Acme Pty' and d['score'] == 4.2 and d['why_it_fits'] == 'Matches your SQL work.'
    assert d['state'] == 'draft ready' and d['ad_url'] == 'https://example.com/ad' and d['documents_ready'] is False
    assert _call('owner', 'task_status', {'posting_id': 1}, monkeypatch).structured_content['state'] == 'draft ready'
    # another person's token reads their own database, never the owner's
    other = _call('guest', 'job_detail', {'posting_id': 1}, monkeypatch).structured_content
    assert other['employer'] == 'Secret Co'
    assert 'Acme' not in json.dumps(_call('guest', 'jobs_overview', {}, monkeypatch).structured_content)
    assert _call('owner', 'job_detail', {'posting_id': 99}, monkeypatch).structured_content['found'] is False


def test_unauthenticated_request_reads_nothing(two_people, monkeypatch):
    def deny():
        raise RuntimeErrorSafe('mcp_auth_required')
    monkeypatch.setattr(mcp_server, '_person_from_request', deny)
    server = mcp_server.create_server(token=TOKEN, person='owner')

    async def go():
        async with Client(server) as c:
            await c.call_tool('jobs_overview', {})
    with pytest.raises(Exception):
        asyncio.run(go())


def test_ad_link_must_be_http():
    assert cc._http_url('javascript:alert(1)') is None and cc._http_url('https://a.example/x') == 'https://a.example/x'
