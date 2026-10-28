"""Person-bound selection approval and durable preparation outbox. Never Submit."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
import uuid
import time

from jobwatch import users, preference_service
from jobwatch.candidate import intake
from jobwatch.candidate.contracts import digest
from pipeline.agentic import feedback, shortlist, service
from pipeline.agentic.api_store import APIStore, Conflict


class SelectionError(ValueError):
    def __init__(self,code):
        self.code=code
        super().__init__(code)


def _now():
    return datetime.now(timezone.utc).isoformat()


def status(conn,ident):
    row=conn.execute('SELECT * FROM selection_requests WHERE person=? AND id=?',(users.current(),ident)).fetchone()
    if row is None:
        raise SelectionError('not_found')
    names=[v[1] for v in conn.execute('PRAGMA table_info(selection_requests)')]
    result=dict(zip(names,row))
    result['result']=json.loads(result.pop('result_json')) if result.get('result_json') else None
    result.pop('result_json',None)
    manifest=json.loads(result.pop('manifest_json'))
    result.update(posting_ids=manifest['request']['posting_ids'],authorises='preparation_only')
    return result


def preview(conn,config,*,posting_ids,expected_entry_ids,expected_run_keys):
    if (type(posting_ids) is not list or not 1<=len(posting_ids)<=10
            or any(type(pid) is not int or pid<=0 for pid in posting_ids)
            or len(set(posting_ids))!=len(posting_ids)
            or type(expected_entry_ids) is not dict or type(expected_run_keys) is not dict):
        raise SelectionError('invalid_request')
    expected={str(pid) for pid in posting_ids}
    if set(expected_entry_ids)!=expected or set(expected_run_keys)!=expected:
        raise SelectionError('invalid_request')
    before=shortlist._pin(conn,config)
    _,_,_,runs=preference_service.current_runs(conn,config)
    eligible={r.posting_id for r in runs if (r.decision.route,r.decision.reason)==('draft','eligible')}
    entries=[]
    for pid in posting_ids:
        entry=shortlist.load_entry(conn,pid,config=config)
        if (entry is None or pid not in eligible or entry.entry_id!=expected_entry_ids[str(pid)]
                or entry.run_key!=expected_run_keys[str(pid)]):
            raise SelectionError('inputs_changed')
        entries.append(entry.model_dump(mode='json'))
    if shortlist._pin(conn,config)!=before:
        raise SelectionError('inputs_changed')
    return dict(person=users.current(),request=dict(posting_ids=posting_ids,
        expected_entry_ids=expected_entry_ids,expected_run_keys=expected_run_keys),
        input_context=before,entries=entries,profile_hash=digest(intake.current_version(users.current())),
        preparation_hash=_preparation_hash(config,runs,posting_ids),
        display_context=shortlist._pin(conn,config,preparation=True),
        authorises='preparation_only')


def _preparation_hash(config,runs,posting_ids):
    """Operational preparation progress cannot invalidate its own approved inputs."""
    from pathlib import Path
    from pipeline.agentic import ranking
    selected={r.posting_id:r for r in runs}
    if not set(posting_ids)<=set(selected):
        raise SelectionError('inputs_changed')
    return digest(dict(person=users.current(),approved=intake.current_version(users.current()),
        config=service._config(config),ranking=digest(Path(ranking.__file__).read_text()),
        jobs=[dict(posting_id=pid,key=selected[pid].key.value,
                   posting={k:v for k,v in selected[pid].posting.items() if k!='last_seen_at'},
                   evaluation=selected[pid].evaluation.model_dump(mode='json')) for pid in posting_ids]))


def request(conn,config,*,posting_ids,expected_entry_ids,expected_run_keys,request_id,actor,source='api'):
    if actor!='person':
        raise SelectionError('person_required')
    if source not in ('api','chat') or not isinstance(request_id,str) or not request_id.strip() or len(request_id)>200:
        raise SelectionError('invalid_request')
    payload=dict(posting_ids=posting_ids,expected_entry_ids=expected_entry_ids,expected_run_keys=expected_run_keys)
    if conn.in_transaction:
        raise SelectionError('transaction_active')
    conn.execute('BEGIN IMMEDIATE')
    try:
        previous=conn.execute('SELECT id,manifest_json FROM selection_requests WHERE person=? AND request_key=?',
                              (users.current(),request_id)).fetchone()
        if previous:
            if json.loads(previous[1])['request']!=payload:
                raise SelectionError('idempotency_conflict')
            conn.rollback()
            return status(conn,previous[0])
        manifest=preview(conn,config,**payload)
        ident,stamp=uuid.uuid4().hex,_now()
        conn.execute('INSERT INTO selection_requests '
            '(id,person,request_key,input_hash,manifest_json,state,run_id,error,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (ident,users.current(),request_id,digest(manifest),json.dumps(manifest,sort_keys=True),
             'pending_dispatch',None,None,stamp,stamp))
        for entry in manifest['entries']:
            feedback.append_event(conn,kind='select',request_id='selection:'+ident+':'+str(entry['posting_id']),
                actor='person',source=source,posting_id=entry['posting_id'],entry_id=entry['entry_id'],
                run_key=entry['run_key'],profile_version=entry['profile_version'],detail={'selection_id':ident})
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return status(conn,ident)


def _manifest(conn,config,row):
    if datetime.now(timezone.utc)-datetime.fromisoformat(row['created_at'])>=timedelta(hours=24):
        raise SelectionError('approval_expired')
    value=json.loads(conn.execute('SELECT manifest_json FROM selection_requests WHERE person=? AND id=?',
                                 (users.current(),row['id'])).fetchone()[0])
    _,_,_,runs=preference_service.current_runs(conn,config)
    selected=[r for r in runs if r.posting_id in row['posting_ids']]
    if (digest(value)!=row['input_hash'] or intake.discovery_scope(users.current()) is None
            or any((r.decision.route,r.decision.reason)!=('draft','eligible') for r in selected)
            or set(row['posting_ids'])&feedback.rejected_posting_ids(conn)
            or shortlist._pin(conn,config,preparation=True)!=value['display_context']
            or _preparation_hash(config,runs,row['posting_ids'])!=value['preparation_hash']):
        raise SelectionError('inputs_changed')
    return value


def _mark_queued(conn,ident,run_id):
    conn.execute("UPDATE selection_requests SET state='queued',run_id=?,updated_at=? WHERE person=? AND id=? AND state='pending_dispatch'",
                 (run_id,_now(),users.current(),ident))


def dispatch_pending(conn,config,*,limit=10):
    """Bounded unpaid dispatch; jobs transaction serialises cancellation with enqueue."""
    if type(limit) is not int or not 1<=limit<=10 or conn.in_transaction:
        raise SelectionError('invalid_request')
    count=0
    ids=[r[0] for r in conn.execute("SELECT id FROM selection_requests WHERE person=? AND state='pending_dispatch' ORDER BY created_at,id LIMIT ?",
                                  (users.current(),limit))]
    for ident in ids:
        conn.execute('BEGIN IMMEDIATE')
        try:
            row=status(conn,ident)
            if row['state']!='pending_dispatch':
                conn.rollback(); continue
            try:
                _manifest(conn,config,row)
            except SelectionError as exc:
                conn.execute("UPDATE selection_requests SET state='failed',error=?,updated_at=? WHERE person=? AND id=?",
                             (exc.code,_now(),users.current(),ident))
                conn.commit(); continue
            from pipeline.agentic.chat import skill_version
            try:
                with APIStore(users.current()) as store:
                    run_id=store.enqueue_selection(ident,{'selection_id':ident,'manifest_hash':row['input_hash']},skill_version())
            except Conflict as exc:
                if exc.code=='queue_full':
                    conn.rollback(); continue
                raise
            _mark_queued(conn,ident,run_id)
            conn.commit()
            count+=1
        except BaseException:
            conn.rollback()
            raise
    return count


def cancel(conn,ident,*,actor):
    if actor!='person':
        raise SelectionError('person_required')
    if conn.in_transaction:
        raise SelectionError('transaction_active')
    conn.execute('BEGIN IMMEDIATE')
    try:
        row=status(conn,ident)
        if row['state'] not in ('completed','failed','cancelled'):
            if row['run_id']:
                with APIStore(users.current()) as store:
                    store.cancel(row['run_id'])
            conn.execute("UPDATE selection_requests SET state='cancelled',updated_at=? WHERE person=? AND id=?",(_now(),users.current(),ident))
        conn.commit()
    except BaseException:
        conn.rollback(); raise
    return status(conn,ident)


def execute(conn,config,ident,manifest_hash,run_id,*,llm=None,llm_factory=None):
    """Called only by authenticated worker, with the persisted queue identity."""
    from pipeline.agentic import execution
    with intake._locked(users.current(),'preparation.lock'):
        row=status(conn,ident)
        if row['run_id']!=run_id or row['input_hash']!=manifest_hash:
            raise SelectionError('selection_not_queued')
        if row['state']=='completed' and row['result'] is not None:
            return row['result']
        if row['state'] not in ('queued','running'):
            raise SelectionError('selection_not_queued')
        manifest=_manifest(conn,config,row)
        cfg=service._config(config)
        llm=llm or (llm_factory() if llm_factory else service.configured_llm(config))
        for name in ('worker_model','evaluator_model','reviewer_model','answer_model'):
            execution.require_route(llm,cfg[name])
        active=execution.current()
        if active:
            active.check()
        changed=conn.execute("UPDATE selection_requests SET state='running',updated_at=? WHERE person=? AND id=? AND state IN ('queued','running')",
                             (_now(),users.current(),ident)).rowcount
        if not changed:
            conn.rollback()
            raise SelectionError('selection_not_queued')
        conn.commit()
        summary=service.agentic_batch_run(manifest['request']['posting_ids'],config,conn,
            batch_id='selection-'+ident,expected_run_keys={int(k):v for k,v in manifest['request']['expected_run_keys'].items()},
            max_seconds=max(0,active.deadline-time.monotonic()) if active else None,
            llm=llm,llm_drafter=llm,llm_reviewer=llm,operation='prepare')
        from pipeline.agentic.persistence import latest_result
        deferred={d['posting_id']:d for d in summary.get('deferred',[])}
        outcomes=[]
        for pid in manifest['request']['posting_ids']:
            if pid in deferred:
                outcomes.append(dict(status='deferred',run_key=manifest['request']['expected_run_keys'][str(pid)],**deferred[pid]))
            else:
                result=latest_result(conn,pid,parse=frozenset())
                outcomes.append(dict(posting_id=pid,run_key=result['run_key'] if result else None,
                                     status=result['status'] if result else 'deferred',reason=result['reason'] if result else 'not_run'))
        result=dict(status='complete',selection_id=ident,summary=summary,outcomes=outcomes)
        completed=conn.execute("UPDATE selection_requests SET state='completed',result_json=?,updated_at=? WHERE person=? AND id=? AND state='running'",
                              (json.dumps(result,sort_keys=True,allow_nan=False),_now(),users.current(),ident)).rowcount
        conn.commit()
        if not completed:
            raise SelectionError('selection_not_queued')
        return result


def finish_error(conn,ident,code):
    """Reflect worker terminal states without changing the immutable approval."""
    if code in ('worker_interrupted','person_busy'):
        return
    state='cancelled' if code=='cancelled' else 'failed'
    conn.execute("UPDATE selection_requests SET state=?,error=?,updated_at=? WHERE person=? AND id=? AND state IN ('queued','running')",
                 (state,code,_now(),users.current(),ident))
    conn.commit()


def reconcile(conn, *, limit=10, run_id=None):
    """Recover terminal queue/cancellation commits independently of dispatch."""
    if type(limit) is not int or not 1<=limit<=500 or conn.in_transaction:
        raise SelectionError('invalid_request')
    sql="SELECT id,run_id FROM selection_requests WHERE person=? AND run_id IS NOT NULL AND state IN ('queued','running')"
    args=[users.current()]
    if run_id is not None:
        if not isinstance(run_id,str) or not run_id:
            raise SelectionError('invalid_request')
        sql+=' AND run_id=?'; args.append(run_id)
    rows=conn.execute(sql+' ORDER BY updated_at,id LIMIT ?',(*args,limit)).fetchall()
    changed=0
    if not rows:
        return changed
    # APIStore reads occur before taking a jobs write transaction. A cancelled
    # run is terminal; an interrupted run retains the existing approval/budgets.
    with APIStore(users.current()) as store:
        terminal=[]
        for ident,run_id in rows:
            try:
                run=store.raw_run(run_id)
            except KeyError:
                continue
            if run['state'] in ('cancelled','failed','completed'):
                terminal.append((ident,run['state'],run['error']))
    with conn:
        # Rotate inspected nonterminal rows too, so interrupted older work cannot
        # indefinitely hide a later terminal queue commit from this bounded scan.
        for ident,_ in rows:
            conn.execute("UPDATE selection_requests SET updated_at=? WHERE person=? AND id=? AND state IN ('queued','running')",
                         (_now(),users.current(),ident))
        for ident,state,error in terminal:
            changed+=conn.execute("UPDATE selection_requests SET state=?,error=?,updated_at=? WHERE person=? AND id=? AND state IN ('queued','running')",
                                  (state,error,_now(),users.current(),ident)).rowcount
    return changed
