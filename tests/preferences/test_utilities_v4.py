"""Synthetic, in-memory posterior arithmetic; never export as owner training data."""
import copy
import sqlite3

import pytest
from jobwatch.preferences import PreferenceError, PreferenceStore
from jobwatch.preferences.features import NAMES, FAMILIES
from tests.preferences.test_core import CTX, alternative, populate, good_summary


def posterior():
    b=[0.]*(len(NAMES)*2); b[NAMES.index('coverage')]=2
    return {'id':'arithmetic-fixture','context_hash':CTX,'origin':'owner','profile_hash':'b'*64,
         'draws':{'beta':[b,b],'alpha':[[0.]*len(FAMILIES),[0.]*len(FAMILIES)]},
         'preprocessing':{'centers':[0.]*len(NAMES),'scales':[1.]*len(NAMES),
                          'missing_rates':[0.]*len(NAMES)}}


class Stub:
    def __init__(self, fit=None, status='valid'):
        self.fit=posterior() if fit is None else fit
        self.state=status
    def status(self, ctx): return {'status':self.state,'fit':self.fit}


def test_arbitrary_utility_intervals_do_not_invent_choice_probabilities():
    from jobwatch.preferences.model import predict_utilities
    rows=[alternative(i) for i in range(1,9)]
    for i,row in enumerate(rows): row['features']['coverage']=i/10
    out=predict_utilities(Stub(),rows,CTX)
    assert out['fit_id']=='arithmetic-fixture'
    assert len(out['alternatives'])==8
    assert out['alternatives'][-1]['utility']['mean']==pytest.approx(1.4)
    assert out['alternatives'][-1]['utility']['hdi_low']==pytest.approx(1.4)
    assert out['ranking']==list(range(8,0,-1))
    assert 'none_probability' not in out
    assert all('choice_probability' not in row for row in out['alternatives'])
    # Each utility is invariant to the pool it is requested with.
    one=predict_utilities(Stub(),rows[-1:],CTX)
    assert one['alternatives'][0]==out['alternatives'][-1]


@pytest.mark.parametrize('state',['synthetic_valid','rejected','stale','no_data','untrained'])
def test_utilities_fail_closed_without_valid_genuine_fit(state):
    from jobwatch.preferences.model import predict_utilities
    with pytest.raises(PreferenceError,match='valid_current_fit_required'):
        predict_utilities(Stub(status=state),[alternative(1)],CTX)


@pytest.mark.parametrize('change',[
    {'origin':'synthetic'}, {'profile_hash':'c'*64}, {'context_hash':'c'*64},
])
def test_utilities_reject_fit_provenance(change):
    from jobwatch.preferences.model import predict_utilities
    with pytest.raises(PreferenceError,match='invalid_fit_provenance'):
        predict_utilities(Stub({**posterior(),**change}),[alternative(1)],CTX)


@pytest.mark.parametrize('change',[
    {'draws':{'beta':[[0]],'alpha':[[0]]}}, {'draws':{'beta':[],'alpha':[]}},
    {'preprocessing':{}}, {'preprocessing':{'centers':[0]*17,'scales':[0]*17,'missing_rates':[0]*17}},
])
def test_utilities_reject_invalid_posterior_and_transform(change):
    from jobwatch.preferences.model import predict_utilities
    with pytest.raises(PreferenceError,match='invalid_posterior'):
        predict_utilities(Stub({**posterior(),**change}),[alternative(1)],CTX)


def test_explicit_migration_split_provenance_and_overlap():
    store=PreferenceStore(sqlite3.connect(':memory:'),origin='synthetic')
    rows=[alternative(i) for i in (1,2,3)]
    item=store.create_set(rows,CTX,holdout=True,migrated_from='historical-id')
    assert item['holdout'] is True and item['migrated_from']=='historical-id'
    assert store.create_set(rows,CTX,holdout=True,migrated_from='historical-id')['id']==item['id']
    with pytest.raises(PreferenceError,match='split_overlap'):
        store.create_set([alternative(i) for i in (1,4,5)],CTX,holdout=False,migrated_from='other-id')
    with pytest.raises(PreferenceError,match='split_overlap'):
        store.create_set(rows,CTX,holdout=False,migrated_from='historical-id')
    assert len(store.list_sets())==1
    for kwargs in ({'holdout':1},{'migrated_from':''},{'migrated_from':12}):
        with pytest.raises(PreferenceError): store.create_set(rows,CTX,**kwargs)
