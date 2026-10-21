"""Native profile intake API: synthetic documents, tmp_path people, fake LLM transport."""
import json

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

    def chat(self, *a, **kw):
        return self.llm.chat(*a, **kw)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(model_choice, 'SERVER_URL', 'http://127.0.0.1:20128/v1')
    monkeypatch.setattr(model_choice, 'get_model', lambda role: 'claude/sonnet')
    for person in ('fixture-a', 'fixture-b'):
        users.create_user_dirs(person)
    fake = FakeLLM()
    fake.next = {'facts': [{'section': 'experience', 'value': 'Accounts Assistant, Ledger Co', 'basis': 'evidence',
                            'upload': 1, 'sources': [{'line': 5, 'quote': 'Ledger Co, Accounts Assistant, 2021 - 2023'}]}],
                 'questions': [{'section': 'work_rights', 'text': 'What are your work rights?', 'why': 'Matching.'}]}
    credentials = {RUN: Principal('fixture-a'), APPROVE: Principal('fixture-a', frozenset({'read', 'interact', 'approve'})),
                   OTHER: Principal('fixture-b', frozenset({'read', 'run', 'interact', 'approve'}))}
    app = create_api(credentials=credentials, config={'agentic': {'enabled': False}}, llm_factory=lambda p: fake)
    with TestClient(app) as client:
        yield client


def h(token=RUN):
    return {'Authorization': 'Bearer ' + token}


def upload(client, data=CV, name='cv.txt', kind='cv', token=RUN):
    return client.post(P + '/uploads', files={'file': (name, data)}, data={'kind': kind}, headers=h(token))


def proposal(client):
    up = upload(client)
    assert up.status_code == 201, up.text
    res = client.post(P + '/proposals', json={'upload_ids': [up.json()['upload_id']], 'base_version': None}, headers=h())
    assert res.status_code == 201, res.text
    return res.json()


def test_full_profile_flow_over_http(env):
    c = env
    prop = proposal(c)
    pid = prop['id']
    got = c.get(f'{P}/proposals/{pid}', headers=h()).json()
    assert got['facts'][0]['basis'] == 'evidence' and got['facts'][0]['sources'][0]['line'] == 5
    r = c.patch(f'{P}/proposals/{pid}', json={'expected_revision': 1, 'edits': [
        {'op': 'add', 'section': 'location', 'value': 'Perth'}]}, headers=h(APPROVE))
    assert r.status_code == 200 and r.json()['revision'] == 2
    qid = r.json()['questions'][0]['id']
    r = c.post(f'{P}/proposals/{pid}/answers', json={'expected_revision': 2, 'question_id': qid, 'text': 'Citizen'}, headers=h(APPROVE))
    assert r.status_code == 200 and r.json()['revision'] == 3 and qid not in [q['id'] for q in r.json()['questions']]
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
    pad = {'op': 'add', 'section': 'skill', 'value': 'x' * 70000}
    r = c.patch(f'{P}/proposals/{pid}', json={'expected_revision': 1, 'edits': [pad]}, headers=h(APPROVE))
    assert r.status_code == 413 and r.json() == {'error': 'request_too_large'}
    ok = c.patch(f'{P}/proposals/{pid}', json={'expected_revision': 1, 'edits': [{**pad, 'value': 'Bookkeeping'}]}, headers=h(APPROVE))
    assert ok.status_code == 200 and ok.json()['revision'] == 2


def test_one_proposal_in_flight_per_person(tmp_path, monkeypatch):
    import threading
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(model_choice, 'SERVER_URL', 'http://127.0.0.1:20128/v1')
    monkeypatch.setattr(model_choice, 'get_model', lambda role: 'claude/sonnet')
    for person in ('fixture-a', 'fixture-b'):
        users.create_user_dirs(person)
    started, release, seen = threading.Event(), threading.Event(), []

    class Blocking:
        def chat(self, *a, **kw):
            seen.append(kw.get('deadline'))
            started.set()
            assert release.wait(10)
            return FakeLLM().chat(*a, **kw)
    credentials = {RUN: Principal('fixture-a'), OTHER: Principal('fixture-b')}
    app = create_api(credentials=credentials, config={'agentic': {'enabled': False}}, llm_factory=lambda p: Blocking())
    with TestClient(app) as c:
        ids = {t: upload(c, token=t).json()['upload_id'] for t in (RUN, OTHER)}
        first = {}
        def go():
            first['r'] = c.post(P + '/proposals', json={'upload_ids': [ids[RUN]], 'base_version': None}, headers=h())
        t = threading.Thread(target=go)
        t.start()
        assert started.wait(10)
        r = c.post(P + '/proposals', json={'upload_ids': [ids[RUN]], 'base_version': None}, headers=h())
        assert r.status_code == 409 and r.json() == {'error': 'proposal_in_progress'}
        release.set()
        t.join(10)
        assert first['r'].status_code == 201 and seen[0] is not None           # deadline passed to the LLM
        again = c.post(P + '/proposals', json={'upload_ids': [ids[RUN]], 'base_version': None}, headers=h())
        assert again.status_code == 201                                       # slot released in finally
