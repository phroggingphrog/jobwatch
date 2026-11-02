import sqlite3
from types import SimpleNamespace

from jobwatch.config import Config
from pipeline import tracks
from pipeline import vocabulary_research as research


def test_effective_searches_and_configured_category_receive_researched_terms():
    conn=sqlite3.connect(':memory:')
    cfg=Config(None, {'pipeline': {
        'screened': {'category_snapshot': {'categories': [dict(id='office',label='Office',priority=0,
            phrases=['admin'],action='admit',promote=True,hours='standard')]}},
        'discovery_research': {'sources':[dict(source='seek',url='https://careers.example.com/jobs',category_id='office')]} }},
        {}, {'seek': {'enabled':True,'keywords':['stale'], 'searches':[dict(term='admin',where='Melbourne')]}}, {}, [])
    result=research.prepare(conn,cfg,'person',['Admin and clerical roles'],
        fetch_page=lambda _: '<h2>Clerical Officer</h2>')
    assert result.searches['seek']['searches'] == [dict(term='admin',where='Melbourne'),dict(term='Clerical Officer',where='Melbourne')]
    assert tracks.classify('Clerical Officer',tracks.settings(result))=='office'
    assert tracks.classify('Clerical Officer',tracks.settings(cfg)) is None
    assert result.settings['pipeline']['screened']['category_snapshot']['categories'][0]['hours']=='standard'


def test_goal_alone_researches_without_manual_source_list():
    conn=sqlite3.connect(':memory:');calls=[]
    cfg=Config(None,{}, {}, {'seek':{'enabled':True,'keywords':['admin']}}, {}, [])
    result=research.prepare(conn,cfg,'person',['Admin and clerical roles'],
        fetch_page=lambda url: calls.append(url) or '<h2>Clerical Officer</h2>')
    assert len(calls)==1 and 'duckduckgo.com' in calls[0] and 'clerical' in calls[0]
    assert result.searches['seek']['keywords']==['admin','Clerical Officer']


def test_dry_run_projection_does_not_research(monkeypatch):
    from pipeline.agentic import discovery
    from jobwatch import users
    monkeypatch.setattr(discovery.intake,'discovery_scope',lambda _:SimpleNamespace(basis=('Clerical',),locations=()))
    monkeypatch.setattr(discovery,'_current_plan',lambda _:(SimpleNamespace(focus=('Clerical',)),None))
    monkeypatch.setattr(discovery,'search_plan',lambda *a,**k:object())
    monkeypatch.setattr(discovery,'searches_overlay',lambda p,s,pol:s)
    monkeypatch.setattr(discovery,'feeds_overlay',lambda p,s,pol:s)
    monkeypatch.setattr(research,'prepare',lambda *a,**k: (_ for _ in ()).throw(AssertionError('research in projection')))
    cfg=Config(None,{}, {}, {}, {}, [])
    assert discovery.prepare_run(sqlite3.connect(':memory:'),cfg).searches=={}
