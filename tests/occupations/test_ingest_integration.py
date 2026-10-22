from types import SimpleNamespace

from conftest import make_config
from jobwatch import db, adtext
from jobwatch.models import Posting
from jobwatch.dedupe import ingest as save_posting
from jobwatch.occupations.plan import search_plan
from pipeline.nodes import ingest
from pipeline import store


def setup(tmp_path, **flags):
    cfg = make_config(tmp_path=tmp_path, settings={'pipeline':{'execution_mode':'agentic','agentic':flags}})
    conn = db.connect(cfg.db_path); store.ensure(conn)
    return conn,cfg


def add(conn, source, sid, city):
    posting = Posting(source=source,source_id=sid,url=f'https://example.invalid/{source}/{sid}',
        title='Accounts Officer',company='Acme',location=city,description='Reconcile supplier ledgers daily. ' * 80)
    pid,_ = save_posting(conn,posting)
    adtext.save_text(conn,pid,posting.description,'synthetic')
    conn.commit()
    return pid


def test_semantic_mode_does_not_hash_merge_same_template_different_cities_or_requisitions(tmp_path):
    conn,cfg = setup(tmp_path,dedupe='semantic')
    ids = [add(conn,'one','1','Melbourne VIC'),add(conn,'two','2','Geelong VIC'),add(conn,'one','3','Melbourne VIC')]
    ingest.run(conn,cfg,fetch_budget=0)
    assert [store.get(conn,pid)['stage'] for pid in ids] == ['ingested']*3


def test_search_plan_location_is_not_blocked_by_legacy_victoria_prefilter(tmp_path,monkeypatch):
    conn,cfg = setup(tmp_path,search_plan=True)
    pol = SimpleNamespace(profile_version=1,policy_hash='a'*64,focus=(),home={'place':'Sydney','state':'NSW'},remote_ok=False)
    cfg.extra['search_plan'] = search_plan(pol,[SimpleNamespace(title='Accountant',id='anzsco2022:221111')])
    from jobwatch.candidate import policy
    dp = policy.build_policy({'version':1,'facts':[{'id':'home','section':'location','basis':'evidence','value':'Sydney NSW'}]})
    monkeypatch.setattr(policy,'policy_for',lambda person:dp)
    pid = add(conn,'one','1','Sydney NSW')
    ingest.run(conn,cfg,fetch_budget=0)
    assert store.get(conn,pid)['stage'] == 'ingested'


def test_legacy_location_and_hash_dedup_remain_the_default(tmp_path):
    conn,cfg = setup(tmp_path)
    outside = add(conn,'one','1','Sydney NSW')
    older = add(conn,'one','2','Melbourne VIC')
    newer = add(conn,'two','3','Geelong VIC')
    ingest.run(conn,cfg,fetch_budget=0)
    assert store.get(conn,outside) is None
    assert store.get(conn,older)['stage'] == 'ingested'
    assert store.get(conn,newer)['reason'] == f'duplicate_of:{older}'


def test_semantic_collection_defers_same_key_merges_until_description_comparison(tmp_path):
    conn,cfg = setup(tmp_path,dedupe='semantic')
    a = Posting(source='one',source_id='1',url='https://example.invalid/one',title='Accounts Officer',company='Acme',location='Sydney')
    b = Posting(source='two',source_id='2',url='https://example.invalid/two',title='Accounts Officer',company='Acme',location='Sydney')
    older,_ = save_posting(conn,a,key_merge=False)
    newer,is_new = save_posting(conn,b,key_merge=False)
    assert is_new and newer != older
    assert save_posting(conn,a,key_merge=False) == (older,False)
