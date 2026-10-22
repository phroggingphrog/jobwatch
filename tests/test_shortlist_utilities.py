"""Bounded prediction calls must preserve full-pool ordering and one valid fit."""
import pytest
from jobwatch.preferences import model, PreferenceError
from pipeline.agentic import shortlist


def test_more_than_one_prediction_batch_covers_the_entire_pool(monkeypatch):
    calls=[]
    def predict(store,alternatives,identity):
        assert len(alternatives)<=100
        calls.append(len(alternatives))
        return {'fit_id':'fit-one','context_hash':identity,'alternatives':[
            {'posting_id':a['posting_id'],'utility':{'mean':float(a['posting_id'])}} for a in alternatives]}
    monkeypatch.setattr(model,'predict_utilities',predict)
    fit,utilities=shortlist._preference_utilities(object(),[{'posting_id':i} for i in range(1,202)],'context')
    assert calls==[100,100,1] and fit=='fit-one' and len(utilities)==201 and utilities['201']==201.


@pytest.mark.parametrize('failure',['changed_fit','changed_context','missing','nonfinite'])
def test_any_inconsistent_batch_refuses_the_combined_utilities(monkeypatch,failure):
    count=0
    def predict(store,alternatives,identity):
        nonlocal count
        count+=1
        rows=[{'posting_id':a['posting_id'],'utility':{'mean':float(a['posting_id'])}} for a in alternatives]
        if count==2:
            if failure=='missing':rows=[]
            if failure=='nonfinite':rows[0]['utility']['mean']=float('nan')
        return {'fit_id':'other' if count==2 and failure=='changed_fit' else 'same',
                'context_hash':'other' if count==2 and failure=='changed_context' else identity,
                'alternatives':rows}
    monkeypatch.setattr(model,'predict_utilities',predict)
    with pytest.raises(ValueError):
        shortlist._preference_utilities(object(),[{'posting_id':i} for i in range(1,102)],'context')
from dataclasses import replace
import pytest
from tests.baseline_support import world,frozen
from jobwatch import preference_service
from jobwatch.preferences import PreferenceStore
from jobwatch.preferences.features import NAMES,FAMILIES
from pipeline.agentic import shortlist

@pytest.mark.parametrize('size',[100,101])
def test_valid_genuine_fit_applies_when_current_pool_exceeds_display_cap(frozen,monkeypatch,size):
    identity,bundle,policy,actual=preference_service.current_runs(frozen.conn,frozen.config)
    _,alts=preference_service.pool(frozen.conn,frozen.config)
    row=actual[0]
    rows=[];alternatives=[]
    for pid in range(1,size+1):
        key=row.key.model_copy(update={'posting_id':pid})
        evaluation=row.evaluation.model_copy(update={'run_key':key})
        rows.append(replace(row,posting_id=pid,key=key,evaluation=evaluation,posting={**row.posting,'id':pid}))
        alternatives.append({**alts[0],'posting_id':pid,'run_key':key.value})
    monkeypatch.setattr(preference_service,'current_runs',lambda *a:(identity,bundle,policy,rows))
    monkeypatch.setattr(preference_service,'pool',lambda *a,**k:(identity,alternatives))
    original=PreferenceStore.status
    fit={'id':'synthetic-math-only','origin':'owner','context_hash':identity,'profile_hash':bundle.bundle_hash,
        'draws':{'beta':[[0.]*(len(NAMES)*2)]*2,'alpha':[[0.]*len(FAMILIES)]*2},
        'preprocessing':{'names':list(NAMES),'centers':[0.]*len(NAMES),'scales':[1.]*len(NAMES),'missing_rates':[0.]*len(NAMES)}}
    monkeypatch.setattr(PreferenceStore,'status',lambda self,context=None:{**original(self,context),'status':'valid','fit':fit})
    entries=shortlist.build_shortlist(frozen.conn,frozen.config)
    assert len(entries)==100
    assert all(entry.ordering=='personalised' for entry in entries), {entry.ordering for entry in entries}
