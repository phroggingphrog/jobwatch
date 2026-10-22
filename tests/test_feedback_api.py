"""Authenticated human-only feedback, rules and selected preparation endpoints."""
import pytest
from fastapi.testclient import TestClient
from tests.baseline_support import frozen, world
from jobwatch import users
from pipeline.agentic.api import create_api, Principal
from pipeline.agentic import shortlist

AGENT,HUMAN,OTHER='a'*40,'h'*40,'o'*40


def headers(token=HUMAN,key='one'):
    return {'Authorization':'Bearer '+token,'Idempotency-Key':key}


@pytest.fixture
def client(frozen):
    credentials={AGENT:Principal(users.current(),frozenset({'read','run'})),
        HUMAN:Principal(users.current(),frozenset({'read','interact','approve'})),
        OTHER:Principal('other-person',frozenset({'read','interact','approve'}))}
    shortlist.build_shortlist(frozen.conn,frozen.config)
    with TestClient(create_api(credentials=credentials,config=frozen.config,
                             llm_factory=lambda person:pytest.fail('unpaid operation called a model'))) as api:
        yield api


def test_reject_restore_history_scopes_and_immediate_shortlist(client,frozen):
    entry=shortlist.load_entry(frozen.conn,42,config=frozen.config)
    body=dict(expected_entry_id=entry.entry_id,reason_code='not_this_employer',reason_text='My exact reason.')
    path='/api/agent/shortlist/42/feedback'
    assert client.post(path,json=body,headers=headers(AGENT)).status_code==403
    assert client.post(path,json={**body,'actor':'person'},headers=headers()).status_code==422
    result=client.post(path,json=body,headers=headers())
    assert result.status_code==200,result.text
    assert 42 not in {e['posting_id'] for e in result.json()['shortlist']['entries']}
    assert client.post(path,json=body,headers=headers()).json()['event']==result.json()['event']
    other=client.get('/api/agent/feedback',headers=headers(OTHER))
    assert other.status_code==200,other.text
    assert other.json()['events']==[]
    restore=client.post('/api/agent/shortlist/42/restore',json={'expected_rejection_id':result.json()['event']['id']},
                        headers=headers(key='restore'))
    assert restore.status_code==200,restore.text
    assert 42 in {e['posting_id'] for e in restore.json()['shortlist']['entries']}
    events=client.get('/api/agent/feedback',headers=headers()).json()['events']
    assert [e['kind'] for e in events]==['restore','reject']


def test_rule_confirmation_stales_evaluations_without_model_calls(client,frozen):
    result=client.post('/api/agent/profile/rules',json={'kind':'employer','value':'Synthetic Alpha'},headers=headers())
    assert result.status_code==201,result.text
    draft=result.json()
    path='/api/agent/profile/rules/'+draft['id']+'/confirm'
    assert client.post(path,json={'rule_digest':draft['digest']},headers=headers(AGENT)).status_code==403
    assert client.post(path,json={'rule_digest':draft['digest']},headers=headers(OTHER)).status_code==404
    result=client.post(path,json={'rule_digest':draft['digest']},headers=headers())
    assert result.status_code==200,result.text
    assert result.json()['shortlist']['entries']==[]
    assert result.json()['assessments']=='stale_until_reprocessed'
    assert client.get('/api/agent/profile/rules',headers=headers()).json()['rules']


def test_native_selection_persists_pending_identity_retry_and_cancellation(frozen):
    entries=shortlist.build_shortlist(frozen.conn,frozen.config)
    entry=next(e for e in entries if e.posting_id==42)
    body=dict(posting_ids=[42],expected_entry_ids={'42':entry.entry_id},expected_run_keys={'42':entry.run_key})
    credentials={AGENT:Principal(users.current(),frozenset({'read','run'})),
        HUMAN:Principal(users.current(),frozenset({'read','approve'})),OTHER:Principal('other-person',frozenset({'read'}))}
    # Exercise durable HTTP acceptance before starting the worker; recovery and
    # actual worker/PDF retrieval have separate integration coverage.
    api=TestClient(create_api(credentials=credentials,config=frozen.config,
        llm_factory=lambda person:pytest.fail('selection acceptance called a model')))
    try:
        path='/api/agent/selections'
        assert api.post(path,json=body,headers=headers(AGENT)).status_code==403
        response=api.post(path,json=body,headers=headers())
        assert response.status_code==202,response.text
        selected=response.json()
        assert selected['state']=='pending_dispatch' and selected['run_id'] is None
        assert api.post(path,json=body,headers=headers()).json()['id']==selected['id']
        assert api.post(path,json={**body,'posting_ids':[43]},headers=headers()).status_code==409
        path+='/'+selected['id']
        assert api.get(path,headers=headers(OTHER)).status_code==404
        assert api.post(path+'/cancel',headers=headers()).json()['state']=='cancelled'
        assert api.post(path+'/cancel',headers=headers()).json()['state']=='cancelled'
    finally:
        api.close()


def test_current_prompt_get_reports_stale_without_writing_or_offering_old_profile_questions(client,frozen,monkeypatch):
    shown=client.post('/api/agent/prompts/next',headers=headers()).json()['prompt']
    assert shown is not None
    from jobwatch.candidate import intake
    approved=intake.current_version(users.current())
    monkeypatch.setattr(intake,'current_version',lambda person:{**approved,'confirmed_at':'2099-01-01'})
    before=frozen.conn.total_changes
    response=client.get('/api/agent/prompts/next',headers=headers())
    assert response.status_code==200,response.text
    assert response.json()=={'prompt':None,'reason':'stale'}
    assert frozen.conn.total_changes==before
