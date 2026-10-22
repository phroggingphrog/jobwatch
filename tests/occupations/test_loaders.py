import hashlib
import json

import pytest

from jobwatch.occupations import DiscoveryError
from jobwatch.occupations import datasets, loaders
from jobwatch.occupations.loaders import load_bundled, load_esco, load_onet, load_osca, load_reference_records, record_text
from tests.occupations.reference_fixtures import write_onet, write_esco, write_xlsx


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setattr(datasets, 'PINNED', {})


def register(monkeypatch, directory, dataset='onet'):
    spec = datasets.DatasetSpec(dataset=dataset, version='fx', source_url='https://fixture.invalid/', licence='CC BY 4.0',
        attribution='Invented fixture', files=tuple(datasets.FileSpec(name=p.name, url='https://fixture.invalid/'+p.name,
        sha256=hashlib.sha256(p.read_bytes()).hexdigest(), bytes=p.stat().st_size) for p in sorted(directory.iterdir())))
    payloads={p.name:p.read_bytes() for p in directory.iterdir()}
    monkeypatch.setattr(datasets, 'PINNED', {dataset:spec})
    datasets.fetch_dataset(spec, opener=lambda u:payloads[u.rsplit('/',1)[1]])
    return datasets.dataset_dir(dataset, 'fx')


def test_bundled_reference_gives_one_record_per_occupation():
    records, links, version = load_bundled()
    assert len(records)==1074
    assert all(r.scheme=='anzsco2022' and len(r.text)<=1800 and r.text.startswith(r.title) for r in records)
    assert load_bundled()[0]==records
    assert links and all(c.kind=='broad' for c in links)


def test_record_text_cuts_on_a_word_boundary():
    t=record_text('Accountant', 'x '*2000)
    assert len(t)<=1800 and not t.endswith(' ') and t.startswith('Accountant.')
    assert record_text('A','B', ['first','second'], ['math'])=='A. B Tasks: first; second. Skills: math.'
    assert len(record_text('x'*2000))<=1800


def test_onet_loader_orders_core_tasks_first_and_keeps_top_skills(tmp_path):
    records,_=load_onet(write_onet(tmp_path), 'fx')
    r=records[0]
    assert r.text.index('Core task first')<r.text.index('Core task A')<r.text.index('Supplemental task B')
    assert 'Mathematics' in r.text and 'Ignored level' not in r.text and 'Skill 00' not in r.text


def test_esco_loader_uses_essential_skills_only(tmp_path):
    records,_=load_esco(write_esco(tmp_path), 'fx')
    assert 'keep accounting records' in records[0].text and 'optional skill' not in records[0].text
    assert records[0].id=='esco:http://data.europa.eu/esco/occupation/test'


def test_missing_columns_fail_closed_and_other_datasets_still_load(tmp_path,monkeypatch):
    register(monkeypatch,write_onet(tmp_path/'onet',drop_column='Task'))
    out=load_reference_records()
    assert out.skipped['onet']=='dataset_schema_changed' and len(out.records)==1074


def test_unverified_dataset_is_not_loaded_even_after_it_was_cached(tmp_path,monkeypatch):
    path=register(monkeypatch,write_onet(tmp_path/'onet'))
    assert len(load_reference_records().records)==1075
    (path/'task_statements.csv').write_bytes(b'tampered')
    out=load_reference_records()
    assert out.skipped['onet']=='dataset_hash_mismatch' and len(out.records)==1074


def test_osca_loader_uses_recorded_column_map_and_carries_merged_cells(tmp_path):
    write_xlsx(tmp_path/'s.xlsx',{2:[['Identifier','Principal Title','Other','Lead Statement'],['211131','Accountant','','Prepares accounts'],['211132','Auditor','','Checks accounts']]})
    write_xlsx(tmp_path/'c.xlsx',{6:[['ANZSCO 2022','','OSCA 2024'],['221111','','211131'],['','','211132']]})
    columns={'structure':{'file':'s.xlsx','sheet':2,'code':'A','title':'B','description':'D'},
             'correspondence':{'file':'c.xlsx','sheet':6,'anzsco':'A','osca':'C'}}
    recs,links=load_osca(tmp_path,'fx',columns)
    assert recs[0].id=='osca:211131' and 'Prepares accounts' in recs[0].text
    assert {(c.a,c.b) for c in links}=={('anzsco2022:221111','osca:211131'),('anzsco2022:221111','osca:211132')}


def test_osca_missing_columns_fail_closed(tmp_path):
    write_xlsx(tmp_path/'s.xlsx',{1:[['Code','Title'],['211131','Accountant']]})
    with pytest.raises(DiscoveryError,match='dataset_schema_changed'):
        load_osca(tmp_path,'fx',{'structure':{'file':'s.xlsx','sheet':1,'code':'A','title':'B','description':'D'}})


def test_correspondences_with_unloaded_endpoint_are_dropped():
    out=load_reference_records(); ids={r.id for r in out.records}
    assert all(c.a in ids and c.b in ids for c in out.correspondences)
    triples=[(r.scheme,r.code,r.text) for r in out.records]
    assert out.records_hash==hashlib.sha256(json.dumps(triples,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def test_only_bundled_never_includes_optional_sources(tmp_path,monkeypatch):
    register(monkeypatch,write_onet(tmp_path/'onet'))
    assert len(load_reference_records(only=()).records)==1074


def test_crosswalk_uses_real_esco_numeric_codes_not_a_guessed_uri_column(tmp_path,monkeypatch):
    onet=write_onet(tmp_path/'onet'); esco=write_esco(tmp_path/'esco')
    p=esco/'occupations_en.csv'
    from tests.occupations.reference_fixtures import write_csv
    write_csv(p,['conceptUri','preferredLabel','description','iscoGroup','code'],[
        {'conceptUri':'http://data.europa.eu/esco/occupation/test','preferredLabel':'accountant','description':'Produces accounts','iscoGroup':'2411','code':'2411.1'}])
    write_xlsx(onet/'esco.xlsx',{1:[['ESCO/ISCO Code','ESCO/ISCO Title','O*NET-SOC 2019 Code'],['2411.1','accountant','13-2011.00']]})
    onet_spec=None
    register(monkeypatch,onet)
    onet_spec=datasets.PINNED['onet']
    register(monkeypatch,esco,'esco')
    monkeypatch.setattr(datasets,'PINNED',{'onet':onet_spec,**datasets.PINNED})
    out=load_reference_records()
    assert any(c.a=='esco:http://data.europa.eu/esco/occupation/test' and c.b=='onet:13-2011.00' and c.kind=='broad' for c in out.correspondences)


def test_osca_correspondence_schema_failure_is_not_silent(tmp_path):
    write_xlsx(tmp_path/'s.xlsx',{1:[['Code','Title','Description'],['211131','Accountant','Prepares accounts']]})
    write_xlsx(tmp_path/'c.xlsx',{1:[['ANZSCO'],['221111']]})
    with pytest.raises(DiscoveryError,match='dataset_schema_changed'):
        load_osca(tmp_path,'fx',{'structure':{'file':'s.xlsx','sheet':1,'code':'A','title':'B','description':'C'},
                               'correspondence':{'file':'c.xlsx','sheet':1,'anzsco':'A','osca':'C'}})


def test_broken_optional_crosswalk_does_not_break_bundled_reference(tmp_path,monkeypatch):
    path=write_onet(tmp_path/'onet')
    write_xlsx(path/'esco.xlsx',{1:[['wrong header'],['unrecognised']]})
    register(monkeypatch,path)
    out=load_reference_records()
    assert out.skipped['onet']=='dataset_schema_changed'
    assert len(out.records)==1074


def test_esco_requires_its_numeric_crosswalk_code_column(tmp_path):
    path=write_esco(tmp_path)
    from tests.occupations.reference_fixtures import write_csv
    write_csv(path/'occupations_en.csv',['conceptUri','preferredLabel','description','iscoGroup'],[
        {'conceptUri':'test','preferredLabel':'accountant','description':'Records','iscoGroup':'2411'}])
    with pytest.raises(DiscoveryError,match='dataset_schema_changed'):
        load_esco(path,'fx')
