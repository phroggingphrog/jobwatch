"""Typed, person-scoped discovery requests on the existing durable API worker."""
from __future__ import annotations

import hashlib
import json
import time
from contextlib import nullcontext

from jobwatch import users
from jobwatch.candidate import intake
from pipeline.agentic.api_store import APIStore, Conflict
from pipeline.agentic.chat import job_connection, skill_version
from pipeline.agentic import incidents, service
from pipeline.agentic import discovery_settings


def _context(conn, config, posting_id):
    approved = intake.current_version(users.current())
    captured = service._capture(conn, posting_id)
    if not approved or captured is None:
        raise Conflict('retry_inputs_unavailable')
    value = {'profile': approved, 'posting': captured, 'config': service._config(config),
             'discovery_settings': discovery_settings.get_settings(users.current(), config),
             'implementation': service.IMPLEMENTATION_VERSION}
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def status(person, config):
    with users.use(person), job_connection(config, write=True) as conn:
        service.AgenticStore(conn).ensure()
        incidents.ensure(conn)
        items = incidents.list_incidents(conn)
        for item in items:
            item['next_action'] = 'retry_assessment' if item.get('posting_id') else 'inspect_run_then_start_discovery'
            if item.get('posting_id'):
                try:
                    item['retry_context'] = _context(conn, config, item['posting_id'])
                except Conflict:
                    item['retry_context'] = None
        postings = conn.execute('SELECT COUNT(*) FROM postings').fetchone()[0]
        spent = service._spent_today(conn, service._local_midnight(service._now()))
        scope = intake.discovery_scope(person)
        invocations = []
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='agentic_invocations'").fetchone():
            rows = conn.execute('SELECT run_id,unit,phase,posting_id,state,started_at,updated_at,last_successful_phase '
                                'FROM agentic_invocations ORDER BY updated_at DESC LIMIT 20')
            names = [column[0] for column in rows.description]
            invocations = [dict(zip(names, row)) for row in rows]
    with APIStore(person) as store:
        row = store.conn.execute("SELECT id FROM api_runs WHERE json_extract(input_json,'$.discovery')=1 "
                                 'ORDER BY created DESC LIMIT 1').fetchone()
        latest = store.public_run(row[0]) if row else None
    return {'enabled': scope is not None, 'postings': postings, 'assessments_today': spent[0],
            'charged_tokens_today': spent[1], 'scope': scope.model_dump(mode='json') if scope else None,
            'incidents': items, 'invocations': invocations, 'latest_run': latest}


def get_settings(person, config):
    with users.use(person):
        return discovery_settings.get_settings(person, config)


def set_settings(person, config, daily_token_ceiling, **job_limits):
    with users.use(person):
        return discovery_settings.set_settings(person, config, daily_token_ceiling, **job_limits)


def start(person, config, request_id, *, incident_id=None, posting_id=None, expected_context=None):
    with users.use(person):
        payload = {'discovery': True}
        if incident_id is not None:
            payload.update(incident_id=incident_id, posting_id=posting_id, expected_context=expected_context)
        # A replay reads its immutable receipt, even when the admitted work has
        # released the incident or the person has since changed their profile.
        with APIStore(person) as store:
            existing = store.discovery_receipt(payload, request_id)
            if existing:
                return {'run_id': existing, 'state': store.raw_run(existing)['state']}
        if intake.discovery_scope(person) is None:
            raise Conflict('profile_not_ready')
        if incident_id is not None:
            with job_connection(config, write=True) as conn:
                if _context(conn, config, posting_id) != expected_context:
                    raise Conflict('retry_inputs_changed')
                item = next((i for i in incidents.list_incidents(conn)
                             if i['incident_id'] == incident_id and i.get('posting_id') == posting_id), None)
                if item is None:
                    raise Conflict('incident_not_found')
        with APIStore(person) as store:
            ident = store.enqueue_discovery(payload, request_id, skill_version())
            return {'run_id': ident, 'state': store.raw_run(ident)['state']}


def execute(person, config, run_id, payload, *, seconds=600):
    with users.use(person), job_connection(config, write=True) as conn:
        deadline = time.time() + min(780, max(0, seconds))
        service.AgenticStore(conn).ensure()
        incidents.reconcile_known_failures(conn)
        unit = 'jobwatch-agent.service'
        incidents.begin_run(conn, run_id, unit=unit)
        state = 'completed'
        try:
            if 'incident_id' in payload:
                posting = payload['posting_id']
                if _context(conn, config, posting) != payload['expected_context']:
                    raise Conflict('retry_inputs_changed')
                scope = intake.discovery_scope(person)
                spent = service._spent_today(conn, service._local_midnight(service._now()))
                per_run_cap = service._config(config)['batch_token_ceiling']
                remaining = discovery_settings.allowance(
                    scope.daily_token_ceiling, spent[1], per_run_cap) if scope is not None else 0
                allowance_reason = discovery_settings.allowance_reason(
                    scope.daily_token_ceiling, spent[1], per_run_cap) if scope is not None else 'daily_budget'
                if scope is None or spent[0] >= scope.daily_assessments or remaining <= 0:
                    return {'deferred': 'daily_budget'}
                from jobwatch.util import adtext as adtext
                with adtext.review_lock(adtext.lock_path(config)) as acquired:
                    if not acquired:
                        return {'skipped': 'busy'}
                    from pipeline.agentic import execution as invocation
                    current = invocation.current()
                    if current is not None:
                        current.token_ceiling = min(current.token_ceiling, current.charged_tokens+remaining)
                    budget_context = nullcontext() if current is not None else invocation.use(
                        invocation.Execution(run_id, seconds=max(0,deadline-time.time()), token_ceiling=remaining))
                    batch_id = 'retry-' + run_id
                    service.AgenticStore(conn).create_batch(batch_id,
                        per_run_cap, deadline)
                    incidents.release(conn, payload['incident_id'], posting)
                    with budget_context:
                        result = service.agentic_batch_run([posting], config, conn, operation='evaluate',
                            max_seconds=max(0, deadline-time.time()), deadline=deadline, run_id=run_id,
                            batch_id=batch_id, token_allowance=remaining,
                            token_allowance_reason=allowance_reason)
            else:
                result = service.after_collect(conn, config, max_seconds=seconds, deadline=deadline, run_id=run_id)
            return result
        except Exception as exc:
            state = 'failed'
            reason = getattr(exc, 'code', 'execution_failed')
            incidents.report(conn, run_id=run_id, reason=reason, phase='discovery',
                             posting_id=payload.get('posting_id') if 'incident_id' in payload else None)
            raise
        finally:
            incidents.end_run(conn, run_id, state=state)
