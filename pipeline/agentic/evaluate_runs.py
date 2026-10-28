"""Frozen canonical gate/ranking replay. No production state writes or default models."""
from __future__ import annotations

import json
import math
import time
from types import SimpleNamespace

from jobwatch.candidate.contracts import TargetPolicy, digest
from jobwatch.candidate.evidence import bundle_from_contents
from jobwatch.candidate.policy import policy_for
from pipeline.agentic import baseline, eval_data, ranking, service
from pipeline.agentic.contracts import AgenticError, AgenticEvaluation, RunKey
from pipeline.agentic.runtime import validate_model_payload

# Monitoring maxima. Enforced here, not only in the CLI, so a library caller gets the bound the docs promise.
MONITOR_LIMIT = 500
MONITOR_SECONDS = 300

LIMITATIONS = ['frozen_historical_sample','synthetic_success_not_recommendation_quality',
    'exposure_and_selection_bias','no_recorded_propensities','pending_outcomes_censored',
    'citation_checks_not_independent_qualification','provisional_only_no_personalised_quality']


def _usage(value):
    return {name:value.get(name) if type(value.get(name)) in (int,float) and math.isfinite(value[name])
            and value[name]>=0 else None for name in ('charged_tokens','actual_tokens','latency_seconds')}


def _bundle(case):
    return bundle_from_contents({k:v.encode('utf-8') for k,v in case.snapshot['contents'].items()})


def _citation_failures(evaluation,bundle,ad_text):
    from jobwatch.candidate.assessment import verify_candidate_citations
    from pipeline.agentic.evaluator import _exact_ad_citation
    failed=0
    for requirement in evaluation.requirements.requirements:
        if requirement.jd_signal:
            try:
                _exact_ad_citation(requirement.jd_signal,ad_text,evaluation.run_key.ad_hash)
            except (ValueError,AgenticError):
                failed+=1
    for match in evaluation.matches:
        citations=list(match.evidence)
        if match.judgment:
            citations.extend(match.judgment.contradiction_evidence)
        for citation in citations:
            try:
                if citation.source_id in ('ad','jd'):
                    _exact_ad_citation(citation,ad_text,evaluation.run_key.ad_hash)
                else:
                    verify_candidate_citations((citation,),bundle)
            except (ValueError,AgenticError):
                failed+=1
    return failed


def replay_case(case,record,inputs,approved,dp,*,evaluation=None,usage=None):
    evaluation=evaluation or validate_model_payload(AgenticEvaluation,case.evaluation)
    run_key=RunKey.model_validate(case.snapshot['run_key'])
    if case.run_key!=run_key.value or evaluation.run_key!=run_key:
        raise AgenticError('frozen_run_mismatch')
    bundle=_bundle(case)
    posting=case.snapshot['posting']
    ad=case.snapshot['full_ad']
    decision=service.gate_current(evaluation,posting=posting,ad_text=ad,decision_policy=dp,
        policy=TargetPolicy.model_validate(record.policy),captured_complete=case.snapshot['text_kind']=='full',
        expected_run_key=run_key,evidence_bundle=bundle)
    cov=ranking.coverage(evaluation)
    raw=case.evaluation_context.get('relevance')
    relevance=None
    if raw:
        from pipeline.agentic.discovery import RelevanceJudgment
        relevance=RelevanceJudgment.model_validate(raw)
        plan=inputs.get('plan')
        if not plan or relevance.plan_hash!=plan['plan_hash'] or relevance.ad_hash!=run_key.ad_hash:
            raise AgenticError('frozen_relevance_mismatch')
    reason=ranking.exclusion_reason(cov,relevance if inputs['discovery']['relevance']=='on' else None)
    status=ranking.candidate_status(decision.route,decision.reason)
    label=None; explanation=None; score=None
    if not posting.get('closed_at') and status and not reason:
        label=ranking.label_for(cov,relevance,dp,held=status=='held')
        explanation=ranking.explain(evaluation,cov,label,policy=dp,relevance=relevance,
                                     approved_facts=approved.get('facts',()))
        from pipeline.agentic.shortlist import _focus_hypotheses
        fields=[SimpleNamespace(**h) for h in inputs['fields']]
        focus=_focus_hypotheses(approved,fields)
        score=ranking.Scored(case.case_id,cov,getattr(relevance,'relevant',None),label,
            similarity=getattr(relevance,'similarity',0),
            focus_match=bool(relevance and focus.intersection(relevance.matched_hypotheses)),posting_id=case.posting_id)
    return dict(status='replayed',route=decision.route,reason='closed' if posting.get('closed_at') else reason or decision.reason,
        label=label,rank=None,coverage=dict(weighted=cov.weighted,weighted_upper=cov.weighted_upper,
        unknown=cov.unknown,contradicted=cov.contradicted,mandatory_unmet=len(cov.mandatory_unmet)),
        citation_failures=_citation_failures(evaluation,bundle,ad),mandatory_conflicts=len(cov.mandatory_conflicts),
        unresolved=len(explanation['unresolved']) if explanation else 0,
        uncertainty_disclosed=bool(explanation['unresolved']) if explanation else None,
        usage=usage or dict(charged_tokens=0,actual_tokens=0,latency_seconds=None),error=None),score


def _paid_evaluation(case,inputs,dp,ex,batch,llm):
    from pipeline.agentic.evaluator import evaluate_job
    from pipeline.agentic.execution import require_route
    from pipeline.agentic.runtime import JobBudget
    from jobwatch.candidate.assessment import CandidateAssessment
    from jobwatch.candidate.contracts import AnalysisResult
    cfg=inputs['runtime']
    require_route(llm,cfg['evaluator_model'])
    candidate=case.candidate
    if candidate is None and case.evaluation['run_key'].get('candidate_hash'):
        raise AgenticError('frozen_candidate_unavailable')
    if candidate is not None:
        candidate=(CandidateAssessment if 'structural_analysis' in candidate else AnalysisResult).model_validate(candidate)
    budget=JobBudget(case.run_key,batch,token_ceiling=min(cfg['job_token_ceiling'],ex.token_ceiling))
    before=ex.usage();start=time.monotonic()
    try:
        result=evaluate_job(RunKey.model_validate(case.snapshot['run_key']),case.snapshot['full_ad'],budget,llm,
            evidence_bundle=_bundle(case),candidate_analysis=candidate,model=cfg['evaluator_model'],
            research=None,commute_km=service.commute_km_of(dp,case.snapshot['posting'].get('location')),
            model_insights=case.model_insights,embedding_model=cfg.get('embedding_model'),decision_policy=dp)
        after=ex.usage()
        return result,dict(charged_tokens=after['charged_tokens']-before['charged_tokens'],
            actual_tokens=None if after['unknown_usage_calls']>before['unknown_usage_calls'] else after['actual_tokens']-before['actual_tokens'],
            latency_seconds=round(time.monotonic()-start,6))
    finally:
        batch.release(budget)


def replay(baseline_id, *, partition='development', allow_holdout=False, limit=500, seconds=300,
           paid=False,budget_tokens=None,fit=False,labels=True,monitor=False,llm=None,clock=time.monotonic):
    if (type(limit) is not int or not 1<=limit<=10000 or type(seconds) not in (int,float)
            or not math.isfinite(seconds) or not 0<seconds<=3600):
        raise AgenticError('invalid_evaluation_limits')
    if monitor:
        if limit>MONITOR_LIMIT or seconds>MONITOR_SECONDS:
            raise AgenticError('monitor_limits_exceeded')
        labels=False                       # monitoring never reads the human-label log

    if type(paid) is not bool or (paid and (type(budget_tokens) is not int or budget_tokens<=0)) or (not paid and budget_tokens is not None):
        raise AgenticError('paid_budget_required')
    if fit and partition!='development':
        raise AgenticError('development_fit_only')
    start=clock();deadline=start+seconds
    record=eval_data.record_for(baseline_id)
    split=eval_data.load_split(baseline_id)
    ids=eval_data.partition_ids(baseline_id,partition,allow_holdout=allow_holdout)
    inputs=eval_data.load_inputs(baseline_id)
    approved=baseline.frozen_approved(baseline_id)
    dp=policy_for(record.person,approved=approved)
    if dp is None:
        raise AgenticError('frozen_policy_unavailable')
    source=eval_data.code_hash()
    from pipeline.agentic.execution import Execution, use
    from pipeline.agentic.runtime import BatchBudget, RuntimeErrorSafe
    ex=Execution('evaluation-'+split['split_hash'][:16],seconds=seconds,token_ceiling=budget_tokens or 1,max_calls=10000)
    batch=BatchBudget(ex.run_id,token_ceiling=budget_tokens or 1,deadline=time.time()+max(.001,deadline-clock()))
    items=[];scores=[];cache={};stop=None;loaded=[]
    with baseline.pinned_profile(baseline_id),use(ex):
        for cid in ids:
            if clock()>=deadline:
                stop='deadline';break
            if len(items)>=limit:
                stop='case_limit';break
            case=eval_data._case(record,cid,cache)
            loaded.append(case)
            current=None;score=None
            before=ex.usage()
            try:
                evaluated=usage=None
                if paid:
                    if llm is None:
                        from jobwatch.llm import LLM, load_keys
                        from jobwatch.model_choice import own_key
                        index=0 if own_key() else inputs['runtime']['credential_index']
                        keys=load_keys()
                        if index>=len(keys):
                            raise AgenticError('credential_unavailable')
                        llm=LLM(keys=[keys[index]])
                    evaluated,usage=_paid_evaluation(case,inputs,dp,ex,batch,llm)
                current,score=replay_case(case,record,inputs,approved,dp,evaluation=evaluated,usage=usage)
            except (ValueError,RuntimeErrorSafe) as exc:
                # Store only fixed safe codes, never nested validation messages or model text.
                code=getattr(exc,'code','invalid_frozen_case')
                code=code if code in ('deadline_exceeded','invocation_budget_exhausted','budget_exhausted',
                    'batch_budget_exhausted','job_budget_exhausted','token_limit','frozen_candidate_unavailable',
                    'credential_unavailable','model_not_allowed','gateway_not_allowed') else 'replay_unavailable'
                after=ex.usage()
                current=dict(status='deferred',route=None,reason=None,label=None,rank=None,coverage={},
                    citation_failures=0,mandatory_conflicts=0,unresolved=0,uncertainty_disclosed=None,
                    usage=dict(charged_tokens=after['charged_tokens']-before['charged_tokens'],
                        actual_tokens=None if after['unknown_usage_calls']>before['unknown_usage_calls'] else after['actual_tokens']-before['actual_tokens'],
                        latency_seconds=None),error=code)
                if 'budget' in code or code=='token_limit':
                    stop='budget'
                elif code=='deadline_exceeded':
                    stop='deadline'
            items.append(dict(case_id=cid,posting_id=case.posting_id,
                baseline=dict(route=case.decision.get('route'),reason=case.decision.get('reason'),
                    score=case.decision.get('global_score'),rank=None,usage=_usage(case.usage)),current=current))
            if score is not None:
                scores.append(score)
            if stop:
                break
        for ranked in ranking.rank_candidates(scores,strategy=dp.strategy):
            next(row for row in items if row['case_id']==ranked.case_id)['current']['rank']=ranked.rank
        old=sorted((row for row in items if row['baseline']['route']=='draft'),
            key=lambda row:(-(row['baseline']['score'] or 0),row['posting_id'],row['case_id']))
        for pos,row in enumerate(old,1):
            row['baseline']['rank']=pos
        fit_result={'status':'not_requested'}
        if fit:
            from pipeline.agentic.eval_fit import fit_development
            if clock()<deadline-1:
                fit_result=fit_development(baseline_id,loaded,inputs,seconds=min(600,deadline-clock()))
            else:
                fit_result={'status':'deadline'}
        label_map={}
        if labels:
            label_map={cid:label for cid,label in baseline.latest_labels(baseline.read_labels(baseline_id)).items() if cid in ids}
    if eval_data.code_hash()!=source:
        raise AgenticError('evaluation_source_changed')
    complete=len(items)==len(ids) and all(row['current']['status']=='replayed' for row in items)
    result=dict(version='evaluation-v1',baseline_id=baseline_id,partition=partition,data_hash=split['data_hash'],
        code_hash=source,split_hash=split['split_hash'],inputs_hash=record.evaluation_inputs_sha256,
        labels_hash=digest({k:v.model_dump(mode='json') for k,v in label_map.items()}) if labels else None,
        baseline_gate_version=record.gate_version,ranking_rules_version=ranking.RULES_VERSION,
        ordering='provisional',status='complete' if complete else 'bounded',stop_reason=stop,
        requested=len(ids),processed=len(items),cases=items,usage=ex.usage(),fit=fit_result,
        limitations=LIMITATIONS+(['baseline_uses_revised_gate'] if record.gate_version!=baseline.PRE_REVISION_GATE_VERSION else []))
    from pipeline.agentic.eval_metrics import compute_metrics
    result['metrics']=compute_metrics(result,label_map)
    result['result_id']=digest(result)
    folder=eval_data.private_dir(baseline._baseline_dir(baseline_id)/'evaluation'/'runs')
    with eval_data.locked(folder):
        eval_data.write_once(folder/f"{result['result_id']}.json",result)
        eval_data.write_once(folder/f"{result['result_id']}.index.json",dict(partition=partition))
    return result


def load_result(baseline_id,result_id,*,allow_holdout=False,operation='report'):
    if not baseline._HEX64.fullmatch(result_id):
        raise AgenticError('invalid_evaluation_id')
    # Partition metadata is stored separately so the explicit access check precedes private case output.
    folder=baseline._baseline_dir(baseline_id)/'evaluation'/'runs'
    index_path=folder/f'{result_id}.index.json'
    if any(part.is_symlink() for part in (index_path,*index_path.parents)):
        raise AgenticError('unsafe_evaluation_path')
    try:
        partition=json.loads(index_path.read_bytes())['partition']
    except (OSError,ValueError,KeyError,TypeError):
        raise AgenticError('evaluation_unavailable') from None
    if partition not in ('development','holdout'):
        raise AgenticError('evaluation_corrupt')
    if partition=='holdout':
        eval_data.audit_holdout(baseline_id,operation,allow_holdout=allow_holdout)
    path=folder/f'{result_id}.json'
    if path.is_symlink():
        raise AgenticError('unsafe_evaluation_path')
    try:
        value=json.loads(path.read_bytes())
    except (OSError,ValueError):
        raise AgenticError('evaluation_unavailable') from None
    if digest({k:v for k,v in value.items() if k!='result_id'})!=result_id or value.get('result_id')!=result_id:
        raise AgenticError('evaluation_corrupt')
    split=eval_data.load_split(baseline_id)
    if value.get('data_hash')!=split['data_hash'] or value.get('split_hash')!=split['split_hash']:
        raise AgenticError('evaluation_corrupt')
    if value.get('partition')!=partition:
        raise AgenticError('evaluation_corrupt')
    return value
