"""Bounded human questions and genuine three-job-plus-none comparisons.

Stored prompts retain the exact displayed subject and current-input manifest.
Reads never migrate; only explicit issuance creates canonical preference sets.
Preference writes keep their existing transaction and train/holdout contracts.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from itertools import combinations
import json
import math
import uuid

from jobwatch import users, preference_service
from jobwatch.candidate import intake
from jobwatch.candidate.contracts import digest
from jobwatch.candidate.policy import policy_for
from jobwatch.preferences import PreferenceStore, PreferenceError
from jobwatch.preferences.features import NAMES, family_index, validate_alternatives
from jobwatch.preferences.model import _current_posterior, transform_features
from pipeline.agentic import feedback, service, shortlist

PROMPTS_PER_WEEK = 3
QUESTION_COOLDOWN_DAYS = 30
STATUS = dict(invalid_request=422, person_required=403, prompt_not_found=404,
    prompt_closed=409, comparison_stale=409, prompt_stale=409, feedback_conflict=409,
    transaction_active=409, invalid_configuration=422)


class PromptError(ValueError):
    def __init__(self, code):
        if code not in STATUS:
            raise ValueError('invalid_prompt_error')
        self.code = code
        super().__init__(code)


def _now():
    return datetime.now(timezone.utc)


def _time(value=None):
    value = _now() if value is None else value
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PromptError('invalid_request')
    return value.astimezone(timezone.utc)


def _settings(config):
    raw = service.agentic_settings(config)
    cap = raw.get('prompts_per_week', PROMPTS_PER_WEEK)
    cooldown = raw.get('question_cooldown_days', QUESTION_COOLDOWN_DAYS)
    enabled = raw.get('prompts_enabled', True)
    if (type(cap) is not int or cap < 0 or type(cooldown) is not int or cooldown < 0
            or type(enabled) is not bool):
        raise PromptError('invalid_configuration')
    # Config can reduce issuance and lengthen cooldown, never exceed these caps.
    return min(cap, PROMPTS_PER_WEEK) if enabled else 0, max(cooldown, QUESTION_COOLDOWN_DAYS)


def _pool(conn, config):
    return preference_service.pool(conn, config)


def _preference_store(conn):
    return PreferenceStore(conn)


def _entries(conn, config):
    return shortlist.latest_entries(conn, config=config)


def _snapshot(conn, config):
    approved = intake.current_version(users.current())
    if approved is None:
        return dict(manifest=dict(person=users.current(),context_hash=None,
            approved_hash=digest(None),policy_hash=None),alternatives=[],approved=None,policy=None,entries=[])
    identity, alternatives = _pool(conn, config)
    dismissed = feedback.rejected_posting_ids(conn)
    alternatives = [a for a in alternatives if a['posting_id'] not in dismissed]
    validated = []
    for start in range(0,len(alternatives),100):
        validated.extend(validate_alternatives(alternatives[start:start+100], size=None))
    alternatives = validated
    if len({a['posting_id'] for a in alternatives}) != len(alternatives):
        raise PreferenceError('duplicate_alternative')
    if len({a['profile_hash'] for a in alternatives}) > 1:
        raise PreferenceError('mixed_profiles')
    policy = policy_for(users.current(), approved=approved) if approved else None
    return dict(manifest=dict(person=users.current(), context_hash=identity,
        approved_hash=digest(approved), policy_hash=policy.policy_hash if policy else None),
        alternatives=alternatives, approved=approved, policy=policy,
        entries=_entries(conn, config))


def _entropy(probabilities):
    return -sum(p * math.log(p) for p in probabilities if p > 0.)


def _choices(fit, beta, alpha, alternatives, max_draws):
    if type(max_draws) is not int or not 1 <= max_draws <= 1000:
        raise PreferenceError('invalid_draw_limit')
    x = [transform_features(a['features'], fit['preprocessing']) for a in alternatives]
    rows = []
    for b, a in zip(beta[:max_draws], alpha[:max_draws]):
        utilities = [a[family_index(alt['family'])-1] + sum(v * b[k] for k, v in enumerate(values))
                     for alt, values in zip(alternatives, x)] + [0.]
        if any(not math.isfinite(value) for value in utilities):
            raise PreferenceError('invalid_posterior')
        largest = max(utilities)
        exps = [math.exp(value-largest) for value in utilities]
        total = sum(exps)
        rows.append([value/total for value in exps])
    means = [sum(row[j] for row in rows)/len(rows) for j in range(4)]
    gain = max(0., _entropy(means) - sum(_entropy(row) for row in rows)/len(rows))
    return dict(information_gain=gain, probabilities=means[:3], none_probability=means[3])


def posterior_choices(store, alternatives, context_hash, *, max_draws=1000):
    alternatives = validate_alternatives(alternatives)
    fit, beta, alpha = _current_posterior(store, alternatives, context_hash)
    return _choices(fit, beta, alpha, alternatives, max_draws)


def information_gain(fit, alternatives, *, max_draws=1000):
    """Pure arithmetic for a supplied posterior, with canonical shape validation.

    Issuance uses posterior_choices with the actual store's readiness checks.
    This pure helper alone cannot establish that a stored fit is current/accepted.
    """
    class Value:
        def status(self, context):
            return {'status':'valid', 'fit':fit}
    return posterior_choices(Value(), alternatives, fit.get('context_hash'),
                             max_draws=max_draws)['information_gain']


def cold_start_triple(alternatives):
    if len(alternatives) < 3:
        return None
    alternatives = validate_alternatives(alternatives, size=None)
    ranges = {}
    for name in NAMES:
        known = [a['features'][name] for a in alternatives if a['features'][name] is not None]
        ranges[name] = max(known)-min(known) if known else 0.
    def differences(a, b):
        count = int(family_index(a['family']) != family_index(b['family']))
        for name, width in ranges.items():
            av, bv = a['features'][name], b['features'][name]
            if width > 0 and av is not None and bv is not None and abs(av-bv) >= width/2:
                count += 1
        return count
    best = None
    for triple in combinations(sorted(alternatives, key=lambda a:a['posting_id']), 3):
        counts = [differences(a,b) for a,b in combinations(triple, 2)]
        ids = tuple(a['posting_id'] for a in triple)
        key = (-min(counts), -sum(counts), ids)
        if best is None or key < best[0]:
            best = key, ids
    return best[1] if best and best[0][0] < 0 else None


def _has_prompts(conn):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='feedback_prompts'").fetchone() is not None


def _rows(conn, *, prompt_id=None, opened=False, limit=None):
    if not _has_prompts(conn):
        return []
    sql = 'SELECT * FROM feedback_prompts WHERE person=?'
    args = [users.current()]
    if prompt_id is not None:
        sql += ' AND id=?'; args.append(prompt_id)
    if opened:
        sql += ' AND closed_at IS NULL'
    sql += ' ORDER BY created_at DESC,rowid DESC'
    if limit is not None:
        sql += ' LIMIT ?'; args.append(limit)
    cursor = conn.execute(sql, args)
    names = [col[0] for col in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _get(conn, prompt_id):
    if type(prompt_id) is not str or not prompt_id.strip() or len(prompt_id) > 128:
        raise PromptError('invalid_request')
    rows = _rows(conn, prompt_id=prompt_id)
    if not rows:
        raise PromptError('prompt_not_found')
    return rows[0]


def _body(row):
    return json.loads(row['subject_json'])


def _render(row):
    body = _body(row)
    subject = body['subject']
    return dict(subject, prompt_id=row['id'], set_id=row['set_id'], person=row['person'],
        type=row['kind'], created_at=row['created_at'], closed_at=row['closed_at'],
        closed_reason=row['closed_reason'], subject=subject, subject_digest=digest(subject),
        response=body.get('response'))


def outstanding_prompt(conn):
    rows = _rows(conn, opened=True, limit=1)
    return _render(rows[0]) if rows else None


def list_prompts(conn, *, limit=100):
    if type(limit) is not int or not 1 <= limit <= 200:
        raise PromptError('invalid_request')
    return [_render(row) for row in _rows(conn, limit=limit)]


def prompts_this_week(conn, now=None):
    cutoff = (_time(now)-timedelta(days=7)).isoformat()
    if not _has_prompts(conn):
        return 0
    return conn.execute('SELECT COUNT(*) FROM feedback_prompts WHERE person=? AND created_at>?',
                        (users.current(), cutoff)).fetchone()[0]


@contextmanager
def _transaction(conn):
    if conn.in_transaction:
        raise PromptError('transaction_active')
    conn.execute('BEGIN IMMEDIATE')
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _questions(snapshot):
    policy = snapshot['policy']
    result = [dict(text=text, source='open_question', source_entries=[])
              for text in (policy.open_questions if policy else ()) if isinstance(text,str) and text.strip()]
    counts = Counter()
    entries_by_key = {}
    text_by_key = {}
    for entry in sorted(snapshot['entries'], key=lambda e:(e.rank,e.posting_id))[:10]:
        for text in set(entry.unresolved):
            key = text.strip().casefold()
            if not key:
                continue
            identity = dict(posting_id=entry.posting_id, entry_id=entry.entry_id, run_key=entry.run_key)
            identities = entries_by_key.setdefault(key, [])
            if identity not in identities:
                identities.append(identity)
                counts[key] += 1
            text_by_key[key] = min(text_by_key.get(key, text), text)
    result.extend(dict(text=text_by_key[key], source='shared_unresolved', source_entries=entries_by_key[key])
                  for key in sorted(counts) if counts[key] >= 2)
    for question in result:
        question['subject_key'] = digest([question['source'],question['text'].strip().casefold()])
    return result


def _is_current(row, snapshot):
    subject = _body(row)['subject']
    if subject['manifest'] != snapshot['manifest']:
        return False
    if row['kind'] == 'comparison':
        current = {a['posting_id']:a for a in snapshot['alternatives']}
        return all(current.get(a['posting_id']) == a for a in subject['alternatives'])
    return any(all(q.get(key) == subject.get(key) for key in ('text','source','source_entries','subject_key'))
               for q in _questions(snapshot))


def _close(conn, row, reason, at):
    conn.execute('UPDATE feedback_prompts SET closed_at=?,closed_reason=? WHERE person=? AND id=? AND closed_at IS NULL',
                 (at.isoformat(),reason,users.current(),row['id']))


def _stale(conn, row):
    with _transaction(conn):
        _close(conn, row, 'stale', _time())


def _finish_set(conn, config, row):
    if row['set_id'] is not None:
        return _render(row)
    subject = _body(row)['subject']
    # The prompt reservation is durable before canonical create_set commits. A
    # crash at either side recovers this same prompt/set through canonical hashing.
    item = _preference_store(conn).create_set(subject['alternatives'], row['context_hash'])
    with _transaction(conn):
        current = _get(conn, row['id'])
        if current['closed_at'] is None and not _is_current(current, _snapshot(conn,config)):
            _close(conn, current, 'stale', _time())
        elif current['closed_at'] is None:
            conn.execute('UPDATE feedback_prompts SET set_id=? WHERE person=? AND id=? AND set_id IS NULL',
                         (item['id'],users.current(),row['id']))
    current = _get(conn, row['id'])
    if current['closed_at'] is not None:
        raise PromptError('comparison_stale')
    return _render(current)


def next_prompt(conn, config, *, now=None):
    at = _time(now)
    cap, cooldown = _settings(config)
    if conn.in_transaction:
        raise PromptError('transaction_active')
    if not cap:
        return {'prompt':None, 'reason':'disabled'}
    snapshot = _snapshot(conn,config)
    if snapshot['approved'] is None:
        return {'prompt':None, 'reason':'not_enough_alternatives'}
    opened = _rows(conn, opened=True, limit=1)
    if opened:
        row = opened[0]
        if _is_current(row,snapshot):
            prompt = _finish_set(conn,config,row) if row['kind']=='comparison' else _render(row)
            return {'prompt':prompt, 'reason':None}
        _stale(conn,row)
    if prompts_this_week(conn,at) >= cap:
        return {'prompt':None, 'reason':'rate_limited'}
    store = _preference_store(conn)
    existing = store.list_sets(snapshot['manifest']['context_hash'])
    used = {a['posting_id'] for item in existing for a in item['alternatives']}
    # Only this person's historical prompt subjects contribute cross-context seen ids.
    for old in _rows(conn):
        used.update(a['posting_id'] for a in _body(old)['subject'].get('alternatives',()))
    candidates = sorted((a for a in snapshot['alternatives'] if a['posting_id'] not in used),
                        key=lambda a:a['posting_id'], reverse=True)[:9]
    subject = None
    if len(candidates) >= 3:
        best = None
        try:
            fit,beta,alpha = _current_posterior(store,candidates,snapshot['manifest']['context_hash'])
            for triple in combinations(sorted(candidates,key=lambda a:a['posting_id']),3):
                choices = _choices(fit,beta,alpha,list(triple),1000)
                key = (-choices['information_gain'],tuple(a['posting_id'] for a in triple))
                if best is None or key < best[0]:
                    best = key, list(triple), choices
        except (PreferenceError, ValueError, TypeError, KeyError, OverflowError):
            best = None
        if best:
            selected, probabilities = best[1], best[2]
            basis, ordering = 'information_gain','personalised'
        else:
            ids = cold_start_triple(candidates)
            selected = [next(a for a in candidates if a['posting_id']==pid) for pid in ids] if ids else []
            probabilities = dict(information_gain=None, probabilities=[None]*3,none_probability=None)
            basis, ordering = 'cold_start_disagreement','provisional'
        if selected:
            by_id = {e.posting_id:e for e in snapshot['entries']}
            options = [dict(posting_id=a['posting_id'],title=a['title'],company=a['company'],
                entry_id=by_id[a['posting_id']].entry_id if a['posting_id'] in by_id else None,
                choice_probability=p,display_propensity=None)
                for a,p in zip(selected,probabilities['probabilities'])]
            subject = dict(manifest=snapshot['manifest'], alternatives=selected,options=options,
                basis=basis, ordering=ordering,expected_information_gain=probabilities['information_gain'],
                fit_id=fit['id'] if best else None,
                none_probability=probabilities['none_probability'],
                why=('Posterior disagreement about the choice among these three jobs and none.' if best else
                     'Clear observed feature differences across the candidates; no learned preference weights.'),
                meaning='Choice probabilities describe this displayed set, not hiring or selection propensity.')
            kind = 'comparison'
    if subject is None:
        cutoff = at-timedelta(days=cooldown)
        cooling = {_body(row)['subject'].get('subject_key') for row in _rows(conn)
                   if row['kind']=='question' and row['closed_reason'] in ('answered','dismissed')
                   and datetime.fromisoformat(row['closed_at']) >= cutoff}
        question = next((q for q in _questions(snapshot) if q['subject_key'] not in cooling),None)
        if question:
            subject = dict(question,manifest=snapshot['manifest'],basis=question['source'])
            kind = 'question'
    if subject is None:
        return {'prompt':None, 'reason':'not_enough_alternatives' if len(candidates)<3 else 'nothing_to_ask'}
    with _transaction(conn):
        opened = _rows(conn,opened=True,limit=1)
        if opened:
            row = opened[0]
        elif prompts_this_week(conn,at) >= cap:
            row = None
        else:
            ident = uuid.uuid4().hex
            conn.execute('INSERT INTO feedback_prompts(id,person,kind,subject_json,context_hash,basis,'
                'expected_gain,set_id,profile_version,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (ident,users.current(),kind,json.dumps({'subject':subject},ensure_ascii=False,allow_nan=False),
                 snapshot['manifest']['context_hash'],subject['basis'],subject.get('expected_information_gain'),
                 None,snapshot['approved']['version'] if snapshot['approved'] else None,at.isoformat()))
            row = _get(conn,ident)
        if row and not _is_current(row,_snapshot(conn,config)):
            _close(conn,row,'stale',at)
            row = None
    if row is None:
        return {'prompt':None,'reason':'rate_limited' if prompts_this_week(conn,at)>=cap else 'inputs_changed'}
    return {'prompt':_finish_set(conn,config,row) if row['kind']=='comparison' else _render(row),'reason':None}


def _validate_write(actor, source, request_id):
    if type(actor) is not str or actor != 'person':
        raise PromptError('person_required')
    if (type(source) is not str or source not in ('api','chat') or type(request_id) is not str
            or not request_id.strip() or len(request_id)>128):
        raise PromptError('invalid_request')


def _request(kind, row, request_id, actor, source, payload):
    return dict(kind=kind,prompt_id=row['id'],person=users.current(),request_id=request_id,
                actor=actor,source=source,subject_digest=digest(_body(row)['subject']),**payload)


def _prior_response(conn, request):
    fingerprint = digest(request)
    cursor = conn.execute('SELECT input_hash FROM feedback_events WHERE person=? AND request_id=?',
                           (users.current(),request['request_id']))
    prior = cursor.fetchone()
    if prior:
        if prior[0] != fingerprint:
            raise PromptError('feedback_conflict')
        # The event's own scoped query returns its persisted exact response.
        cursor = conn.execute('SELECT * FROM feedback_events WHERE person=? AND request_id=?',
                              (users.current(),request['request_id']))
        return feedback._event(cursor.fetchone(),cursor)
    for row in _rows(conn):
        response = _body(row).get('response')
        if response and response['request_id']==request['request_id'] and response['input_hash']!=fingerprint:
            raise PromptError('feedback_conflict')
    return None


def _reserve(conn, config, row, request):
    stale = False
    with _transaction(conn):
        current = _get(conn,row['id'])
        _prior_response(conn,request)
        body = _body(current)
        response = body.get('response')
        if response and response['input_hash'] != digest(request):
            raise PromptError('feedback_conflict')
        if current['closed_at'] is not None:
            raise PromptError('prompt_closed')
        if not _is_current(current,_snapshot(conn,config)):
            _close(conn,current,'stale',_time())
            stale = True
        else:
            body['response'] = dict(request_id=request['request_id'],input_hash=digest(request),request=request)
            conn.execute('UPDATE feedback_prompts SET subject_json=? WHERE person=? AND id=?',
                         (json.dumps(body,ensure_ascii=False,allow_nan=False),users.current(),row['id']))
    if stale:
        raise PromptError('comparison_stale' if row['kind']=='comparison' else 'prompt_stale')


def _existing_pick(conn, row, request):
    if row['set_id'] is None:
        return False
    # The prompt belongs to this person; the immutable set must also carry its
    # exact context and alternatives before any recovery can accept its choice.
    store = _preference_store(conn)
    item = next((s for s in store.list_sets(row['context_hash']) if s['id']==row['set_id']),None)
    if item is None or item['alternatives'] != _body(row)['subject']['alternatives']:
        raise PromptError('comparison_stale')
    prior = conn.execute('SELECT selected,request_id FROM preference_picks WHERE set_id=?',(row['set_id'],)).fetchone()
    if prior is None:
        return False
    key = 'prompt:'+digest(request)
    if tuple(prior) != (request['selected'],key):
        raise PromptError('feedback_conflict')
    return True


def _finalize(conn, row, request):
    with _transaction(conn):
        prior = _prior_response(conn,request)
        if prior is not None:
            return prior
        current = _get(conn,row['id'])
        body = _body(current)
        subject = body['subject']
        if body.get('response',{}).get('input_hash') != digest(request):
            raise PromptError('feedback_conflict')
        selected = request.get('selected')
        alternative = next((a for a in subject.get('alternatives',()) if a['posting_id']==selected),None)
        option = next((a for a in subject.get('options',()) if a['posting_id']==selected),None)
        event = feedback.append_event(conn,kind=request['kind'],actor=request['actor'],source=request['source'],
            request_id=request['request_id'],prompt_id=row['id'],posting_id=selected,
            entry_id=option['entry_id'] if option else None,run_key=alternative['run_key'] if alternative else None,
            profile_version=row['profile_version'],
            reason_text=request.get('text','') if len(request.get('text',''))<=2000 else '',
            input_hash=digest(request),
            detail=dict(set_id=row['set_id'],selected=selected,basis=subject['basis'],
                        text=request.get('text'),subject_digest=digest(subject),
                        manifest=subject['manifest'],subject=subject))
        conn.execute('UPDATE feedback_prompts SET closed_at=?,closed_reason=? WHERE person=? AND id=?',
                     (_time().isoformat(),'answered',users.current(),row['id']))
        return event


def answer_comparison(conn, config, prompt_id, selected, *, request_id, actor, source='api'):
    _validate_write(actor,source,request_id)
    if conn.in_transaction:
        raise PromptError('transaction_active')
    if selected is not None and (type(selected) is not int or selected<=0):
        raise PromptError('invalid_request')
    row = _get(conn,prompt_id)
    if row['kind'] != 'comparison':
        raise PromptError('invalid_request')
    if selected is not None and selected not in {o['posting_id'] for o in _body(row)['subject']['options']}:
        raise PromptError('invalid_request')
    request = _request('comparison',row,request_id,actor,source,{'selected':selected})
    prior = _prior_response(conn,request)
    if prior is not None:
        return prior
    if _existing_pick(conn,row,request):
        return _finalize(conn,row,request)
    _reserve(conn,config,row,request)
    row = _get(conn,prompt_id)
    if row['set_id'] is None:
        _finish_set(conn,config,row)
        row = _get(conn,prompt_id)
    try:
        preference_service.record_pick(conn,config,row['set_id'],selected,'prompt:'+digest(request))
    except PreferenceError as exc:
        if str(exc) in ('stale_set','unknown_set'):
            _stale(conn,row)
            raise PromptError('comparison_stale') from None
        raise PromptError('feedback_conflict') from None
    return _finalize(conn,row,request)


def answer_question(conn, config, prompt_id, text, *, request_id, actor, source='api'):
    _validate_write(actor,source,request_id)
    if conn.in_transaction:
        raise PromptError('transaction_active')
    if type(text) is not str or not text.strip() or len(text)>4000:
        raise PromptError('invalid_request')
    row = _get(conn,prompt_id)
    if row['kind'] != 'question':
        raise PromptError('invalid_request')
    request = _request('answer',row,request_id,actor,source,{'text':text})
    prior = _prior_response(conn,request)
    if prior is not None:
        return prior
    _reserve(conn,config,row,request)
    # No canonical choice operation is involved: raw human words remain feedback.
    return _finalize(conn,row,request)


def dismiss_prompt(conn, prompt_id, *, config, request_id, actor, source='api'):
    _validate_write(actor,source,request_id)
    if conn.in_transaction:
        raise PromptError('transaction_active')
    row = _get(conn,prompt_id)
    request = _request('dismiss',row,request_id,actor,source,{})
    _prior_response(conn,request)
    response = _body(row).get('response')
    result = dict(closed='dismissed',prompt_id=row['id'],subject_digest=digest(_body(row)['subject']))
    if row['closed_reason']=='dismissed' and response and response['input_hash']==digest(request):
        return result
    _reserve(conn,config,row,request)
    with _transaction(conn):
        current = _get(conn,prompt_id)
        if _body(current).get('response',{}).get('input_hash') != digest(request):
            raise PromptError('feedback_conflict')
        _close(conn,current,'dismissed',_time())
    return result
