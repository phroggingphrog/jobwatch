import hashlib

import pytest
from fastapi.testclient import TestClient

from jobwatch import db, users
from pipeline import store
from pipeline.agentic.api import Principal, create_api
from pipeline.agentic.discovery import RelevanceJudgment, _store_judgment
from jobwatch.occupations.plan import search_plan, save_plan
from jobwatch.candidate.policy import build_policy

A, B, NO_READ = 'a'*40, 'b'*40, 'c'*40
PREFIX = '/api/agent/discovery'


@pytest.fixture
def api():
    credentials = {A:Principal('fixture-a',frozenset({'read','run'})), B:Principal('fixture-b'),
                   NO_READ:Principal('fixture-a',frozenset({'run'}))}
    with TestClient(create_api(credentials=credentials,config={'pipeline':{'execution_mode':'off'}})) as client:
        yield client


def h(token=A): return {'Authorization':f'Bearer {token}'}


def test_uncached_discovery_is_read_only_and_never_computes(api, monkeypatch):
    from pipeline.agentic import discovery
    def boom(*a,**k): raise AssertionError('Read endpoint must not call a model')
    monkeypatch.setattr(discovery,'field_hypotheses',boom)
    result = api.get(PREFIX+'/fields',headers=h())
    assert result.status_code == 200 and result.json()['status'] == 'not_computed'
    assert 'not qualification proof' in result.json()['note']
    assert api.get(PREFIX+'/plan',headers=h()).json()['flags']['relevance'] == 'shadow'
    assert api.post(PREFIX+'/fields',headers=h()).status_code == 405
    assert api.get(PREFIX+'/fields',headers=h(NO_READ)).status_code == 403
    assert api.get(PREFIX+'/fields').status_code == 401
    assert api.get(PREFIX+'/postings/1/relevance',headers=h()).status_code == 404


def test_plan_and_relevance_are_per_person(api):
    from types import SimpleNamespace
    with users.use('fixture-a'):
        policy = build_policy({'version':1,'facts':[]})
        save_plan('fixture-a',search_plan(policy,[SimpleNamespace(title='Accountant',id='anzsco2022:221111')]))
        conn = db.connect(users.db_path())
        conn.execute("INSERT INTO postings(id,source,source_id,url,url_hash,dedupe_key,title,first_seen_at,last_seen_at) VALUES(1,'seek','one','https://example.invalid/one','one','one','Accountant','now','now')")
        _store_judgment(conn, RelevanceJudgment(posting_id=1,relevant='uncertain',quotes=(),similarity=.2,
            matched_hypotheses=(),reason='Unknown duties',ad_hash='a',plan_hash='p'), 'shadow')
        conn.commit(); conn.close()
    assert api.get(PREFIX+'/plan',headers=h()).json()['plan']['queries']['seek'] == ['accountant']
    assert api.get(PREFIX+'/plan',headers=h(B)).json()['plan'] is None
    result = api.get(PREFIX+'/postings/1/relevance',headers=h())
    assert result.status_code == 200 and result.json()['judgment']['relevant'] == 'uncertain'
    assert result.json()['mode'] == 'shadow'
    assert api.get(PREFIX+'/postings/1/relevance',headers=h(B)).status_code == 404


def test_capabilities_advertise_discovery(api):
    out = api.get('/api/agent/capabilities',headers=h())
    assert out.status_code == 200 and out.json()['discovery']['read_only'] is False
    assert out.json()['discovery']['operations'] == ['status', 'start', 'retry']
