import sqlite3
from types import SimpleNamespace

from jobwatch.config import Config
from pipeline import discovery_vocabulary as store
from pipeline import vocabulary_research as research


def config():
    return Config(None, {'pipeline': {'discovery_research': {'enabled': True,
        'sources': [{'source': 'seek', 'url': 'https://careers.example.com/jobs'}]}}}, {},
        {'seek': {'enabled': True, 'keywords': ['admin']},
         'jora': {'enabled': False, 'keywords': ['clerical']},
         'jobspy': {'enabled': True, 'searches': [{'term': 'clerical'}]}}, {}, [])


def test_goal_research_overlay_refresh_corrections_and_failure():
    conn = sqlite3.connect(':memory:'); calls=[]; cfg=config()
    def fetch(url):
        calls.append(url)
        return '<h2>Administrative Assistant</h2><a>Clerical Officer</a><a>Software Engineer</a>'
    result=research.prepare(conn, cfg, 'a', ['Administrative and Clerical roles'], fetch_page=fetch)
    assert result.searches['seek']['keywords'] == ['admin', 'Administrative Assistant', 'Clerical Officer']
    assert result.searches['jora'] == cfg.searches['jora']
    assert cfg.searches['seek']['keywords'] == ['admin']
    assert len(calls)==1
    research.prepare(conn,cfg,'a',['Administrative and Clerical roles'],fetch_page=fetch)
    assert len(calls)==1
    store.override(conn,'a','seek','Clerical Officer','exclude')
    assert 'Clerical Officer' not in research.overlay(conn,'a',cfg).searches['seek']['keywords']
    result=research.prepare(conn,cfg,'a',['Clerical roles'],fetch_page=fetch)
    assert len(calls)==2 and 'Clerical Officer' not in result.searches['seek']['keywords']
    before=store.status(conn,'a')['active_version']
    def failed(_): raise TimeoutError('source timeout')
    research.prepare(conn,cfg,'a',['Admin roles'],fetch_page=failed)
    assert store.status(conn,'a')['active_version']==before
    assert 'TimeoutError' in store.status(conn,'a')['error']
    assert store.queries(conn,'b','seek')==[]


def test_source_specific_queries_never_enable_collectors():
    conn=sqlite3.connect(':memory:');cfg=config()
    cfg.settings['pipeline']['discovery_research']['sources']=[
        {'source':'jobspy','url':'https://careers.example.com/jobs'},
        {'source':'jora','url':'https://careers.example.com/jobs'}]
    result=research.prepare(conn,cfg,'a',['Clerical'],fetch_page=lambda _: '<h2>Clerical Officer</h2>')
    assert result.searches['jobspy']['searches']==[{'term':'clerical'},{'term':'Clerical Officer'}]
    assert result.searches['jora']['enabled'] is False
    assert 'categories' not in result.settings['pipeline']


def test_public_source_validation():
    import pytest
    def local(*args,**kwargs):return [(0,0,0,'',('127.0.0.1',443))]
    for url in ['http://careers.example.com','https://user:pass@careers.example.com','https://127.0.0.1']:
        with pytest.raises(ValueError): research.public_url(url,resolve=local)
    assert research.public_url('https://careers.example.com/jobs',resolve=lambda *a,**k:[(0,0,0,'',('93.184.216.34',443))])


def test_missing_goals_or_disabled_research_does_not_fetch():
    conn=sqlite3.connect(':memory:');cfg=config()
    def fail(_):raise AssertionError('must not fetch')
    assert research.prepare(conn,cfg,'a',[],fetch_page=fail) is cfg
    cfg.settings['pipeline']['discovery_research']['enabled']=False
    assert research.prepare(conn,cfg,'a',['Admin'],fetch_page=fail) is cfg
