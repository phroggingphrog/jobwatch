"""Native profile intake API: synthetic documents, tmp_path people, fake LLM transport."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from jobwatch import model_choice, users
from jobwatch.candidate import intake
from jobwatch.llm import LLM
from pipeline.agentic import profile_api
from pipeline.agentic.api import Principal, create_api

CV = b"Alex Example\nAccounts Assistant\n\nExperience\nLedger Co, Accounts Assistant, 2021 - 2023\n"
RUN, APPROVE, OTHER = 'fixture-run-' + 'a' * 40, 'fixture-approval-' + 'b' * 40, 'fixture-other-' + 'c' * 40
P = '/api/agent/profile'


class FakeLLM:
    def __init__(self):
        self.next = {'facts': [], 'questions': []}
        def transport(url, headers, body, timeout):
            return 200, {'choices': [{'message': {'content': json.dumps(self.next)}}], 'usage': {}}
        self.llm = LLM(transport=transport, keys=['synthetic'], base_url=model_choice.SERVER_URL)
        self.base_url = self.llm.base_url
        self.calls = []

    def chat(self, *a, **kw):
        self.calls.append(a)
        return self.llm.chat(*a, **kw)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(model_choice, 'SERVER_URL', 'http://127.0.0.1:20128/v1')
    monkeypatch.setattr(model_choice, 'get_model', lambda role: 'claude/sonnet')
    for person in ('fixture-a', 'fixture-b'):
        users.create_user_dirs(person)
        model_choice.set_models({'reader': 'claude/sonnet'}, person)      # the approved paid route for candidate text
    fake = FakeLLM()
    fake.next = {'facts': [{'section': 'experience', 'value': 'Accounts Assistant, Ledger Co', 'basis': 'evidence',
                            'upload': 1, 'sources': [{'line': 5, 'quote': 'Ledger Co, Accounts Assistant, 2021 - 2023'}]}],
                 'questions': [{'section': 'work_rights', 'text': 'What are your work rights?', 'why': 'Matching.'}]}
    credentials = {RUN: Principal('fixture-a'), APPROVE: Principal('fixture-a', frozenset({'read', 'interact', 'approve'})),
                   OTHER: Principal('fixture-b', frozenset({'read', 'run', 'interact', 'approve'}))}
    app = create_api(credentials=credentials, config={'agentic': {'enabled': False}}, llm_factory=lambda p: fake)
    with TestClient(app) as client:
        client.fake = fake
        yield client


def h(token=RUN):
    return {'Authorization': 'Bearer ' + token}


def upload(client, data=CV, name='cv.txt', kind='cv', token=RUN):
    return client.post(P + '/uploads', files={'file': (name, data)}, data={'kind': kind}, headers=h(token))


def proposal(client):
    up = upload(client)
    assert up.status_code == 201, up.text
    res = client.post(P + '/proposals', json={'upload_ids': [up.json()['upload_id']], 'base_version': None}, headers=h())
    assert res.status_code == 202 and res.json()['status'] == 'parsing', res.text
    return settled(client, res.json()['id'])


def settled(client, pid, token=RUN, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        got = client.get(f'{P}/proposals/{pid}', headers=h(token)).json()
        if got['status'] != 'parsing':
            return got
        time.sleep(0.01)
    raise AssertionError('parse did not finish')


def test_full_profile_flow_over_http(env):
    c = env
    prop = proposal(c)
    pid = prop['id']
    got = c.get(f'{P}/proposals/{pid}', headers=h()).json()
    exp = next(f for f in got['facts'] if f['section'] == 'experience')
    assert exp['basis'] == 'evidence' and exp['sources'][0]['line'] == 5 and got['status'] == 'draft' and got['parse_error'] == ''
    rev = got['revision']
    r = c.patch(f'{P}/proposals/{pid}', json={'expected_revision': rev, 'edits': [
        {'op': 'add', 'section': 'location', 'value': 'Perth'}]}, headers=h(APPROVE))
    assert r.status_code == 200 and r.json()['revision'] == rev + 1
    qid = next(q['id'] for q in r.json()['questions'] if q['section'] == 'work_rights')
    r = c.post(f'{P}/proposals/{pid}/answers', json={'expected_revision': rev + 1, 'question_id': qid, 'text': 'Citizen'}, headers=h(APPROVE))
    assert r.status_code == 200 and r.json()['revision'] == rev + 2 and qid not in [q['id'] for q in r.json()['questions']]
    conf = c.get(f'{P}/proposals/{pid}/confirmation', headers=h()).json()
    assert conf['does_not_authorise'] and conf['scope']['locations'] == ['Perth']
    assert c.get(P + '/', headers=h()).json()['version'] is None
    r = c.post(f'{P}/proposals/{pid}/confirm', json={k: conf[k] for k in ('proposal_digest', 'scope_digest')}, headers=h(APPROVE))
    assert r.status_code == 201 and r.json() == {'version': 1}
    assert c.get(P + '/', headers=h()).json()['version'] == 1
    assert [v['version'] for v in c.get(P + '/versions', headers=h()).json()['versions']] == [1]
    assert not (users.user_dir('fixture-b') / 'profile-versions').exists()


def test_confirm_needs_approve_scope(env):
    c = env
    pid = proposal(c)['id']
    conf = c.get(f'{P}/proposals/{pid}/confirmation', headers=h()).json()
    body = {k: conf[k] for k in ('proposal_digest', 'scope_digest')}
    assert c.post(f'{P}/proposals/{pid}/confirm', json=body, headers=h(RUN)).status_code == 403
    assert c.post(f'{P}/proposals/{pid}/confirm', json=body).status_code == 401
    assert c.post(f'{P}/proposals/{pid}/confirm', json={**body, 'actor': 'agent'}, headers=h(APPROVE)).status_code == 422
    assert intake.current_version('fixture-a') is None
    stale = c.post(f'{P}/proposals/{pid}/confirm', json={**body, 'proposal_digest': '0' * 64}, headers=h(APPROVE))
    assert stale.status_code == 409 and stale.json() == {'error': 'proposal_changed'}
    bad = c.post(f'{P}/proposals/{pid}/confirm', json={**body, 'scope_digest': '0' * 64}, headers=h(APPROVE))
    assert bad.status_code == 409 and bad.json() == {'error': 'scope_changed'}


def test_other_person_cannot_see_proposal(env):
    c = env
    pid = proposal(c)['id']
    for method, path, body in (('get', '', None), ('get', '/confirmation', None), ('patch', '', {'expected_revision': 1, 'edits': [{'op': 'remove', 'fact_id': 'f1'}]}),
                               ('post', '/answers', {'expected_revision': 1, 'question_id': 'q1', 'text': 'x'}),
                               ('post', '/confirm', {'proposal_digest': 'a', 'scope_digest': 'b'})):
        r = getattr(c, method)(f'{P}/proposals/{pid}{path}', headers=h(OTHER), **({'json': body} if body else {}))
        assert r.status_code == 404 and r.json() == {'error': 'proposal_not_found'}, (method, path)
    r = c.post(P + '/proposals', json={'upload_ids': ['0' * 16], 'base_version': None}, headers=h(OTHER))
    assert r.status_code == 404 and r.json() == {'error': 'upload_not_found'}


def test_upload_size_and_type_limits(env):
    c = env
    r = upload(c, name='cv.exe')
    assert r.status_code == 415 and r.json() == {'error': 'unsupported_type'}
    assert upload(c, kind='resume').status_code == 415
    r = upload(c, data=b' ' * 20)  # no extractable text is kept at upload; propose refuses
    assert r.status_code == 201
    big = upload(c, data=b'x' * (10 * 1024 * 1024 + 1))
    assert big.status_code == 413 and big.json() == {'error': 'too_large'}
    # declared length over the cap is refused before reading; the streamed body is also counted
    r = c.post(P + '/uploads', content=b'x', headers={**h(), 'Content-Length': str(11 * 1024 * 1024), 'Content-Type': 'multipart/form-data; boundary=x'})
    assert r.status_code == 413 and r.json() == {'error': 'too_large'}
    chunked = c.post(P + '/uploads', content=(b'x' * 65536 for _ in range(200)), headers={**h(), 'Content-Type': 'multipart/form-data; boundary=x'})
    assert chunked.status_code == 413 and chunked.json() == {'error': 'too_large'}
    # exactly the cap is accepted; the cap is not raised for other routes
    assert upload(c, data=b'a' * (10 * 1024 * 1024)).status_code == 201
    r = c.post(P + '/proposals', content=b'{"upload_ids": [], "pad": "' + b'x' * 70000 + b'"}', headers={**h(), 'Content-Type': 'application/json'})
    assert r.status_code == 413 and r.json() == {'error': 'request_too_large'}
    assert c.post(P + '/uploads', files={'file': ('cv.txt', CV)}, data={'kind': 'cv'}).status_code == 401
    big_cv = {'files': {'file': ('cv.txt', b'x' * 70000)}, 'data': {'kind': 'cv'}}
    assert c.post(P + '/uploads', headers=h(APPROVE), **big_cv).status_code == 403   # no run scope: refused before buffering
    assert c.post(P + '/uploads', headers=h(), **big_cv).status_code == 201
    assert c.post(P + '/uploads', data={'kind': 'cv'}, headers=h()).status_code == 422


def test_empty_upload_is_refused_at_proposal(env):
    c = env
    up = upload(c, data=b'   \n').json()
    r = c.post(P + '/proposals', json={'upload_ids': [up['upload_id']], 'base_version': None}, headers=h())
    assert r.status_code == 422 and r.json() == {'error': 'no_extractable_text'}


def test_every_intake_code_has_a_mapping():
    assert set(intake.CODES) == set(profile_api.STATUS)
    assert {c: s for c, s in profile_api.STATUS.items() if c in ('proposal_changed', 'scope_changed', 'adopt_first')} == dict.fromkeys(('proposal_changed', 'scope_changed', 'adopt_first'), 409)
    assert profile_api.STATUS['too_large'] == 413 and profile_api.STATUS['unsupported_type'] == 415
    assert profile_api.STATUS['no_extractable_text'] == 422 and profile_api.STATUS['extractor_unavailable'] == 503


def test_capabilities_lists_profile(env):
    caps = env.get('/api/agent/capabilities', headers=h()).json()
    assert caps['profile']['upload_max_bytes'] == 10 * 1024 * 1024


def test_json_cap_applies_to_patch_too(env):
    c = env
    pid = proposal(c)['id']
    rev = c.get(f'{P}/proposals/{pid}', headers=h()).json()['revision']
    pad = {'op': 'add', 'section': 'skill', 'value': 'x' * 70000}
    r = c.patch(f'{P}/proposals/{pid}', json={'expected_revision': rev, 'edits': [pad]}, headers=h(APPROVE))
    assert r.status_code == 413 and r.json() == {'error': 'request_too_large'}
    ok = c.patch(f'{P}/proposals/{pid}', json={'expected_revision': rev, 'edits': [{**pad, 'value': 'Bookkeeping'}]}, headers=h(APPROVE))
    assert ok.status_code == 200 and ok.json()['revision'] == rev + 1


def test_one_proposal_in_flight_per_person(tmp_path, monkeypatch):
    import threading
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(model_choice, 'SERVER_URL', 'http://127.0.0.1:20128/v1')
    monkeypatch.setattr(model_choice, 'get_model', lambda role: 'claude/sonnet')
    for person in ('fixture-a', 'fixture-b'):
        users.create_user_dirs(person)
        model_choice.set_models({'reader': 'claude/sonnet'}, person)
    started, release, seen = threading.Event(), threading.Event(), []

    class Blocking:
        base_url = model_choice.SERVER_URL

        def chat(self, *a, **kw):
            seen.append(kw.get('deadline'))
            started.set()
            assert release.wait(10)
            return FakeLLM().chat(*a, **kw)
    credentials = {RUN: Principal('fixture-a'), OTHER: Principal('fixture-b')}
    app = create_api(credentials=credentials, config={'agentic': {'enabled': False}}, llm_factory=lambda p: Blocking())
    with TestClient(app) as c:
        ids = {t: upload(c, token=t).json()['upload_id'] for t in (RUN, OTHER)}
        first = c.post(P + '/proposals', json={'upload_ids': [ids[RUN]], 'base_version': None}, headers=h())
        assert first.status_code == 202 and first.json()['status'] == 'parsing'      # returns at once; the parse is held open
        assert started.wait(10)
        r = c.post(P + '/proposals', json={'upload_ids': [ids[RUN]], 'base_version': None}, headers=h())
        assert r.status_code == 409 and r.json() == {'error': 'proposal_in_progress'}
        mid = c.get(f"{P}/proposals/{first.json()['id']}", headers=h()).json()
        assert mid['status'] == 'parsing' and {q['section'] for q in mid['questions']} >= {'career_focus', 'location', 'work_rights'}
        release.set()
        assert settled(c, first.json()['id'])['status'] == 'draft' and seen[0] is not None   # deadline passed to the LLM
        deadline = time.monotonic() + 10
        while True:                                                                  # slot released in the worker's finally
            again = c.post(P + '/proposals', json={'upload_ids': [ids[RUN]], 'base_version': None}, headers=h())
            if again.status_code == 202 or time.monotonic() > deadline:
                break
            time.sleep(0.01)
        assert again.status_code == 202
        settled(c, again.json()['id'])


def test_an_adopted_owner_onboards_by_a_proposal_on_the_current_version_over_http(env):
    from jobwatch.apply import paths as apaths
    c = env
    with users.use('fixture-a'):
        apaths.profile_dir().mkdir(parents=True, exist_ok=True)
        (apaths.profile_dir() / 'profile.yaml').write_text('candidate:\n  name: Synthetic\n')
        (apaths.profile_dir() / 'master_resume.md').write_text('# Synthetic\n\nAccounts Assistant, 2021\n')
        intake.adopt_existing('fixture-a', actor='person')
    assert intake.discovery_scope('fixture-a') is None and c.get(P + '/', headers=h()).json()['version'] == 1
    up = upload(c).json()['upload_id']
    res = c.post(P + '/proposals', json={'upload_ids': [up], 'base_version': 1}, headers=h())
    assert res.status_code == 202 and res.json()['base_version'] == 1
    pid = settled(c, res.json()['id'])['id']
    conf = c.get(f'{P}/proposals/{pid}/confirmation', headers=h()).json()
    r = c.post(f'{P}/proposals/{pid}/confirm', json={k: conf[k] for k in ('proposal_digest', 'scope_digest')}, headers=h(APPROVE))
    assert r.status_code == 201 and r.json() == {'version': 2} and intake.discovery_scope('fixture-a') is not None


def test_the_scope_only_routes_are_gone(env):
    for method, path in (('get', '/scope-confirmation'), ('post', '/scope-confirm')):
        assert getattr(env, method)(P + path, headers=h(APPROVE)).status_code in (404, 405)


def test_proposal_returns_202_then_draft(env):
    c = env
    up = upload(c).json()['upload_id']
    res = c.post(P + '/proposals', json={'upload_ids': [up], 'base_version': None}, headers=h())
    assert res.status_code == 202
    first = res.json()
    assert first['status'] == 'parsing' and first['parse_error'] == '' and first['questions']
    done = settled(c, first['id'])
    assert done['status'] == 'draft' and done['revision'] > first['revision']
    stale = c.post(f"{P}/proposals/{first['id']}/answers", headers=h(APPROVE),
                   json={'expected_revision': first['revision'], 'question_id': 'q1', 'text': 'x'})
    assert stale.status_code == 409 and stale.json() == {'error': 'proposal_changed'}      # an old revision re-reads


def test_confirm_while_parsing_is_409_and_uploads_add_documents(tmp_path, monkeypatch):
    import threading
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(model_choice, 'SERVER_URL', 'http://127.0.0.1:20128/v1')
    monkeypatch.setattr(model_choice, 'get_model', lambda role: 'claude/sonnet')
    users.create_user_dirs('fixture-a')
    model_choice.set_models({'reader': 'claude/sonnet'}, 'fixture-a')
    release = threading.Event()

    class Blocking:
        base_url = model_choice.SERVER_URL

        def chat(self, *a, **kw):
            assert release.wait(10)
            return FakeLLM().chat(*a, **kw)
    credentials = {RUN: Principal('fixture-a'), APPROVE: Principal('fixture-a', frozenset({'read', 'interact', 'approve'}))}
    app = create_api(credentials=credentials, config={'agentic': {'enabled': False}}, llm_factory=lambda p: Blocking())
    with TestClient(app) as c:
        try:
            ids = [upload(c).json()['upload_id'], upload(c, data=b'Dear team\nI led the audit\n', name='l.txt', kind='letter').json()['upload_id']]
            first = c.post(P + '/proposals', json={'upload_ids': ids[:1], 'base_version': None}, headers=h()).json()
            r = c.post(f"{P}/proposals/{first['id']}/confirm", json={'proposal_digest': 'x', 'scope_digest': 'y'}, headers=h(APPROVE))
            assert r.status_code == 409 and r.json() == {'error': 'proposal_parsing'}
            r = c.post(f"{P}/proposals/{first['id']}/uploads", json={'upload_ids': ids[1:]}, headers=h())
            assert r.status_code == 409 and r.json() == {'error': 'proposal_parsing'}
            release.set()
            done = settled(c, first['id'])
            deadline = time.monotonic() + 10
            while True:
                r = c.post(f"{P}/proposals/{first['id']}/uploads", json={'upload_ids': ids[1:]}, headers=h())
                if r.status_code != 409 or time.monotonic() > deadline:
                    break
                time.sleep(0.01)
            assert r.status_code == 202 and r.json()['status'] == 'parsing' and r.json()['revision'] == done['revision'] + 1
            assert len(settled(c, first['id'])['uploads']) == 2
            assert c.post(f"{P}/proposals/{first['id']}/uploads", json={'upload_ids': ids[1:]}, headers=h(APPROVE)).status_code == 403
        finally:
            release.set()


def test_parse_over_http_refuses_a_non_paid_reader_model_without_a_model_call(env):
    c = env
    first = proposal(c)
    ids = [upload(c, kind='evidence').json()['upload_id']]
    model_choice.set_models({'reader': 'openrouter/free-model'}, 'fixture-a')
    calls = len(c.fake.calls)
    r = c.post(P + '/proposals', json={'upload_ids': ids, 'base_version': None}, headers=h())
    assert r.status_code == 403 and r.json() == {'error': 'model_not_allowed'}
    r = c.post(f"{P}/proposals/{first['id']}/uploads", json={'upload_ids': ids}, headers=h())
    assert r.status_code == 403 and r.json() == {'error': 'model_not_allowed'}
    assert len(c.fake.calls) == calls                                         # the CV never reached a model
    assert c.get(f"{P}/proposals/{first['id']}", headers=h()).json()['revision'] == first['revision']


def test_parse_over_http_refuses_a_gateway_that_is_not_the_local_one(env):
    c = env
    up = upload(c).json()['upload_id']
    c.fake.base_url = 'https://example.invalid/v1'
    r = c.post(P + '/proposals', json={'upload_ids': [up], 'base_version': None}, headers=h())
    assert r.status_code == 403 and r.json() == {'error': 'gateway_not_allowed'} and not c.fake.calls
