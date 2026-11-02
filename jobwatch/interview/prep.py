"""Posting-bound private interview preparation, with durable conservative budgets."""
from __future__ import annotations

import json
import math
import time
import uuid

from jobwatch.util import adtext as adtext
from jobwatch import ledger
from jobwatch import users
from jobwatch.candidate import approved
from jobwatch.candidate.contracts import content_hash, digest
from jobwatch.candidate.evidence import verify_evidence_snapshot
from jobwatch.interview.inputs import load_inputs
from pipeline.agentic.contracts import AgenticError, AgenticEvaluation, parse_budget_checkpoint_json
from pipeline.agentic.interview import InterviewReport, prepare_interview, snapshot_hash, validate_report
from pipeline.agentic.persistence import latest_result
from pipeline.agentic.runtime import BatchBudget, JobBudget, validate_model_payload
from pipeline.agentic.service import _config, _research, configured_llm, enabled



def _approved_bundle():
    return approved.evidence(users.current())


def _run_table(reference):
    if type(reference) is str:return 'interview_subject_runs','subject_id'
    if type(reference) is int:return 'interview_runs','posting_id'
    raise AgenticError('interview_reference_invalid')


def _run_row(conn,reference,identity):
    table,column=_run_table(reference)
    return conn.execute(f'SELECT * FROM {table} WHERE run_key=? AND {column}=?',(identity,reference)).fetchone()


def _save_run(conn,reference,identity,value):
    table,column=_run_table(reference)
    ledger.upsert(conn,'applications',table,{'run_key':identity,column:reference,'detail_json':json.dumps(value)},commit=False)


def _subject_capture(conn,subject_id,bundle,config):
    from jobwatch.interview.subjects import load_subject
    subject=load_subject(conn,subject_id)
    ad=subject['ad']
    context={'subject_id':subject_id,'title':ad.title,'company':ad.company,'url':ad.url,'location':'',
        'application':None,'evaluation':None,'inputs_revision':subject['revision'],
        'jd_source':{'acquisition':ad.acquisition,'source_url':ad.source_url,'acquired_at':ad.acquired_at,'text_hash':ad.text_hash},
        **subject['inputs'].model_dump(mode='json')}
    cfg=_config(config)
    identity=digest({'snapshot':snapshot_hash(context,ad.text,bundle),
        'writer':cfg['worker_model'],'reviewer':cfg['reviewer_model'],'research_enabled':cfg['research_enabled']})
    return context,ad.text,identity

def capture(conn, posting_id, bundle, config):
    bundle = bundle or _approved_bundle()
    verify_evidence_snapshot(bundle)
    if type(posting_id) is str:return _subject_capture(conn,posting_id,bundle,config)
    inputs,revision=load_inputs(conn,posting_id)
    posting=dict(conn.execute('SELECT * FROM postings WHERE id=?',(posting_id,)).fetchone())
    text,kind=adtext.local_text(conn,posting)
    if kind!='full':raise AgenticError('interview_ad_incomplete')
    context={k:posting.get(k) or '' for k in ('title','company','url','location')}
    context.update(inputs.model_dump(mode='json'),inputs_revision=revision)
    app=conn.execute('SELECT id,status,notes FROM applications WHERE posting_id=?',(posting_id,)).fetchone()
    context['application']=dict(app) if app else None
    if app:
        event=conn.execute("SELECT id FROM application_events WHERE application_id=? AND actor='owner' AND kind IN ('status','outcome_decided') AND to_status='interview' AND (from_status IS NULL OR from_status!='interview') ORDER BY id DESC LIMIT 1",(app['id'],)).fetchone()
        context['application']['interview_event_id']=event['id'] if event else None
    result=latest_result(conn,posting_id)
    context['evaluation']=None
    if result and result.get('evaluation'):
        try:
            evaluation=validate_model_payload(AgenticEvaluation,result['evaluation'])
            if (evaluation.run_key.posting_id==posting_id and evaluation.run_key.ad_hash==content_hash(text.encode())
                    and evaluation.run_key.evidence_hash==bundle.bundle_hash):
                context['evaluation']=evaluation.model_dump(mode='json')
        except AgenticError:
            pass
    cfg=_config(config)
    identity=digest({'snapshot':snapshot_hash(context,text,bundle),
        'writer':cfg['worker_model'],'reviewer':cfg['reviewer_model'],'research_enabled':cfg['research_enabled']})
    return context,text,identity


def _payload(row):
    try:
        value=json.loads(row['detail_json'])
        if type(value) is not dict or value.get('status') not in {'queued','running','held','ready'}:raise ValueError
        if value['status']=='queued' and value.get('checkpoint') is not None:raise ValueError
        deadline=value.get('deadline')
        if type(deadline) not in (float,int) or not math.isfinite(deadline) or deadline<=0:raise ValueError
        return value
    except (ValueError,TypeError):
        raise AgenticError('invalid_interview_artifact') from None


def load_report(conn, posting_id, config, *, bundle=None):
    bundle=bundle or _approved_bundle()
    context,text,identity=capture(conn,posting_id,bundle,config)
    row=_run_row(conn,posting_id,identity)
    if row is None:return {'status':'missing','reason':None,'report':None}
    value=_payload(row)
    status=value['status']
    if status=='queued':return {'status':'running','reason':None,'report':None}
    if status=='running' and value['deadline']<time.time():status='held'
    if status!='ready':return {'status':status,'reason':value.get('reason'),'report':None}
    report=validate_report(validate_model_payload(InterviewReport,value.get('report')),context,text,bundle)
    cfg=_config(config)
    if (report.writer_model,report.reviewer_model)!=(cfg['worker_model'],cfg['reviewer_model']):
        raise AgenticError('invalid_interview_artifact')
    return {'status':'ready','reason':None,'report':report}


def generate(conn, posting_id, config, *, bundle=None, writer=None, reviewer=None, retry=False, queued_only=False):
    if not enabled(config):raise AgenticError('agentic_disabled')
    cfg=_config(config)
    live_profile=bundle is None
    bundle=bundle or _approved_bundle()
    context,text,identity=capture(conn,posting_id,bundle,config)
    if conn.in_transaction:raise AgenticError('transaction_already_active')
    attempt=uuid.uuid4().hex
    deadline=time.time()+min(cfg['job_seconds'],cfg['batch_seconds'])
    checkpoint=None
    conn.execute('BEGIN IMMEDIATE')
    try:
        row=_run_row(conn,posting_id,identity)
        if queued_only and (row is None or _payload(row)['status']!='queued'):
            conn.commit()
            return load_report(conn,posting_id,config,bundle=bundle)
        if row:
            prior=_payload(row)
            expired=prior['status']=='running' and prior['deadline']<time.time()
            if prior['status']!='queued' and (not retry or (prior['status']!='held' and not expired)):
                conn.commit()
                return load_report(conn,posting_id,config,bundle=bundle)
            if prior.get('checkpoint') is not None:
                checkpoint=parse_budget_checkpoint_json(json.dumps(prior['checkpoint']))
                if checkpoint.run_key!=identity:raise AgenticError('invalid_interview_artifact')
                checkpoint=checkpoint.model_copy(update={'job_deadline':deadline,'batch_deadline':deadline})
            value=dict(prior,status='running',deadline=deadline,attempt=attempt,reason=None,
                retry_count=prior.get('retry_count',0)+(prior['status']!='queued'),checkpoint=checkpoint.model_dump(mode='json') if checkpoint else None)
        else:
            value={'status':'running','deadline':deadline,'attempt':attempt,'checkpoint':None,
                   'token_ceiling':min(cfg['job_token_ceiling'],cfg['batch_token_ceiling']),'retry_count':0,
                   'trigger_event_id':(context.get('application') or {}).get('interview_event_id')}
        _save_run(conn,posting_id,identity,value)
        conn.commit()
    except BaseException:
        conn.rollback();raise

    def save():
        conn.execute('BEGIN IMMEDIATE')
        try:
            current=_payload(_run_row(conn,posting_id,identity))
            if current.get('attempt')!=attempt:raise AgenticError('interview_attempt_replaced')
            _save_run(conn,posting_id,identity,value)
            conn.commit()
        except BaseException:
            conn.rollback();raise

    def persist(cp, *, expected_revision, **kwargs):
        old=value.get('checkpoint')
        if (old['revision'] if old else 0)!=expected_revision:raise AgenticError('interview_checkpoint_conflict')
        value['checkpoint']=cp.model_dump(mode='json')
        save()

    ceiling=checkpoint.batch_token_ceiling if checkpoint else value['token_ceiling']
    batch=BatchBudget(checkpoint.batch_id if checkpoint else 'interview-'+uuid.uuid4().hex,token_ceiling=ceiling,deadline=deadline)
    budget=JobBudget.restore(checkpoint,batch=batch,persist=persist) if checkpoint else JobBudget(identity,batch,token_ceiling=ceiling,deadline=deadline,persist=persist)
    try:
        client=writer or configured_llm(config)
        report=prepare_interview(context,text,bundle,budget,client,reviewer or client,
            research=_research(context,budget,cfg),writer_model=cfg['worker_model'],reviewer_model=cfg['reviewer_model'])
        current_bundle=_approved_bundle() if live_profile else bundle
        if capture(conn,posting_id,current_bundle,config)[2]!=identity:raise AgenticError('interview_snapshot_changed')
        validate_report(report,context,text,current_bundle)
        value.update(status='ready',report=report.model_dump(mode='json'),reason=None)
        save()
    except Exception as exc:
        value.update(status='held',reason=exc.code if isinstance(exc,AgenticError) else 'interview_generation_failed')
        save()
    return load_report(conn,posting_id,config,bundle=bundle)


def should_prepare_after_interview(conn, posting_id, config):
    """Owner-confirmed interview transition may enqueue one current eligible prep."""
    from jobwatch.candidate.contracts import CandidateError
    if not enabled(config):return False
    try:
        bundle=_approved_bundle()
        context,_,identity=capture(conn,posting_id,bundle,config)
        evaluation=context.get('evaluation')
        return bool(context.get('application') and context['application']['status']=='interview'
            and evaluation
            and not conn.execute('SELECT 1 FROM interview_runs WHERE run_key=?',(identity,)).fetchone())
    except (AgenticError,CandidateError):
        return False


def enqueue(conn, posting_id, config):
    """Durably record undispatched intent before acknowledging a prep request."""
    if not enabled(config):raise AgenticError('agentic_disabled')
    cfg=_config(config)
    context,_,identity=capture(conn,posting_id,_approved_bundle(),config)
    if conn.in_transaction:raise AgenticError('transaction_already_active')
    conn.execute('BEGIN IMMEDIATE')
    try:
        row=_run_row(conn,posting_id,identity)
        if row:
            queued=_payload(row)['status']=='queued'
            conn.commit()
            return queued
        value={'status':'queued','deadline':time.time()+min(cfg['job_seconds'],cfg['batch_seconds']),
               'checkpoint':None,'attempt':None,'retry_count':0,
               'token_ceiling':min(cfg['job_token_ceiling'],cfg['batch_token_ceiling']),
               'trigger_event_id':(context.get('application') or {}).get('interview_event_id')}
        _save_run(conn,posting_id,identity,value)
        conn.commit()
        return True
    except BaseException:
        conn.rollback();raise


def queued_posting_ids(conn, config):
    """Recover only undispatched requests and unhandled confirmed transitions.

    A confirmed status event also survives a crash before enqueue. An event that
    already has any attempt is never re-triggered just because its sources changed.
    """
    from jobwatch.candidate.contracts import CandidateError
    if not enabled(config):return ()
    queued=set()
    for row in conn.execute('SELECT * FROM interview_runs').fetchall():
        try:value=_payload(row)
        except AgenticError:continue
        if value['status']!='queued':continue
        try:
            identity=capture(conn,row['posting_id'],_approved_bundle(),config)[2]
        except (AgenticError,CandidateError):identity=None
        if identity==row['run_key']:
            queued.add(row['posting_id']);continue
        conn.execute('BEGIN IMMEDIATE')
        try:
            current=_payload(conn.execute('SELECT * FROM interview_runs WHERE run_key=?',(row['run_key'],)).fetchone())
            if current['status']=='queued':
                current.update(status='held',reason='interview_snapshot_changed')
                ledger.upsert(conn,'applications','interview_runs',{'run_key':row['run_key'],'detail_json':json.dumps(current)},commit=False)
            conn.commit()
        except BaseException:
            conn.rollback();raise
    for app in conn.execute("SELECT posting_id FROM applications WHERE status='interview'").fetchall():
        pid=app['posting_id']
        try:
            context,_,_=capture(conn,pid,_approved_bundle(),config)
            trigger=(context.get('application') or {}).get('interview_event_id')
            evaluation=context.get('evaluation')
            if not trigger or not evaluation:continue
            attempted=any(_payload(row).get('trigger_event_id')==trigger for row in conn.execute(
                'SELECT * FROM interview_runs WHERE posting_id=?',(pid,)).fetchall())
            if not attempted and enqueue(conn,pid,config):queued.add(pid)
        except (AgenticError,CandidateError):continue
    return tuple(sorted(queued))


def is_queued(conn, posting_id, config):
    """Inspect current undispatched intent; never create new work or retry a call."""
    from jobwatch.candidate.contracts import CandidateError
    try:
        identity=capture(conn,posting_id,_approved_bundle(),config)[2]
        row=_run_row(conn,posting_id,identity)
        return bool(row and _payload(row)['status']=='queued')
    except (AgenticError,CandidateError):return False


def queued_subject_ids(conn, config):
    """Recover only explicit, undispatched standalone requests with current sources."""
    from jobwatch.candidate.contracts import CandidateError
    if not enabled(config):return ()
    queued=[]
    for row in conn.execute('SELECT * FROM interview_subject_runs').fetchall():
        try:value=_payload(row)
        except AgenticError:continue
        if value['status']!='queued':continue
        subject_id=row['subject_id']
        try:identity=capture(conn,subject_id,_approved_bundle(),config)[2]
        except (AgenticError,CandidateError):identity=None
        if identity==row['run_key']:
            queued.append(subject_id);continue
        conn.execute('BEGIN IMMEDIATE')
        try:
            current=_payload(_run_row(conn,subject_id,row['run_key']))
            if current['status']=='queued':
                current.update(status='held',reason='interview_snapshot_changed')
                _save_run(conn,subject_id,row['run_key'],current)
            conn.commit()
        except BaseException:
            conn.rollback();raise
    return tuple(sorted(set(queued)))


def matching_posting(conn,url,config,*,bundle=None,title=None,company=None):
    """Read-only reuse of a current source-validated report before URL retrieval."""
    from jobwatch.models import canonical_url,fold
    from jobwatch.candidate.contracts import CandidateError
    exact=[];named=[]
    for row in conn.execute('SELECT id,url,title,company FROM postings').fetchall():
        if canonical_url(row['url'])==canonical_url(url):exact.append(row['id'])
        elif title and company and fold(row['title'])==fold(title) and fold(row['company'] or '')==fold(company):named.append(row['id'])
    for candidates in (exact,named):
        valid=[]
        for pid in candidates:
            try:
                result=latest_result(conn,pid)
                if not result or not result.get('evaluation'):continue
                bundle=bundle or _approved_bundle()
                context,_,_=capture(conn,pid,bundle,config)
            except (AgenticError,CandidateError):continue
            if context.get('evaluation') is not None:valid.append(pid)
        if len(valid)==1:return valid[0]
        if len(valid)>1:return None
    return None
