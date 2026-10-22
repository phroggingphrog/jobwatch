import hashlib
import json
import pytest
from jobwatch import users
from pipeline.agentic import baseline,eval_data,evaluate_runs
from pipeline.agentic.contracts import AgenticError
from tests.baseline_support import world, frozen  # noqa:F401


def prepared(frozen):
    record=eval_data.freeze_cases(frozen.ro,frozen.config)
    eval_data.create_split(record.baseline_id)
    return record


def test_offline_reproducible_without_live_profile_or_database_writes(frozen,monkeypatch):
    record=prepared(frozen)
    before=frozen.conn.iterdump();before=list(before)
    first=evaluate_runs.replay(record.baseline_id)
    from jobwatch.candidate import intake
    monkeypatch.setattr(intake,'current_version',lambda *a,**k:(_ for _ in ()).throw(AssertionError('live profile read')))
    second=evaluate_runs.replay(record.baseline_id)
    assert first==second and first['usage']['model_calls']==0
    assert first['ordering']=='provisional' and first['cases']
    assert list(frozen.conn.iterdump())==before
    assert first['metrics']


def test_monitor_never_reads_labels_or_holdout_cases(frozen,monkeypatch):
    record=prepared(frozen);split=eval_data.load_split(record.baseline_id)
    original=baseline._read_verified
    def guard(path,sha):
        assert path.stem not in split['holdout']
        return original(path,sha)
    monkeypatch.setattr(baseline,'_read_verified',guard)
    monkeypatch.setattr(baseline,'read_labels',lambda *a:(_ for _ in ()).throw(AssertionError('label read')))
    result=evaluate_runs.replay(record.baseline_id,labels=False,limit=1)
    assert result['processed']==1 and result['labels_hash'] is None


def test_bounds_and_paid_budget_reject_before_clients(frozen):
    record=prepared(frozen)
    with pytest.raises(AgenticError,match='paid_budget_required'):
        evaluate_runs.replay(record.baseline_id,paid=True)
    with pytest.raises(AgenticError,match='paid_budget_required'):
        evaluate_runs.replay(record.baseline_id,budget_tokens=100)
    values=iter([0,0,301])
    result=evaluate_runs.replay(record.baseline_id,clock=lambda:next(values))
    assert result['stop_reason']=='deadline' and result['processed']==0
    assert result['usage']['model_calls']==0


def test_other_person_cannot_retrieve_frozen_inputs(frozen):
    record=prepared(frozen)
    users.create_user_dirs('friend')
    with users.use('friend'),pytest.raises(AgenticError,match='baseline_not_found'):
        evaluate_runs.replay(record.baseline_id)


def test_relevance_mode_and_judgment_frozen_before_live_changes(frozen,monkeypatch):
    from pipeline.agentic import discovery
    from jobwatch.occupations.plan import search_plan,save_plan
    from jobwatch.candidate.policy import policy_for
    from jobwatch import users
    plan=search_plan(policy_for(users.current()),())
    save_plan(users.current(),plan)
    original_capture=eval_data.capture_case_context
    def capture(conn,config,case):
        return {'relevance':discovery.RelevanceJudgment(posting_id=case.posting_id,
            ad_hash=case.evaluation['run_key']['ad_hash'],plan_hash=plan.plan_hash,
            relevant='no',similarity=.1,matched_hypotheses=(),method='extraction',reason='unrelated',quotes=('Reconcile supplier ledgers',)).model_dump(mode='json')}
    monkeypatch.setattr(eval_data,'capture_case_context',capture)
    r=eval_data.freeze_cases(frozen.ro,frozen.config);eval_data.create_split(r.baseline_id)
    first=evaluate_runs.replay(r.baseline_id)
    frozen.config.settings['pipeline']['agentic']['relevance']='on'
    monkeypatch.setattr(discovery,'latest_judgment',lambda *a:(_ for _ in ()).throw(AssertionError('live relevance')))
    monkeypatch.setattr(discovery,'_current_plan',lambda *a:(_ for _ in ()).throw(AssertionError('live plan')))
    second=evaluate_runs.replay(r.baseline_id)
    assert first==second
    assert any(row['current']['rank'] for row in first['cases']), 'shadow must not exclude'


def test_result_tampering_and_holdout_export_audit(frozen):
    record=prepared(frozen)
    result=evaluate_runs.replay(record.baseline_id,partition='holdout',allow_holdout=True)
    with pytest.raises(AgenticError,match='holdout_approval_required'):
        evaluate_runs.load_result(record.baseline_id,result['result_id'])
    assert evaluate_runs.load_result(record.baseline_id,result['result_id'],allow_holdout=True)==result
    folder=baseline._baseline_dir(record.baseline_id)/'evaluation'
    accesses=[json.loads(s) for s in (folder/'holdout_access.jsonl').read_text().splitlines()]
    assert [a['operation'] for a in accesses]==['replay','report']
    path=folder/'runs'/f"{result['result_id']}.json"
    path.write_text('{}')
    with pytest.raises(AgenticError,match='evaluation_corrupt'):
        evaluate_runs.load_result(record.baseline_id,result['result_id'],allow_holdout=True)
