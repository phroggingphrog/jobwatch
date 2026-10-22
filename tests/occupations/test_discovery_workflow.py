"""Real private profile and API wiring, using invented records and a fake Qwen transport."""
import json

from fastapi.testclient import TestClient

from conftest import confirm_discovery, make_config
from jobwatch import users, db
from jobwatch.occupations import loaders
from pipeline.agentic import discovery
from pipeline.agentic.api import create_api, Principal
from tests.occupations.fixtures import toy_reference, approved_llm, hash_transport
from pipeline.agentic.execution import QWEN_EMBEDDING_MODEL


def test_confirm_refresh_and_read_native_fields_and_plan(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(loaders,'load_reference_records',lambda **k:toy_reference())
    calls = []
    with users.use('fixture-a'):
        cfg = make_config(tmp_path=tmp_path,settings={'pipeline':{'execution_mode':'agentic',
            'agentic':{'embedding_model':QWEN_EMBEDDING_MODEL}}})
        confirm_discovery(cfg,'fixture-a')
        conn = db.connect(cfg.db_path)
        out = discovery.refresh('fixture-a',cfg,conn=conn,llm=approved_llm(hash_transport(calls)),seconds=20.)
        assert out['hypotheses'] > 0
        assert conn.execute('SELECT SUM(charged_tokens) FROM discovery_spend').fetchone()[0] > 0
        before = len(calls)
        assert discovery.refresh('fixture-a',cfg,conn=conn,llm=approved_llm(hash_transport(calls))) == out
        assert len(calls) == before
        from jobwatch.models import Posting
        from jobwatch.dedupe import ingest
        from jobwatch import adtext
        from pipeline import store
        store.ensure(conn)
        text = 'Accountant reconciles supplier ledgers and prepares journals. ' * 16
        pid,_ = ingest(conn,Posting(source='synthetic',source_id='1',url='https://example.invalid/1',
            title='Accountant',company='Example Company',location='Sydney NSW',description=text))
        adtext.save_text(conn,pid,text,'synthetic'); store.admit(conn,pid,'h',{}); conn.commit()
        cfg.settings['pipeline']['discovery'] = {'similar_at':.01}
        with discovery.context_for(conn,cfg,llm=approved_llm(hash_transport(calls))) as context:
            assert context is not None
            screen = discovery.screen_step(conn,cfg,context=context)
        assert screen == {'judged':1,'archived':0,'uncertain':0}
        assert store.get(conn,pid)['stage'] == 'ingested'
        assert discovery.latest_judgment(conn,pid).relevant == 'yes'
        before = len(calls)
        conn.close()
    token = 'r'*40
    with TestClient(create_api(credentials={token:Principal('fixture-a')},config=cfg)) as api:
        headers = {'Authorization':f'Bearer {token}'}
        fields = api.get('/api/agent/discovery/fields',headers=headers).json()
        plan = api.get('/api/agent/discovery/plan',headers=headers).json()
        assert fields['status'] == 'ready' and fields['hypotheses']
        assert all(h['is_qualification_proof'] is False for h in fields['hypotheses'])
        assert plan['status'] == 'ready' and plan['plan']['plan_hash'] == out['plan_hash']
        assert len(calls) == before
        relevance = api.get(f'/api/agent/discovery/postings/{pid}/relevance',headers=headers).json()
    from jobwatch import config
    monkeypatch.setattr(config,'load_config',lambda:cfg)
    assert discovery.main(['refresh','--user','fixture-a']) == 0
    cli_refresh = json.loads(capsys.readouterr().out)
    assert cli_refresh == out
    assert discovery.main(['status','--user','fixture-a']) == 0
    status = json.loads(capsys.readouterr().out)
    assert status['counts']['yes'] == 1
    assert discovery.main(['restore','--user','fixture-a']) == 0
    restored = json.loads(capsys.readouterr().out)
    assert restored == {'restored':0}
    print('SYNTHETIC_DISCOVERY_EXAMPLE=' + json.dumps(dict(refresh=cli_refresh,fields=fields,plan=plan,relevance=relevance,status=status,restore=restored),sort_keys=True))
