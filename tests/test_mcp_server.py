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


def test_current_canonical_assessment_is_projected_without_changing_application_state(two_people, monkeypatch):
    from ranking_support import make_evaluation

    evaluation = make_evaluation([], posting_id=1, score=4.8)
    current_key = evaluation.run_key.value
    latest = {'run_key': current_key, 'reason': 'hard_gate', 'status': 'archived',
              'evaluation': evaluation.model_dump(mode='json')}
    monkeypatch.setattr(cc, 'latest_result', lambda conn, posting_id, **kw:
                        latest if users.current() == 'owner' else None)
    monkeypatch.setattr(cc.service, 'snapshot_inventory', lambda conn, config, *, posting_ids, limit:
                        [{'posting_id': pid, 'run_key': current_key} for pid in posting_ids])

    result = _call('owner', 'job_detail', {'posting_id': 1}, monkeypatch)
    detail = result.structured_content
    assert detail['assessment_state'] == 'current'
    assert detail['assessment_reason'] == 'hard_gate'
    assert detail['assessment_summary'] == 'Synthetic report.'
    assert detail['score'] == 4.8 and detail['why_it_fits'] == 'Synthetic report.'
    assert detail['state'] == 'draft ready' and detail['can_submit'] is False
    assert 'Assessment current (hard_gate)' in result.content[0].text

    overview = _call('owner', 'jobs_overview', {}, monkeypatch).structured_content['jobs'][0]
    assert overview['assessment_state'] == 'current' and overview['assessment_reason'] == 'hard_gate'
    assert overview['score'] == 4.8

    guest = _call('guest', 'job_detail', {'posting_id': 1}, monkeypatch).structured_content
    assert guest['assessment_state'] == 'not_assessed' and guest['score'] == 4.2


def test_stale_or_invalid_canonical_assessment_does_not_fall_back_to_legacy_score(two_people, monkeypatch):
    from ranking_support import make_evaluation

    evaluation = make_evaluation([], posting_id=1, score=4.8)
    stale = {'run_key': evaluation.run_key.value, 'reason': 'hard_gate', 'status': 'archived',
             'evaluation': evaluation.model_dump(mode='json')}
    monkeypatch.setattr(cc, 'latest_result', lambda conn, posting_id, **kw: stale)
    monkeypatch.setattr(cc.service, 'snapshot_inventory', lambda conn, config, *, posting_ids, limit:
                        [{'posting_id': pid, 'run_key': 'b' * 64} for pid in posting_ids])

    detail = _call('owner', 'job_detail', {'posting_id': 1}, monkeypatch).structured_content
    assert detail['assessment_state'] == 'stale'
    assert detail['assessment_reason'] is None and detail['assessment_summary'] is None
    assert detail['score'] is None and detail['why_it_fits'] is None
    assert detail['state'] == 'draft ready' and detail['can_submit'] is False

    stale['run_key'] = 'b' * 64
    stale['evaluation'] = {'not': 'an evaluation'}
    detail = _call('owner', 'job_detail', {'posting_id': 1}, monkeypatch).structured_content
    assert detail['assessment_state'] == 'incomplete'
    assert detail['score'] is None and detail['why_it_fits'] is None


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


# --- ChatGPT connector stages 2 and 3: hand-off, widget approvals, widget-only Submit ----------------------

PREPARED = {'status': 'ready_for_owner', 'run_id': 'r1', 'package_hash': 'p', 'session_id': 's', 'page_url_sha256': 'u',
            'owner_revision': 1, 'attached_documents': ['cv.pdf'], 'final_control': {'selector': 'b'}, 'form_state': 'f'}


def _interrupt(op='prepare_application', digest='d1'):
    return {'status': 'interrupted', 'checkpoint_id': 'cp1', 'interactions': [{
        'type': 'approval', 'operation': op, 'posting_id': 1,
        'binding': {'digest': digest, 'operation': op, 'arguments': {'posting_id': 1}}}]}


@pytest.fixture(autouse=True)
def _clear_pending():
    cc._PENDING.clear()
    yield
    cc._PENDING.clear()


def test_prepare_hands_off_and_raises_a_widget_approval_with_the_binding_only_in_meta(two_people, monkeypatch):
    calls = []
    monkeypatch.setattr(cc, 'dispatch', lambda **kw: calls.append(kw) or _interrupt())
    res = _call('owner', 'prepare_application', {'posting_id': 1, 'instructions': 'short letter'}, monkeypatch)
    sc = res.structured_content
    assert sc['status'] == 'awaiting_approval' and sc['operation'] == 'prepare_application'
    assert 'short letter' in calls[0]['message'] and calls[0]['person'] == 'owner'
    assert 'd1' not in json.dumps(sc) and 'd1' not in res.content[0].text      # the model never sees the binding
    assert res.meta['binding'] == 'd1'


def test_decide_needs_the_binding_the_person_and_is_single_use(two_people, monkeypatch):
    seen = []
    def fake(**kw):
        seen.append(kw)
        return _interrupt() if 'message' in kw else {'status': 'complete', 'answer': 'Draft saved.', 'tools': []}
    monkeypatch.setattr(cc, 'dispatch', fake)
    sc = _call('owner', 'prepare_application', {'posting_id': 1}, monkeypatch).structured_content
    iid = sc['interaction_id']
    with pytest.raises(Exception):
        _call('owner', 'decide', {'interaction_id': iid, 'decision': 'approve', 'binding': 'wrong'}, monkeypatch)
    with pytest.raises(Exception):                                  # another person cannot answer it
        _call('guest', 'decide', {'interaction_id': iid, 'decision': 'approve', 'binding': 'd1'}, monkeypatch)
    assert len(seen) == 1
    done = _call('owner', 'decide', {'interaction_id': iid, 'decision': 'approve', 'binding': 'd1'}, monkeypatch)
    assert done.structured_content['answer'] == 'Draft saved.' and seen[1]['decisions'] == [{'type': 'approve'}]
    assert seen[1]['expected_checkpoint'] == 'cp1' and seen[1]['human_decision'] is True
    with pytest.raises(Exception):
        _call('owner', 'decide', {'interaction_id': iid, 'decision': 'approve', 'binding': 'd1'}, monkeypatch)


def test_a_submit_approval_from_the_agent_is_never_put_to_the_widget(two_people, monkeypatch):
    seen = []
    def fake(**kw):
        seen.append(kw)
        return _interrupt('submit_application') if 'message' in kw else {'status': 'complete', 'answer': 'No.', 'tools': []}
    monkeypatch.setattr(cc, 'dispatch', fake)
    sc = _call('owner', 'revise_application', {'posting_id': 1, 'changes': 'shorter'}, monkeypatch).structured_content
    assert sc['status'] == 'complete' and sc['declined'] == ['submit_application']
    assert seen[1]['decisions'] == [{'type': 'reject'}] and not cc._PENDING


def test_tool_annotations_and_widget_only_visibility():
    server = mcp_server.create_server(token=TOKEN, person='owner')
    async def go():
        async with Client(server) as c:
            return {t.name: t for t in await c.list_tools()}
    by = asyncio.run(go())
    assert by['submit_reviewed'].annotations.destructive_hint is True
    assert by['submit_reviewed'].meta['ui']['visibility'] == ['app'] and by['decide'].meta['ui']['visibility'] == ['app']
    for name in ('prepare_application', 'revise_application'):
        assert by[name].annotations.read_only_hint is False and by[name].annotations.destructive_hint is False


@pytest.fixture
def reviewed(two_people, monkeypatch):
    from jobwatch.apply import prepare
    monkeypatch.setattr(prepare, 'latest_preparation', lambda root, app_id: dict(PREPARED))
    from jobwatch.apply import submit_confirm
    return submit_confirm.digest(PREPARED)


def _requests(person):
    with users.use(person):
        conn = dbm.connect(users.db_path())
        rows = conn.execute('SELECT posting_id, digest FROM submit_requests').fetchall() \
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='submit_requests'").fetchone() else []
        conn.close()
    return rows


def test_submit_requires_the_digest_of_the_reviewed_form(reviewed, monkeypatch):
    d = _call('owner', 'job_detail', {'posting_id': 1}, monkeypatch)
    assert d.structured_content['can_submit'] is True
    assert d.meta['submit_digest'] == reviewed and reviewed not in json.dumps(d.structured_content) + d.content[0].text
    # a model-style call with no digest, an empty one, or a wrong one refuses and queues nothing
    for args in ({'posting_id': 1}, {'posting_id': 1, 'confirm_digest': ''}, {'posting_id': 1, 'confirm_digest': 'a' * 64}):
        with pytest.raises(Exception):
            _call('owner', 'submit_reviewed', args, monkeypatch)
    assert _requests('owner') == []
    ok = _call('owner', 'submit_reviewed', {'posting_id': 1, 'confirm_digest': reviewed}, monkeypatch)
    assert ok.structured_content['status'] == 'queued'
    with pytest.raises(Exception):                                  # a second click never queues a second press
        _call('owner', 'submit_reviewed', {'posting_id': 1, 'confirm_digest': reviewed}, monkeypatch)
    assert len(_requests('owner')) == 1


def test_submit_is_per_person_and_needs_a_reviewed_fill(two_people, monkeypatch):
    d = _call('owner', 'job_detail', {'posting_id': 1}, monkeypatch)
    assert d.structured_content['can_submit'] is False and 'submit_digest' not in (d.meta or {})
    with pytest.raises(Exception):
        _call('owner', 'submit_reviewed', {'posting_id': 1, 'confirm_digest': 'a' * 64}, monkeypatch)


def test_a_digest_for_one_person_does_not_submit_for_another(reviewed, monkeypatch):
    from jobwatch.apply import prepare
    monkeypatch.setattr(prepare, 'latest_preparation',
                        lambda root, app_id: dict(PREPARED) if 'owner' in str(root) or str(root).endswith('owner') else None)
    with users.use('guest'):
        guest_dir = str(users.user_dir())
    if 'owner' in guest_dir:
        pytest.skip('layout does not separate people by name')
    with pytest.raises(Exception):
        _call('guest', 'submit_reviewed', {'posting_id': 1, 'confirm_digest': reviewed}, monkeypatch)
    assert _requests('guest') == []


# --- ChatGPT connector stage 4: optional OAuth 2.1 (code + PKCE + dynamic registration) --------------------

PASS = 'correct horse battery'


def _oauth_server(monkeypatch):
    monkeypatch.setenv('JOBWATCH_MCP_OAUTH', '1')
    monkeypatch.setenv('JOBWATCH_MCP_PUBLIC_URL', 'http://127.0.0.1:8914')
    monkeypatch.setenv('JOBWATCH_MCP_OAUTH_PASSPHRASE', PASS)
    return mcp_server.create_server(token=TOKEN, person='owner')


def test_oauth_is_off_by_default_and_needs_its_config(monkeypatch):
    monkeypatch.delenv('JOBWATCH_MCP_OAUTH', raising=False)
    paths = {getattr(r, 'path', '') for r in mcp_server.create_server(token=TOKEN, person='owner').http_app().routes}
    assert '/register' not in paths and '/oauth/consent' not in paths
    monkeypatch.setenv('JOBWATCH_MCP_OAUTH', '1')
    monkeypatch.delenv('JOBWATCH_MCP_PUBLIC_URL', raising=False)
    with pytest.raises(RuntimeErrorSafe) as exc:
        mcp_server.create_server(token=TOKEN, person='owner')
    assert exc.value.code == 'mcp_oauth_configuration_required'


def test_oauth_flow_maps_the_user_to_the_configured_person(monkeypatch):
    import base64, hashlib
    from urllib.parse import parse_qs, urlparse
    from starlette.testclient import TestClient
    server = _oauth_server(monkeypatch)
    http = TestClient(server.http_app(), base_url='http://127.0.0.1:8914', follow_redirects=False)
    assert 'registration_endpoint' in http.get('/.well-known/oauth-authorization-server').json()
    assert http.get('/.well-known/oauth-protected-resource/mcp').status_code == 200
    cb = 'https://chatgpt.example/callback'
    reg = http.post('/register', json={'redirect_uris': [cb], 'client_name': 'Test ChatGPT', 'token_endpoint_auth_method': 'none',
                                       'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code']})
    assert reg.status_code == 201, reg.text
    cid = reg.json()['client_id']
    verifier = __import__('secrets').token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    auth = http.get('/authorize', params={'response_type': 'code', 'client_id': cid, 'redirect_uri': cb, 'state': 's1',
                                          'code_challenge': challenge, 'code_challenge_method': 'S256', 'scope': 'jobwatch'})
    assert auth.status_code == 302 and '/oauth/consent' in auth.headers['location']
    txn = parse_qs(urlparse(auth.headers['location']).query)['txn'][0]
    assert 'Allow access' in http.get('/oauth/consent', params={'txn': txn}).text
    assert 'wrong' in http.post('/oauth/consent', data={'txn': txn, 'passphrase': 'nope'}).text
    done = http.post('/oauth/consent', data={'txn': txn, 'passphrase': PASS})
    q = parse_qs(urlparse(done.headers['location']).query)
    assert done.headers['location'].startswith(cb) and q['state'] == ['s1']
    bad = http.post('/token', data={'grant_type': 'authorization_code', 'code': q['code'][0], 'client_id': cid,
                                    'redirect_uri': cb, 'code_verifier': 'x' * 50})
    assert bad.status_code in (400, 401) and 'code_verifier' in bad.text                           # PKCE verifier mismatch refuses
    tok = http.post('/token', data={'grant_type': 'authorization_code', 'code': q['code'][0], 'client_id': cid,
                                    'redirect_uri': cb, 'code_verifier': verifier})
    assert tok.status_code == 200, tok.text
    access = tok.json()['access_token']

    async def check():
        got = await server.auth.verify_token(access)
        assert got.claims['sub'] == 'owner' or got.subject == 'owner'
        assert await server.auth.verify_token(TOKEN) is not None       # the bearer token still works
        assert await server.auth.verify_token('nope') is None
    asyncio.run(check())
    again = http.post('/token', data={'grant_type': 'authorization_code', 'code': q['code'][0], 'client_id': cid,
                                      'redirect_uri': cb, 'code_verifier': verifier})
    assert again.status_code in (400, 401)                                    # a code works once
    refreshed = http.post('/token', data={'grant_type': 'refresh_token', 'refresh_token': tok.json()['refresh_token'], 'client_id': cid})
    assert refreshed.status_code == 200
    unauth = http.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'},
                       headers={'Accept': 'application/json, text/event-stream'})
    assert unauth.status_code == 401


def test_consent_denied_and_lockout(monkeypatch):
    from urllib.parse import parse_qs, urlparse
    from starlette.testclient import TestClient
    server = _oauth_server(monkeypatch)
    http = TestClient(server.http_app(), base_url='http://127.0.0.1:8914', follow_redirects=False)
    cb = 'https://chatgpt.example/callback'
    cid = http.post('/register', json={'redirect_uris': [cb], 'token_endpoint_auth_method': 'none'}).json()['client_id']
    def start():
        r = http.get('/authorize', params={'response_type': 'code', 'client_id': cid, 'redirect_uri': cb, 'state': 's',
                                           'code_challenge': 'c' * 43, 'code_challenge_method': 'S256'})
        return parse_qs(urlparse(r.headers['location']).query)['txn'][0]
    denied = http.post('/oauth/consent', data={'txn': start(), 'passphrase': PASS, 'deny': '1'})
    assert 'error=access_denied' in denied.headers['location']
    txn = start()
    for _ in range(5):
        last = http.post('/oauth/consent', data={'txn': txn, 'passphrase': 'bad'})
    assert last.status_code == 429
    assert http.post('/oauth/consent', data={'txn': txn, 'passphrase': PASS}).status_code == 400
