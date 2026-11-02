"""Private, replayable follow-up drafts; ledger budgets precede every model call."""
from __future__ import annotations

from datetime import UTC, datetime
import json
import math
import time
import uuid

from jobwatch.util import adtext as adtext
from jobwatch import ledger
from jobwatch import users
from jobwatch.candidate import approved
from jobwatch.candidate.contracts import digest
from jobwatch.candidate.evidence import verify_evidence_snapshot
from jobwatch.followup.events import application_cadence, history, _events, FollowupEventError
from pipeline.agentic.contracts import AgenticError, parse_budget_checkpoint_json
from pipeline.agentic.followup import (CRITERIA, FollowupDraft, compose_followup, snapshot_hash, validate_proposal)
from pipeline.agentic.runtime import BatchBudget, JobBudget, validate_model_payload
from pipeline.agentic.service import _config, configured_llm, enabled


def _approved_bundle():
    return approved.evidence(users.current())


def capture(conn, application_id, bundle, *, now=None, channel="email"):
    bundle = bundle or _approved_bundle()
    if channel not in {'email','linkedin'}:raise AgenticError('invalid_followup_channel')
    row = conn.execute('SELECT * FROM applications WHERE id=?',(application_id,)).fetchone()
    if row is None:
        raise AgenticError('application_missing')
    cadence = application_cadence(conn, application_id, now=now)
    if not cadence.draft_allowed:
        raise AgenticError('followup_not_due')
    posting = dict(conn.execute('SELECT * FROM postings WHERE id=?',(row['posting_id'],)).fetchone())
    text, kind = adtext.local_text(conn, posting)
    if kind != 'full':
        raise AgenticError('followup_ad_incomplete')
    h = history(conn, application_id, now=now)
    confirmed = [{'id':e['id'],'action':e['action'],'occurred_at':e['when'].isoformat(),
                  'channel':e['detail'].get('channel')} for e in _events(conn, application_id)]
    application = {'application_id':application_id,'posting_id':row['posting_id'],
        'title':posting['title'],'company':posting['company'], 'url':posting['url'],
        'status':row['status'],'applied_on':h.applied_on.isoformat(),
        'channel':channel,'kind':cadence.kind,'sent_count':cadence.sent_count,'history':confirmed,
        'owner_notes':row['notes'] or ''}
    verify_evidence_snapshot(bundle)
    return application, text, snapshot_hash(application,text,bundle)


def _payload(row):
    try:
        value=json.loads(row['detail_json'])
        if type(value) is not dict:raise ValueError
        if value.get('status') not in {'running','held','ready'}:raise ValueError
        deadline=value.get('deadline')
        if type(deadline) not in (int,float) or not math.isfinite(deadline) or deadline<=0:raise ValueError
        return value
    except (ValueError,TypeError):
        raise AgenticError('invalid_followup_artifact') from None


def _rows(conn, application_id):
    return conn.execute("SELECT * FROM application_events WHERE application_id=? AND kind='followup_draft' AND actor='jobwatch' ORDER BY id DESC",(application_id,)).fetchall()


def load_draft(conn, application_id, *, bundle=None, now=None, channel="email"):
    bundle = bundle or _approved_bundle()
    application, text, identity = capture(conn,application_id,bundle,now=now,channel=channel)
    for row in _rows(conn,application_id):
        value=_payload(row)
        if value.get('snapshot_hash') != identity:continue
        if value.get('status') != 'ready':
            status=value.get('status','held')
            if status=='running' and value.get('deadline',0)<time.time():status='held'
            return {'status':status,'reason':value.get('reason'),'draft':None}
        draft=validate_model_payload(FollowupDraft,value.get('draft'))
        if draft.snapshot_hash!=identity or draft.evidence_hash!=bundle.bundle_hash or \
           draft.review.draft_hash!=draft.proposal.draft_hash or draft.review.verdict!='approve' or \
           set(draft.review.criteria)!=set(CRITERIA) or not all(draft.review.criteria.values()):
            raise AgenticError('invalid_followup_artifact')
        validate_proposal(draft.proposal,application,text,bundle)
        return {'status':'ready','reason':None,'draft':draft}
    return {'status':'missing','reason':None,'draft':None}


def generate(conn, application_id, config, *, bundle=None, writer=None, reviewer=None, now=None, channel="email", retry=False):
    if not enabled(config):raise AgenticError('agentic_disabled')
    cfg=_config(config)
    live_profile = bundle is None
    bundle=bundle or _approved_bundle()
    application,text,identity=capture(conn,application_id,bundle,now=now,channel=channel)
    # Snapshot identity scopes retries. Never reset an unknown prior reservation
    # merely because the worker restarted or the owner clicked twice.
    if conn.in_transaction:raise AgenticError('transaction_already_active')
    conn.execute('BEGIN IMMEDIATE')
    checkpoint=None
    attempt=uuid.uuid4().hex
    try:
        event=None
        deadline=time.time()+min(cfg['job_seconds'],cfg['batch_seconds'])
        for row in _rows(conn,application_id):
            prior=_payload(row)
            if prior.get('snapshot_hash')!=identity:continue
            expired=prior['status']=='running' and prior['deadline']<time.time()
            if not retry or (prior['status']!='held' and not expired):
                conn.commit()
                return load_draft(conn,application_id,bundle=bundle,now=now,channel=channel)
            # An explicit owner retry renews time only. All prior charges,
            # unknown reservations, failures and role turns remain consumed.
            if prior.get('checkpoint') is not None:
                checkpoint=parse_budget_checkpoint_json(json.dumps(prior['checkpoint']))
                if checkpoint.run_key!=identity:raise AgenticError('invalid_followup_artifact')
                checkpoint=checkpoint.model_copy(update={'job_deadline':deadline,'batch_deadline':deadline})
            value=dict(prior,status='running',deadline=deadline,attempt=attempt,reason=None,
                       retry_count=prior.get('retry_count',0)+1,
                       checkpoint=checkpoint.model_dump(mode='json') if checkpoint else None)
            event=ledger.upsert(conn,'applications','application_events',
                {'id':row['id'],'detail_json':json.dumps(value)},commit=False)
            break
        if event is None:
            value={'snapshot_hash':identity,'status':'running','deadline':deadline,'checkpoint':None,
                   'attempt':attempt,'retry_count':0,'token_ceiling':min(cfg['job_token_ceiling'],cfg['batch_token_ceiling'])}
            event=ledger.upsert(conn,'applications','application_events',{'application_id':application_id,
                'at':datetime.now(UTC).isoformat(),'kind':'followup_draft','actor':'jobwatch',
                'source':'followup-draft:'+uuid.uuid4().hex,'detail_json':json.dumps(value)},commit=False)
        conn.commit()
    except BaseException:
        conn.rollback();raise

    def save():
        # Fence a late worker after an expired attempt has been explicitly retried.
        conn.execute('BEGIN IMMEDIATE')
        try:
            current=_payload(conn.execute('SELECT * FROM application_events WHERE id=?',(event['id'],)).fetchone())
            if current.get('attempt')!=attempt:raise AgenticError('followup_attempt_replaced')
            ledger.upsert(conn,'applications','application_events',{'id':event['id'],'detail_json':json.dumps(value)},commit=False)
            conn.commit()
        except BaseException:
            conn.rollback();raise

    def persist(cp, *, expected_revision, **kwargs):
        old=value.get('checkpoint')
        if (old['revision'] if old else 0)!=expected_revision:
            raise AgenticError('followup_checkpoint_conflict')
        value['checkpoint']=cp.model_dump(mode='json')
        save()

    ceiling=checkpoint.batch_token_ceiling if checkpoint else value.get('token_ceiling',cfg['job_token_ceiling'])
    batch=BatchBudget(checkpoint.batch_id if checkpoint else 'followup-'+uuid.uuid4().hex,token_ceiling=ceiling,deadline=deadline)
    budget=JobBudget.restore(checkpoint,batch=batch,persist=persist) if checkpoint else JobBudget(identity,batch,token_ceiling=ceiling,deadline=deadline,persist=persist)
    try:
        prior_drafts=[]
        for row in _rows(conn,application_id):
            prior=_payload(row)
            if prior.get('status')=='ready' and prior.get('draft'):
                old=validate_model_payload(FollowupDraft,prior['draft'])
                prior_drafts.append({'subject':old.proposal.subject,'body':old.proposal.body})
        client=writer or configured_llm(config)
        draft=compose_followup(application,text,bundle,budget,client,reviewer or client,
            writer_model=cfg['worker_model'],reviewer_model=cfg['reviewer_model'],previous_drafts=prior_drafts)
        # Re-read owner events and profile before publishing any accepted draft.
        current_bundle = _approved_bundle() if live_profile else bundle
        if capture(conn,application_id,current_bundle,now=now,channel=channel)[2]!=identity:
            raise AgenticError('followup_snapshot_changed')
        value.update(status='ready',draft=draft.model_dump(mode='json'),reason=None)
        save()
    except Exception as exc:
        value.update(status='held',reason=exc.code if isinstance(exc,AgenticError) else 'followup_generation_failed')
        save()
    return load_draft(conn,application_id,bundle=bundle,now=now,channel=channel)
