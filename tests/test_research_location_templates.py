import sqlite3
from datetime import UTC,datetime
from jobwatch.config import Config
from pipeline import discovery_vocabulary as store
from pipeline.vocabulary_research import overlay


def test_research_preserves_all_location_remote_and_site_templates():
    conn=sqlite3.connect(':memory:')
    version=store.set_goal(conn,'a','clerical')
    store.activate(conn,'a',version,[dict(term='Records Clerk',source='seek',url='https://example.com/jobs',retrieved_at=datetime.now(UTC),goal_version=version)])
    cfg=Config(None,{}, {}, {'seek':{'enabled':True,'searches':[
        dict(term='clerical',where='Melbourne',remote=False),
        dict(term='clerical',where='Sydney',remote=True)]}}, {}, [])
    out=overlay(conn,'a',cfg)
    assert out.searches['seek']['searches'][2:]==[
        dict(term='Records Clerk',where='Melbourne',remote=False),
        dict(term='Records Clerk',where='Sydney',remote=True)]
    assert all('where' in row for row in out.searches['seek']['searches'])
    assert len(cfg.searches['seek']['searches'])==2
