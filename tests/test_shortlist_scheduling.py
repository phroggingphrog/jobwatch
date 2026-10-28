"""Completed assessment reuse must not starve changed inputs or retry work."""
import pytest
from tests.baseline_support import world, frozen
from pipeline.agentic import service, decision_log
from pipeline.agentic.persistence import latest_result
from jobwatch.util import adtext as adtext


def inputs(frozen,pid=42):
    cfg=service._config(frozen.config);policy=service.default_policy()
    captured=service._capture(frozen.conn,pid)
    reference,mappings=service.load_inputs(frozen.bundle,cfg)
    structural=service.analyse_candidate(frozen.bundle,reference,mappings,policy)
    key=service._run_key(pid,captured,frozen.bundle,policy,cfg,(reference,mappings),structural)
    return captured,key,service.decision_policy_for(frozen.config)


def test_only_unchanged_completed_evaluation_with_current_liveness_is_skipped(frozen,monkeypatch):
    captured,key,policy=inputs(frozen)
    assert service._evaluation_current(frozen.conn,42,captured,key,policy)
    monkeypatch.setattr(service,'observation_current',lambda *a,**k:False)
    assert not service._evaluation_current(frozen.conn,42,captured,key,policy)


def test_retry_reasons_and_changed_policy_are_not_skipped(frozen,monkeypatch):
    captured,key,policy=inputs(frozen)
    monkeypatch.setattr(service,'latest_result',lambda *a,**k:{'run_key':key.value,'reason':'model_unavailable'})
    assert not service._evaluation_current(frozen.conn,42,captured,key,policy)
    monkeypatch.setattr(service,'latest_result',lambda *a,**k:{'run_key':key.value,'reason':'evaluation_complete'})
    monkeypatch.setattr(decision_log,'latest',lambda *a,**k:{'policy_hash':'changed'})
    assert not service._evaluation_current(frozen.conn,42,captured,key,policy)


def test_spent_budget_still_refreshes_shortlist_without_paid_work(frozen,monkeypatch):
    monkeypatch.setattr(service,'_spent_today',lambda *a:(999999,999999999))
    result=service.after_collect(frozen.conn,frozen.config,max_seconds=60)
    assert result['deferred']=='daily_budget' and result['shortlist']['entries']==3


def test_shortlist_failure_does_not_fail_collection(frozen,monkeypatch):
    monkeypatch.setattr(service,'_spent_today',lambda *a:(999999,999999999))
    from pipeline.agentic import shortlist
    monkeypatch.setattr(shortlist,'build_shortlist',lambda *a,**k:(_ for _ in ()).throw(ValueError('synthetic')))
    result=service.after_collect(frozen.conn,frozen.config,max_seconds=60)
    assert result['deferred']=='daily_budget' and result['shortlist']=={'error':'shortlist_failed'}
