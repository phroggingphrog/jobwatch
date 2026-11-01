from types import SimpleNamespace

from conftest import make_config
from jobwatch import db
from jobwatch.dedupe import ingest
from jobwatch.models import Posting
from pipeline import store
from pipeline.schemas import Stage
from pipeline.agentic import discovery


def test_goal_only_archives_recover_without_plan_or_new_judgment(tmp_path,monkeypatch):
    conn=db.connect(tmp_path/'jobs.db');store.ensure(conn)
    for i in range(3):
        pid,_=ingest(conn,Posting(source='fixture',source_id=str(i),url=f'https://example.com/{i}',title='Clerical Officer'))
        store.admit(conn,pid,str(i),{},Stage.ARCHIVED,reason='not_relevant')
        if i==2:conn.execute('UPDATE postings SET closed_at=? WHERE id=?',('2026-01-01',pid))
    conn.commit()
    monkeypatch.setattr(discovery,'_current_plan',lambda p:(None,None))
    config={'agentic':{'relevance':'off'},'discovery':{'reconsider_per_run':1}}
    assert discovery.reconsider(conn,config)==1
    assert discovery.reconsider(conn,config)==1
    assert discovery.reconsider(conn,config)==0
    assert store.get(conn,3)['stage']=='archived'
    assert conn.execute("SELECT COUNT(*) FROM pipeline_events WHERE node='discovery_reconsider'").fetchone()[0]==2
