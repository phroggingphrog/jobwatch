"""Native account-bound shortlist views are unpaid and never prepare documents."""
import pytest
from fastapi.testclient import TestClient
from tests.baseline_support import world, frozen
from jobwatch import users
from pipeline.agentic.api import create_api, Principal
from pipeline.agentic import shortlist

A,B,READ='a'*40,'b'*40,'r'*40
PREFIX='/api/agent/shortlist'
def headers(token=A): return {'Authorization':'Bearer '+token}


@pytest.fixture
def client(frozen):
    credentials={A:Principal(users.current(),frozenset({'read','run'})),
        B:Principal('other-fixture',frozenset({'read','run'})),
        READ:Principal(users.current(),frozenset({'read'}))}
    with TestClient(create_api(credentials=credentials,config=frozen.config,
        llm_factory=lambda person:pytest.fail('shortlist called a model'))) as api:
        yield api


def test_scope_validation_and_missing_profile(client):
    assert client.get(PREFIX).status_code==401
    assert client.post(PREFIX+'/refresh',headers=headers(READ)).status_code==403
    for suffix in ('?limit=0','?limit=51','?offset=-1','?label=wrong'):
        assert client.get(PREFIX+suffix,headers=headers()).status_code==422
    result=client.get(PREFIX,headers=headers(B))
    assert result.status_code==200 and result.json()['entries']==[]
    assert client.get(PREFIX+'/42',headers=headers(B)).status_code==404


def test_refresh_views_and_detail_are_current_explained_and_idempotent(client):
    assert client.get(PREFIX,headers=headers()).json()['status']=='not_built'
    first=client.post(PREFIX+'/refresh',headers=headers())
    assert first.status_code==200 and first.json()['rebuilt'] is True
    second=client.post(PREFIX+'/refresh',headers=headers()).json()
    assert second['rebuilt'] is False and second['shortlist_id']==first.json()['shortlist_id']
    page=client.get(PREFIX+'?limit=1&offset=1',headers=headers()).json()
    assert page['status']=='ok' and page['total']==3 and len(page['entries'])==1
    entry=page['entries'][0]
    detail=client.get(PREFIX+'/'+str(entry['posting_id']),headers=headers()).json()
    assert detail['entry_id']==entry['entry_id'] and detail['requirements'] and detail['evidence'][0]['citations']
    assert detail['holistic_score'] and detail['ordering']=='provisional'
    assert client.get(PREFIX+'/999999',headers=headers()).status_code==404
    assert client.get('/api/agent/capabilities',headers=headers()).json()['shortlist']['labels']==['stronger_match','stretch','needs_clarification']


def test_change_inside_throttle_window_rebuilds_and_never_returns_stale(client,frozen):
    first=client.post(PREFIX+'/refresh',headers=headers()).json()
    frozen.conn.execute("UPDATE postings SET salary_text='$99/hour AUD' WHERE id=42");frozen.conn.commit()
    stale=client.get(PREFIX,headers=headers()).json()
    assert stale['status']=='stale' and stale['entries']==[]
    assert client.get(PREFIX+'/42',headers=headers()).status_code==404
    second=client.post(PREFIX+'/refresh',headers=headers()).json()
    assert second['rebuilt'] is True and second['shortlist_id']!=first['shortlist_id']


def test_no_database_returns_not_built_without_creating_one():
    with TestClient(create_api(credentials={A:Principal('no-db-fixture')},config={'pipeline':{'execution_mode':'off'}})) as api:
        result=api.get(PREFIX,headers=headers())
        assert result.status_code==200 and result.json()['status']=='not_built'
        with users.use('no-db-fixture'):
            assert not users.db_path().exists()
