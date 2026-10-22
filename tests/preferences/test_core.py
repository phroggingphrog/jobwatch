import copy
import json
import math
import sqlite3
from pathlib import Path
import pytest
from jobwatch.preferences import PreferenceStore, PreferenceError, context_hash, evaluate_fit, predict_set
from jobwatch.preferences.features import NAMES, FAMILIES, versions
from jobwatch.preferences.model import parameter_names, prepare_data, transform_features

CTX='a'*64

def alternative(pid):
    return {'posting_id':pid,'title':'Synthetic vacancy','company':'Synthetic employer',
            'family':'accounting','features':dict.fromkeys(NAMES), 'eligible':True,'current':True,
            **{k:'b'*64 for k in ('ad_hash','profile_hash','run_key','evaluation_hash')}}

@pytest.fixture
def store():
    return PreferenceStore(sqlite3.connect(':memory:'),origin='synthetic')

def test_gets_do_not_migrate(store):
    assert store.status(CTX)['status']=='no_data'
    assert store.list_sets()==[]
    assert store.conn.execute("SELECT name FROM sqlite_master").fetchall()==[]

def test_immutable_owner_explicit_idempotent(store):
    choice=store.create_set([alternative(i) for i in (1,2,3)],CTX)
    assert store.create_set([alternative(i) for i in (1,2,3)],CTX)['id']==choice['id']
    with pytest.raises(PreferenceError,match='explicit_owner_required'):
        store.pick(choice['id'],None,actor='agent',request_id='x')
    picked=store.pick(choice['id'],None,actor='owner',request_id='x')
    assert picked['answered'] and picked['selected'] is None
    assert store.pick(choice['id'],None,actor='owner',request_id='x')==picked
    with pytest.raises(PreferenceError,match='pick_conflict'):
        store.pick(choice['id'],1,actor='owner',request_id='x')
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute('UPDATE preference_picks SET selected=1')
    store.conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute('DELETE FROM preference_sets')
    store.conn.rollback()
    assert store.status(CTX)['status']=='insufficient_data'

def test_reject_bad_alternatives(store):
    for update in ({'family':''},{'current':False},{'eligible':False},{'ad_hash':'bad'}):
        rows=[alternative(i) for i in (1,2,3)]; rows[0].update(update)
        with pytest.raises(PreferenceError): store.create_set(rows,CTX)
    with pytest.raises(PreferenceError): store.create_set([alternative(1)]*3,CTX)

def populate(store,count=25):
    for s in range(count):
        rows=[alternative(3*s+a+1) for a in range(3)]
        for a,row in enumerate(rows):
            row['features']['pay_low_c']=20+a if s%5!=4 else 1e5
            row['features']['entry_signal']=a%2
        c=store.create_set(rows,CTX)
        store.pick(c['id'],None if s%7==0 else rows[0]['posting_id'],actor='owner',request_id=str(s))
    return store.dataset(CTX)

def test_train_only_missing_and_posting_split(store):
    sets=populate(store)
    payload=prepare_data(sets)
    idx=NAMES.index('pay_low_c')
    assert payload['preprocessing']['centers'][idx]==21
    x=payload['sets'][0]['x'][0]
    assert payload['sets'][0]['missing'][0][NAMES.index('coverage')] is True
    assert x[NAMES.index('coverage')+len(NAMES)]==0  # centred constant missingness, not an intercept surrogate
    assert x[NAMES.index('entry_signal')+len(NAMES)]==0
    assert store.status(CTX)['status']=='untrained'
    training=next(s for s in sets if not s['holdout']); held=next(s for s in sets if s['holdout'])
    with pytest.raises(PreferenceError,match='split_overlap'):
        store.create_set([training['alternatives'][0],held['alternatives'][0],alternative(10000)],CTX)
    bad=copy.deepcopy(sets); bad[-1]['alternatives'][0]['posting_id']=sets[0]['alternatives'][0]['posting_id']
    with pytest.raises(PreferenceError,match='split_overlap'): prepare_data(bad)

def good_summary():
    return {'chains':4,'seeds':[1103,2207,3301,4409],'n_train':20,'n_holdout':5,
        'holdout_log_score':-4.,'prior_log_score':-8.,
        'parameters':{n:{'rhat':1.,'ess':20000.,'mcse':1/math.sqrt(20000),
          'mcse_ratio':1/math.sqrt(20000),'sd':1.,'mean':0.,'mode':0.,'hdi_low':-2.,'hdi_high':2.} for n in parameter_names()}}

def test_finite_per_parameter_gates_and_holdout():
    summary=good_summary(); assert evaluate_fit(summary)['accepted']
    for key,value in [('rhat',float('nan')),('ess',float('inf')),('ess',1000),('ess',0),('ess',-1),('sd',0),('mcse',-.1),('mcse_ratio',.1)]:
        bad=copy.deepcopy(summary); bad['parameters']['tau'][key]=value
        assert not evaluate_fit(bad)['accepted']
    bad=copy.deepcopy(summary); del bad['parameters']['tau']
    assert not evaluate_fit(bad)['accepted']
    summary['holdout_log_score']=-9
    assert not evaluate_fit(summary)['accepted']

def test_stale_and_synthetic_cannot_predict(store):
    populate(store)
    s=good_summary();s.update(id='fit',dataset_hash=store.dataset_hash(CTX),context_hash=CTX,versions=versions(),origin='synthetic')
    store.save_fit(s)
    assert store.status(CTX)['status']=='synthetic_valid'
    with pytest.raises(PreferenceError,match='valid_current_fit_required'):
        predict_set(store,[alternative(i) for i in (100,101,102)],CTX)
    c=store.create_set([alternative(i) for i in (100,101,102)],CTX)
    store.pick(c['id'],100,actor='owner',request_id='new')
    assert store.status(CTX)['status']=='stale'

def test_synthetic_cannot_mix_with_owner(store):
    store.create_set([alternative(i) for i in (1,2,3)],CTX)
    with pytest.raises(PreferenceError,match='mixed_data_origins'):
        PreferenceStore(store.conn).create_set([alternative(i) for i in (4,5,6)],CTX)

def test_prediction_arithmetic_in_memory_fixture_only():
    """Stub authorization/status only; this fixture is never saved/exported as owner data."""
    from jobwatch.preferences.model import predict_set
    rows=[alternative(i) for i in (1,2,3)]
    for i,row in enumerate(rows): row['features']['coverage']=i/2
    transform={'centers':[0.]*len(NAMES),'scales':[1.]*len(NAMES),
               'missing_rates':[0.]*len(NAMES)}
    b=[0.]*(len(NAMES)*2);b[NAMES.index('coverage')]=2.
    fit={'id':'arithmetic-fixture','context_hash':CTX,'origin':'owner','profile_hash':'b'*64,
         'draws':{'beta':[b,b],'alpha':[[0.]*len(FAMILIES),[0.]*len(FAMILIES)]},'preprocessing':transform}
    class Stub:
        def status(self,ctx):return {'status':'valid','fit':fit}
    result=predict_set(Stub(),rows,CTX)
    assert result['ranking']==[3,2,1]
    probabilities=[a['choice_probability']['mean'] for a in result['alternatives']]
    assert sum(probabilities)+result['none_probability']['mean']==pytest.approx(1.)
    assert probabilities[0]==result['none_probability']['mean']
    assert result['alternatives'][2]['contributions']['coverage']['mean']==2.
    bad=copy.deepcopy(rows);bad[0]['profile_hash']='c'*64
    # Every alternative is required to have the same current profile even before fit matching.
    with pytest.raises(PreferenceError,match='mixed_profiles'):predict_set(Stub(),bad,CTX)
    for r in bad:r['profile_hash']='c'*64
    with pytest.raises(PreferenceError,match='invalid_fit_provenance'):predict_set(Stub(),bad,CTX)
