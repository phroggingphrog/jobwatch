"""Real local sampler acceptance; opt in because this spends CPU, never model tokens."""
import os
import random
import sqlite3
import pytest
from jobwatch.preferences import PreferenceStore, fit_store, PreferenceError
from jobwatch.preferences.features import NAMES

@pytest.mark.skipif(os.environ.get('JOBWATCH_TEST_R')!='1',reason='set JOBWATCH_TEST_R=1 for local four-chain synthetic fit')
def test_real_four_chain_synthetic_fit(tmp_path):
    store=PreferenceStore(sqlite3.connect(tmp_path/'synthetic.sqlite'),origin='synthetic')
    rng=random.Random(917)
    ctx='a'*64
    for s in range(25):
        coverage=[.0,.5,1.];rng.shuffle(coverage)
        rows=[]
        for a,cov in enumerate(coverage):
            f=dict.fromkeys(NAMES);f['coverage']=cov
            rows.append({'posting_id':s*3+a+1,'title':'Synthetic vacancy','company':'Synthetic employer',
                'family':'accounting','features':f,'eligible':True,'current':True,
                **{k:'b'*64 for k in ('ad_hash','profile_hash','run_key','evaluation_hash')}})
        choice=store.create_set(rows,ctx)
        store.pick(choice['id'],None if s==0 else rows[coverage.index(1.)]['posting_id'],actor='owner',request_id=str(s))
    summary=fit_store(store,tmp_path/'fits',ctx,iterations=30000,timeout=600)
    assert summary['origin']=='synthetic'
    assert summary['chains']==4
    assert summary['n_train']==20 and summary['n_holdout']==5
    assert summary['holdout_log_score']>summary['prior_log_score']
    assert summary['parameters']['beta[5]']['mean']>2
    assert summary['gate']['accepted'],summary['gate']
    assert store.status(ctx)['status']=='synthetic_valid'
    print({'artifact_root':str(tmp_path),'train':summary['n_train'],'holdout':summary['n_holdout'],
           'posterior_log_score':summary['holdout_log_score'],'prior_log_score':summary['prior_log_score'],
           'max_rhat':max(p['rhat'] for p in summary['parameters'].values()),
           'min_ess':min(p['ess'] for p in summary['parameters'].values()),
           'max_mcse_ratio':max(p['mcse_ratio'] for p in summary['parameters'].values())})
