"""In-memory synthetic fixtures test preservation of explicit owner-labelled history."""
import copy
import sqlite3

import pytest
from jobwatch.preferences import PreferenceError, PreferenceStore
from jobwatch.preferences.features import versions
from tests.preferences.test_core import CTX, alternative


def historical(monkeypatch, *, selected=2, answered=True, origin='owner', holdout=True):
    from jobwatch.preferences import store as module
    conn=sqlite3.connect(':memory:')
    store=PreferenceStore(conn,origin=origin)
    rows=[{**alternative(i),'approved_hash':'c'*64,'policy_hash':'d'*64} for i in (1,2,3)]
    old_versions={**versions(),'feature':'choice-features-historical'}
    with monkeypatch.context() as patch:
        patch.setattr(module,'versions',lambda:old_versions)
        item=store.create_set(rows,'e'*64,holdout=holdout)
        if answered: item=store.pick(item['id'],selected,actor='owner',request_id='original')
    from jobwatch import preference_service
    monkeypatch.setattr(preference_service,'pool',lambda conn, cfg, *, statuses: (CTX,copy.deepcopy(rows)))
    return conn,store,item,rows


@pytest.mark.parametrize('selected',[None,2])
def test_migration_preserves_originals_selected_none_and_split(monkeypatch, selected):
    from jobwatch.preferences.migration import refeaturise
    conn,store,old,rows=historical(monkeypatch,selected=selected)
    original=tuple(conn.execute('SELECT * FROM preference_sets WHERE id=?',(old['id'],)).fetchone())
    pick=tuple(conn.execute('SELECT * FROM preference_picks WHERE set_id=?',(old['id'],)).fetchone())
    result=refeaturise(conn,None,actor='owner')
    assert result=={'migrated':1,'already':0,'not_current':0,'changed':0}
    new=[s for s in store.list_sets() if s['versions']==versions()]
    assert len(new)==1 and new[0]['answered'] and new[0]['selected']==selected
    assert new[0]['holdout']==old['holdout'] and new[0]['migrated_from']==old['id']
    assert conn.execute('SELECT request_id,actor FROM preference_picks WHERE set_id=?',(new[0]['id'],)).fetchone()==('migrate:'+old['id'],'owner')
    assert tuple(conn.execute('SELECT * FROM preference_sets WHERE id=?',(old['id'],)).fetchone())==original
    assert tuple(conn.execute('SELECT * FROM preference_picks WHERE set_id=?',(old['id'],)).fetchone())==pick
    before=list(conn.iterdump())
    assert refeaturise(conn,None,actor='owner')=={'migrated':0,'already':1,'not_current':0,'changed':0}
    assert list(conn.iterdump())==before


@pytest.mark.parametrize('key',['approved_hash','policy_hash','profile_hash','ad_hash','run_key','evaluation_hash','title','company'])
def test_migration_refuses_changed_or_unverifiable_provenance(monkeypatch,key):
    from jobwatch.preferences.migration import refeaturise
    conn,store,old,rows=historical(monkeypatch)
    rows[0][key]='f'*64 if key not in ('title','company') else 'Changed identity'
    before=list(conn.iterdump())
    assert refeaturise(conn,None,actor='owner')['changed']==1
    assert list(conn.iterdump())==before


def test_migration_skips_unverifiable_historical_profile_and_absent_jobs(monkeypatch):
    from jobwatch.preferences.migration import refeaturise
    from jobwatch import preference_service
    conn,store,old,rows=historical(monkeypatch)
    monkeypatch.setattr(preference_service,'pool',lambda *a,**kw:(CTX,rows[:2]))
    assert refeaturise(conn,None,actor='owner')['not_current']==1


@pytest.mark.parametrize('answered,origin',[(False,'owner'),(True,'synthetic')])
def test_migration_never_promotes_unanswered_or_synthetic_labels(monkeypatch,answered,origin):
    from jobwatch.preferences.migration import refeaturise
    conn,store,old,rows=historical(monkeypatch,answered=answered,origin=origin)
    before=list(conn.iterdump())
    assert refeaturise(conn,None,actor='owner')=={'migrated':0,'already':0,'not_current':0,'changed':0}
    assert list(conn.iterdump())==before


def test_migration_checks_owner_before_any_access():
    from jobwatch.preferences.migration import refeaturise
    with pytest.raises(PreferenceError,match='explicit_owner_required'):
        refeaturise(None,None,actor='agent')


def test_migration_skips_missing_old_approved_hash(monkeypatch):
    from jobwatch.preferences import store as module
    from jobwatch.preferences.migration import refeaturise
    from jobwatch import preference_service
    conn=sqlite3.connect(':memory:'); store=PreferenceStore(conn)
    rows=[alternative(i) for i in (1,2,3)]
    old_versions={**versions(),'feature':'choice-features-historical'}
    with monkeypatch.context() as patch:
        patch.setattr(module,'versions',lambda:old_versions)
        old=store.create_set(rows,'e'*64)
        store.pick(old['id'],None,actor='owner',request_id='original')
    current=[{**a,'approved_hash':'c'*64,'policy_hash':'d'*64} for a in rows]
    monkeypatch.setattr(preference_service,'pool',lambda *a,**kw:(CTX,current))
    before=list(conn.iterdump())
    assert refeaturise(conn,None,actor='owner')['changed']==1
    assert list(conn.iterdump())==before


def test_migration_recovers_interruption_without_reanswering(monkeypatch):
    from jobwatch.preferences.migration import refeaturise
    conn,store,old,rows=historical(monkeypatch,selected=None)
    original_pick=PreferenceStore.pick
    with monkeypatch.context() as patch:
        patch.setattr(PreferenceStore,'pick',lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('synthetic interruption')))
        with pytest.raises(RuntimeError): refeaturise(conn,None,actor='owner')
    copies=[s for s in store.list_sets() if s.get('migrated_from')==old['id']]
    assert len(copies)==1 and not copies[0]['answered']
    assert refeaturise(conn,None,actor='owner')['migrated']==1
    copies=[s for s in store.list_sets() if s.get('migrated_from')==old['id']]
    assert len(copies)==1 and copies[0]['answered'] and copies[0]['selected'] is None


def test_multiple_version_upgrades_do_not_duplicate_historical_labels(monkeypatch):
    from jobwatch.preferences.migration import refeaturise
    from jobwatch.preferences import store as store_module, migration as migration_module
    conn,store,old,rows=historical(monkeypatch)
    assert refeaturise(conn,None,actor='owner')['migrated']==1
    newer={**versions(),'feature':'choice-features-synthetic-next'}
    monkeypatch.setattr(store_module,'versions',lambda:newer)
    monkeypatch.setattr(migration_module,'versions',lambda:newer)
    assert refeaturise(conn,None,actor='owner')['migrated']==1
    current=store.dataset(CTX)
    assert len(current)==1 and current[0]['migrated_from']==old['id']


def test_changed_current_pool_during_migration_cannot_copy_stale_choice(monkeypatch):
    from jobwatch.preferences.migration import refeaturise
    from jobwatch import preference_service
    conn,store,old,rows=historical(monkeypatch)
    calls=[]
    def pool(*a,**kw):
        calls.append(1)
        changed=copy.deepcopy(rows)
        if len(calls)>1: changed[0]['approved_hash']='f'*64
        return CTX,changed
    monkeypatch.setattr(preference_service,'pool',pool)
    before=list(conn.iterdump())
    assert refeaturise(conn,None,actor='owner')['changed']==1
    assert list(conn.iterdump())==before


def test_held_migration_preserves_explicit_noneligible_status(monkeypatch):
    from jobwatch.preferences import store as module
    from jobwatch.preferences.migration import refeaturise
    from jobwatch import preference_service
    conn=sqlite3.connect(':memory:'); store=PreferenceStore(conn)
    rows=[{**alternative(i),'approved_hash':'c'*64,'policy_hash':'d'*64} for i in (1,2,3)]
    rows[2].update(status='held',eligible=False,
                   gate={'route':'hold','reason':'insufficient_evidence','run_key':rows[2]['run_key']})
    rows[2]['features']['status_held']=1
    old_versions={**versions(),'feature':'choice-features-historical'}
    with monkeypatch.context() as patch:
        patch.setattr(module,'versions',lambda:old_versions)
        old=store.create_set(rows,'e'*64,holdout=True)
        store.pick(old['id'],3,actor='owner',request_id='original')
    def pool(*a,**kw):
        assert kw['statuses']==('eligible','held')
        return CTX,copy.deepcopy(rows)
    monkeypatch.setattr(preference_service,'pool',pool)
    assert refeaturise(conn,None,actor='owner')['migrated']==1
    copied=store.dataset(CTX)[0]
    assert copied['selected']==3 and copied['alternatives'][2]['eligible'] is False
    assert copied['alternatives'][2]['status']=='held'


def test_migration_never_combines_cross_context_postings_across_splits(monkeypatch):
    from jobwatch.preferences import store as module
    from jobwatch.preferences.migration import refeaturise
    conn,store,old,rows=historical(monkeypatch)
    old_versions={**versions(),'feature':'choice-features-historical'}
    with monkeypatch.context() as patch:
        patch.setattr(module,'versions',lambda:old_versions)
        other=store.create_set(rows,'f'*64,holdout=False)
        store.pick(other['id'],None,actor='owner',request_id='other-original')
    assert refeaturise(conn,None,actor='owner')=={'migrated':1,'already':0,'not_current':0,'changed':1}
    assert len(store.dataset(CTX))==1 and store.dataset(CTX)[0]['holdout'] is True
    assert store.get_set(other['id'])['holdout'] is False
