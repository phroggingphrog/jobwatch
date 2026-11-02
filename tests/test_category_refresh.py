import json

from conftest import make_config
from jobwatch import db
from jobwatch.dedupe import ingest
from jobwatch.models import Posting
from pipeline import category_refresh,store
from pipeline.schemas import Stage


def test_category_refresh_is_bounded_idempotent_preserves_explicit_and_closed(tmp_path):
    cfg=make_config(tmp_path=tmp_path,settings={'pipeline':{'screened':{'category_snapshot':{'categories':[
        dict(id='office',label='Office',priority=0,phrases=['clerical'],action='admit',promote=True,hours='standard')]}}}})
    conn=db.connect(cfg.db_path)
    store.ensure(conn)
    for i in range(1,5):
        pid,_=ingest(conn,Posting(source='synthetic',source_id=str(i),url=f'https://example.com/{i}',
            title='Clerical Officer',description='Maintain office records and prepare documents for staff.'*10))
        reason='work_rights_incompatible' if i==3 else 'title_not_target'
        store.admit(conn,pid,f'h{i}',{'track':'old'},Stage.ARCHIVED,reason=reason)
        if i==4:conn.execute('UPDATE postings SET closed_at=? WHERE id=?',('2026-01-01',pid))
    conn.commit()
    assert category_refresh.refresh(conn,cfg,limit=1)==1
    row=store.get(conn,1)
    assert row['stage']=='ingested' and row['data']['track']=='office'
    assert row['data']['ingest']['posting_id']==1
    assert category_refresh.refresh(conn,cfg,limit=100)==1
    assert category_refresh.refresh(conn,cfg,limit=100)==0
    assert store.get(conn,3)['stage']=='archived'
    assert store.get(conn,4)['stage']=='archived'
    assert conn.execute("SELECT COUNT(*) FROM pipeline_events WHERE node='category_refresh'").fetchone()[0]==2


def test_changed_explicit_archive_stays_excluded(tmp_path):
    cfg=make_config(tmp_path=tmp_path,settings={'pipeline':{'screened':{'category_snapshot':{'categories':[
        dict(id='explicit',label='Excluded by owner',priority=0,phrases=['clerical'],action='archive',exclusion_confirmed=True,promote=False,hours='standard')]}}}})
    conn=db.connect(cfg.db_path)
    store.ensure(conn)
    pid,_=ingest(conn,Posting(source='synthetic',source_id='x',url='https://example.com/x',title='Clerical Officer'))
    store.admit(conn,pid,'h',{'track':'old'},Stage.ARCHIVED,reason='title_not_target')
    assert category_refresh.refresh(conn,cfg)==0
    assert store.get(conn,pid)['stage']=='archived'
