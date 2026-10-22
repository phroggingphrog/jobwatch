"""Current, account-bound shortlist snapshots built without model calls."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3

from jobwatch import users, preference_service
from jobwatch.candidate import intake
from jobwatch.candidate.contracts import digest, content_hash
from jobwatch.candidate._private_io import read_regular_file
from jobwatch.candidate.policy import policy_for
from jobwatch.preferences import PreferenceStore, PreferenceError
from jobwatch.preferences.features import versions
from pipeline.agentic import service, discovery, ranking
from pipeline.agentic.persistence import latest_result

MEANING = ('Labels and order describe evidence fit and, when personalised, learned preference among '
           'alternatives; they are not hiring probability or approval to apply.')


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _fields(config):
    from jobwatch.occupations.hypotheses import cached_hypotheses
    return cached_hypotheses(users.current(),config=config) or ()


def _focus_hypotheses(approved, fields):
    """Only existing semantic links to confirmed focus facts establish priority."""
    facts={f.get('id') for f in approved.get('facts',()) if isinstance(f,dict)
           and f.get('section')=='career_focus' and f.get('basis')=='evidence'}
    return {h.id for h in fields if facts.intersection(h.supporting_facts)}


def _pin(conn, config):
    """Cheap exact-input fence: no occupational analysis, fetching or schema writes."""
    approved = intake.current_version(users.current())
    bundle = service.snapshot_evidence(service.profile_dir())
    service.verify_evidence_snapshot(bundle)
    cfg = service._config(config)
    from jobwatch.candidate.analysis import STRUCTURAL_VERSION
    from pipeline.agentic.matching import MATCHING_VERSION
    from pipeline.agentic.baseline import current_gate_version
    from jobwatch.outcomes.readiness import response_time_readiness
    reference = cfg.get('occupation_reference_path') or str(Path(__file__).parents[2] / 'jobwatch/candidate/data/occupation-reference.json')
    references = {}
    for name, path in (('reference',reference), ('mappings',cfg.get('occupation_mappings_path'))):
        if path:
            references[name] = content_hash(read_regular_file(Path(path),64 * 1024 * 1024))
    tables = _tables(conn)
    catalog = []
    ids = [r[0] for r in conn.execute('SELECT DISTINCT posting_id FROM agentic_runs ORDER BY posting_id')] if 'agentic_runs' in tables else []
    for pid in ids:
        posting = service._posting(conn,pid)
        captured = service._capture(conn,pid) if posting else None
        # last_seen is operational bookkeeping, not a ranking feature.
        if posting:
            posting.pop('last_seen_at',None)
        result = latest_result(conn,pid,parse=frozenset({'evaluation','candidate'}))
        if result:
            result.pop('candidate',None)  # verified above; its immutable hash already fences identity
        live = bool(captured and service.observation_current(service.latest_observation(conn,pid),
            posting_id=pid,url=captured[0]['url'],ad_hash=content_hash(captured[1].encode())))
        catalog.append((pid,posting,content_hash(captured[1].encode()) if captured else None,
                        captured[2] if captured else None,live,result))
    preferences = {}
    for table, columns in (('preference_sets','id,context_hash,payload_hash,holdout'),
                           ('preference_picks','set_id,selected,request_id'),
                           ('preference_fits','id,context_hash,dataset_hash,created_at')):
        if table in tables:
            preferences[table] = [tuple(r) for r in conn.execute(f'SELECT {columns} FROM {table} ORDER BY 1')]
    relevance = [tuple(r) for r in conn.execute('SELECT posting_id,ad_hash,plan_hash,mode,judgment_json FROM posting_relevance ORDER BY posting_id,ad_hash,plan_hash')] if 'posting_relevance' in tables else []
    _, plan = discovery._current_plan(users.current())
    return digest(dict(person=users.current(),approved=approved,evidence=bundle.bundle_hash,
        references=references,runtime=cfg,discovery=discovery.settings(config),
        implementation=service.IMPLEMENTATION_VERSION,rubric=service.RUBRIC_VERSION,
        structural=STRUCTURAL_VERSION,matching=MATCHING_VERSION,
        location=service.LOCATION_REFERENCE_HASH,gate=current_gate_version(),
        response_readiness=response_time_readiness(conn),
        rules=content_hash(Path(ranking.__file__).read_bytes()),versions=versions(),
        catalog=catalog,preferences=preferences,relevance=relevance,
        plan=plan.model_dump(mode='json') if plan else None,
        fields=[h.model_dump(mode='json') for h in _fields(config)]))


def _latest(conn):
    if 'shortlists' not in _tables(conn):
        return None
    row=conn.execute('SELECT shortlist_id,built_at,input_hash,summary_json FROM shortlists '
                     'WHERE person=? ORDER BY built_at DESC,rowid DESC LIMIT 1',(users.current(),)).fetchone()
    return dict(zip(('shortlist_id','built_at','input_hash','summary_json'),row)) if row else None


def _empty(status):
    return dict(status=status,entries=[],total=0,labels={label:0 for label in
        ('stronger_match','stretch','needs_clarification')},meaning=MEANING)


def _current_relevance(conn,row,plan):
    value=discovery.latest_judgment(conn,row.posting_id)
    if not value or not plan or value.ad_hash != row.key.ad_hash or value.plan_hash != plan.plan_hash:
        return None
    return value


def _preference_utilities(store, alternatives, identity):
    """Combine absolute utilities in bounded calls under one unchanged fit."""
    from jobwatch.preferences.model import predict_utilities
    fit_id=None
    utilities={}
    if not alternatives:
        raise PreferenceError('invalid_alternative_count')
    for start in range(0,len(alternatives),100):
        batch=alternatives[start:start+100]
        predicted=predict_utilities(store,batch,identity)
        current_fit=predicted.get('fit_id')
        if (not isinstance(current_fit,str) or not current_fit
                or (fit_id is not None and current_fit!=fit_id)
                or predicted.get('context_hash')!=identity):
            raise PreferenceError('invalid_fit_provenance')
        fit_id=current_fit
        values=predicted['alternatives']
        expected={a['posting_id'] for a in batch}
        if len(values)!=len(expected) or {v['posting_id'] for v in values}!=expected:
            raise PreferenceError('invalid_posterior')
        for value in values:
            mean=value['utility']['mean']
            key=str(value['posting_id'])
            if type(mean) not in (float,int) or not math.isfinite(mean) or key in utilities:
                raise PreferenceError('invalid_posterior')
            utilities[key]=mean
    return fit_id,utilities


def build_shortlist(conn, config):
    """Database-only assessment projection. Never modifies approvals or applications."""
    approved=intake.current_version(users.current())
    dp=policy_for(users.current(),approved=approved) if approved else None
    if dp is None or intake.discovery_scope(users.current()) is None:
        return []
    before=_pin(conn,config)
    if digest(intake.current_version(users.current()))!=digest(approved):
        raise PreferenceError('snapshot_changed')
    identity,bundle,policy,runs=preference_service.current_runs(conn,config)
    if any(digest(row.approved)!=digest(approved) for row in runs):
        raise PreferenceError('snapshot_changed')
    store=PreferenceStore(conn)
    state=store.status(identity)
    _,plan=discovery._current_plan(users.current())
    mode=discovery.settings(config)['relevance']
    focus_ids=_focus_hypotheses(approved,_fields(config)) if dp.focus else set()
    by_id={}; scores=[]; excluded=Counter()
    present={r.posting_id for r in runs}
    for pid, in conn.execute('SELECT DISTINCT posting_id FROM agentic_runs') if 'agentic_runs' in _tables(conn) else ():
        if pid not in present:
            post=service._posting(conn,pid)
            excluded['closed' if post and post.get('closed_at') else 'not_current']+=1
    for row in runs:
        status=ranking.candidate_status(row.decision.route,row.decision.reason)
        if status is None:
            excluded[row.decision.reason]+=1
            continue
        cov=ranking.coverage(row.evaluation)
        relevance=_current_relevance(conn,row,plan)
        reason=ranking.exclusion_reason(cov,relevance if mode=='on' else None)
        if reason:
            excluded[reason]+=1
            continue
        label=ranking.label_for(cov,relevance,dp,held=status=='held')
        explained=ranking.explain(row.evaluation,cov,label,policy=dp,relevance=relevance,
                                 approved_facts=approved.get('facts',()))
        key=str(row.posting_id)
        by_id[key]=(row,cov,label,explained)
        scores.append(ranking.Scored(key,cov,getattr(relevance,'relevant',None),label,
            similarity=getattr(relevance,'similarity',0.),
            focus_match=bool(relevance and focus_ids.intersection(relevance.matched_hypotheses)),
            unresolved=tuple(explained['unresolved']),posting_id=row.posting_id))
    utilities=None; fit_id=None
    if scores and state['status']=='valid':
        _,alternatives=preference_service.pool(conn,config,statuses=('eligible','held'))
        alternatives=[a for a in alternatives if str(a['posting_id']) in by_id]
        try:
            fit_id,utilities=_preference_utilities(store,alternatives,identity)
            if not all(s.case_id in utilities for s in scores):
                utilities=None
        except (ValueError,KeyError,TypeError):
            utilities=None
            fit_id=None
    ranked=ranking.rank_candidates(scores,strategy=dp.strategy,utilities=utilities,
        answered=state['n_choices'],minimum=state['minimum_train']+state['minimum_holdout'])
    stamp=datetime.now(timezone.utc).isoformat()
    entries=[]
    for item in ranked[:100]:
        row,cov,label,explained=by_id[item.case_id]
        entries.append(dict(entry_id='',shortlist_id='',posting_id=row.posting_id,
            run_key=row.key.value,profile_version=dp.profile_version,label=label,rank=item.rank,
            rank_reason=item.rank_reason,ordering=item.ordering,uncertainty=item.uncertainty,
            **explained,holistic_score=row.evaluation.global_score,created_at='',
            posting={k:row.posting.get(k) for k in ('title','company','location','url','work_type','salary_text')},
            utility=utilities.get(item.case_id) if utilities else None,coverage=cov.model_dump(mode='json'),
            requirements=[dict(**r.model_dump(mode='json'),match=next(m for m in row.evaluation.matches if m.requirement_id==r.id).model_dump(mode='json')) for r in row.evaluation.requirements.requirements]))
    ordering=ranked[0].ordering if ranked else 'provisional'
    from jobwatch.outcomes.readiness import response_time_readiness
    summary=dict(profile_version=dp.profile_version,ordering=ordering,rules_version=ranking.RULES_VERSION,
        score_policy='advisory',total=len(entries),labels=dict(Counter(e['label'] for e in entries)),
        excluded=dict(excluded),open_questions=list(dp.open_questions),meaning=MEANING,
        ordering_basis={'preference':{k:v for k,v in state.items() if k!='fit'},
                        'response_time':response_time_readiness(conn)})
    content=digest(dict(input_hash=before,entries=entries,summary=summary,fit_id=fit_id))
    if conn.in_transaction:
        raise PreferenceError('transaction_active')
    conn.execute('BEGIN IMMEDIATE')
    try:
        if _pin(conn,config)!=before:
            raise PreferenceError('snapshot_changed')
        prior=_latest(conn)
        if prior and json.loads(prior['summary_json']).get('content_hash')==content:
            conn.rollback()
            return latest_entries(conn,config=config)
        ident=digest([content,stamp])[:32]
        summary.update(shortlist_id=ident,built_at=stamp,content_hash=content)
        conn.execute('INSERT INTO shortlists VALUES(?,?,?,?,?,?,?,?,?,?)',
            (ident,users.current(),stamp,dp.profile_version,ordering,ranking.RULES_VERSION,fit_id,content,before,json.dumps(summary)))
        result=[]
        for entry in entries:
            entry.update(entry_id=digest([ident,entry['posting_id']])[:32],shortlist_id=ident,created_at=stamp)
            value=ranking.ShortlistEntry.model_validate(entry)
            conn.execute('INSERT INTO shortlist_entries VALUES(?,?,?,?,?,?)',
                (value.entry_id,ident,value.posting_id,value.rank,value.label,value.model_dump_json()))
            result.append(value)
        if _pin(conn,config)!=before:
            raise PreferenceError('snapshot_changed')
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return result


def load_latest(conn, *, config, label=None, limit=20, offset=0):
    if intake.discovery_scope(users.current()) is None:
        return _empty('no_confirmed_profile')
    row=_latest(conn)
    if row is None:
        return _empty('not_built')
    try:
        pin=_pin(conn,config)
        if pin!=row['input_hash']:
            return _empty('stale')
        sql='SELECT payload_json FROM shortlist_entries WHERE shortlist_id=?'
        args=[row['shortlist_id']]
        if label is not None:
            sql+=' AND label=?'; args.append(label)
        total=conn.execute(sql.replace('payload_json','COUNT(*)'),args).fetchone()[0]
        records=conn.execute(sql+' ORDER BY rank LIMIT ? OFFSET ?',(*args,limit,offset)).fetchall()
        entries=[ranking.ShortlistEntry.model_validate_json(r[0]).model_dump(mode='json') for r in records]
        if _pin(conn,config)!=pin:
            return _empty('stale')
        return dict(json.loads(row['summary_json']),status='ok',total=total,entries=entries)
    except (ValueError,OSError,sqlite3.Error):
        return _empty('stale')


def latest_entries(conn, *, config):
    return [ranking.ShortlistEntry.model_validate(e) for e in load_latest(conn,config=config,limit=100)['entries']]


def load_entry(conn,posting_id,*,config):
    return next((e for e in latest_entries(conn,config=config) if e.posting_id==posting_id),None)


def record_impressions(conn,entries,surface,*,now=None):
    at=now or datetime.now(timezone.utc)
    before=conn.total_changes
    for entry in entries:
        value=entry if isinstance(entry,dict) else entry.model_dump(mode='json')
        conn.execute('INSERT OR IGNORE INTO shortlist_impressions('
            'shortlist_id,entry_id,posting_id,rank,ordering,probability,shown_at,surface,shown_day) '
            'SELECT ?,?,?,?,?,NULL,?,?,? WHERE EXISTS(SELECT 1 FROM shortlists WHERE shortlist_id=? AND person=?)',
            (value['shortlist_id'],value['entry_id'],value['posting_id'],value['rank'],value['ordering'],
             at.isoformat(),surface,at.date().isoformat(),value['shortlist_id'],users.current()))
    return conn.total_changes-before
