"""Explicit paid/fit paths exercised with synthetic local transports only."""
from jobwatch.util.llm import LLM
from pipeline.agentic import eval_data,evaluate_runs,eval_fit
from pipeline.agentic.service import agentic_batch_run
from tests.baseline_support import world, frozen  # noqa:F401
from tests.test_agentic_service import SyntheticGateway


def test_paid_replay_uses_actual_canonical_runtime_and_budget(world):
    conn,config,bundle,add=world
    for pid,company in ((42,'Synthetic Alpha'),(43,'Synthetic Beta'),(44,'Synthetic Gamma')):
        add(pid,company)
    gateway=SyntheticGateway(bundle)
    llm=LLM(transport=gateway,keys=['synthetic'])
    agentic_batch_run([42,43,44],config,conn,evidence_bundle=bundle,llm=llm,operation='evaluate')
    conn.commit()
    record=eval_data.freeze_cases(conn,config);eval_data.create_split(record.baseline_id)
    before=list(conn.iterdump());calls=len(gateway.calls)
    result=evaluate_runs.replay(record.baseline_id,paid=True,budget_tokens=1,llm=llm)
    assert result['status']=='bounded' and result['stop_reason']=='budget'
    assert len(gateway.calls)==calls and result['usage']['model_calls']==0
    paid=evaluate_runs.replay(record.baseline_id,paid=True,budget_tokens=250000,llm=llm)
    assert paid['status']=='complete' and paid['usage']['model_calls']>0
    assert list(conn.iterdump())==before


def test_explicit_fit_insufficient_data_never_starts_sampler(frozen,monkeypatch):
    r=eval_data.freeze_cases(frozen.ro,frozen.config);eval_data.create_split(r.baseline_id)
    monkeypatch.setattr('jobwatch.preferences.model.fit_store',lambda *a,**k:(_ for _ in ()).throw(AssertionError('sampler')))
    result=evaluate_runs.replay(r.baseline_id,fit=True,labels=False)
    assert result['fit']['status']=='insufficient_data'
    assert result['usage']['model_calls']==0


def test_fit_uses_canonical_gates_and_preserves_original_choices(frozen,monkeypatch,tmp_path):
    import copy
    import sqlite3
    from jobwatch.preferences import PreferenceStore
    from tests.preferences.test_core import populate,CTX
    store=PreferenceStore(sqlite3.connect(':memory:'),origin='owner')
    sets=populate(store);before=copy.deepcopy(sets)
    r=eval_data.freeze_cases(frozen.ro,frozen.config);eval_data.create_split(r.baseline_id)
    monkeypatch.setattr(eval_fit,'eligible_choices',lambda *a:(sets,CTX))
    def fit_spy(memory,out,identity,*,timeout):
        from jobwatch.preferences.model import prepare_data
        payload=prepare_data(memory.dataset(identity))
        assert sum(s['holdout'] for s in payload['sets'])==5
        assert 1<=timeout<=7
        assert not hasattr(memory,'conn')
        summary={'id':'synthetic-fit','gate':{'accepted':False}}
        memory.save_fit(summary)
        return summary
    monkeypatch.setattr('jobwatch.preferences.model.fit_store',fit_spy)
    result=eval_fit.fit_development(r.baseline_id,[],{},seconds=7)
    assert result['status']=='rejected' and result['activation']=='evaluation_only'
    assert store.dataset(CTX)==before and store.latest_fit(CTX) is None


def test_frozen_choices_skip_holdout_without_opening_choice_and_keep_originals(frozen,monkeypatch):
    from jobwatch import preference_service
    from jobwatch.preferences import PreferenceStore
    identity,alternatives=preference_service.pool(frozen.conn,frozen.config,statuses=('eligible','held'))
    store=PreferenceStore(frozen.conn)
    choice=store.create_set(alternatives,identity,holdout=True)
    store.pick(choice['id'],alternatives[0]['posting_id'],actor='owner',request_id='genuine-synthetic-human')
    before=store.dataset(identity)
    r=eval_data.freeze_cases(frozen.ro,frozen.config);eval_data.create_split(r.baseline_id)
    inputs=eval_data.load_inputs(r.baseline_id)
    assert len(inputs['choice_index'])==1
    _,cases=eval_data.load_partition(r.baseline_id,'development')
    original=eval_data.baseline._read_verified
    def guard(path,sha):
        assert path.parent.name!='choices', 'choice crossing holdout must not be opened'
        return original(path,sha)
    monkeypatch.setattr(eval_data.baseline,'_read_verified',guard)
    assert eval_fit.eligible_choices(r.baseline_id,cases,inputs)==([],None)
    assert store.dataset(identity)==before and before[0]['holdout'] is True
