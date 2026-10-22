"""Digest-confirmed amendments to the canonical approved exclusion facts.

No assessment or fitting occurs here. Immutable profile versions are the durable
commit record; retrying a projection interrupted after publication finishes it.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import secrets
import shutil

import yaml

from jobwatch import users
from jobwatch.apply.paths import ensure_dir, profile_dir
from . import intake, projection
from ._private_io import read_regular_file
from .contracts import digest
from .policy import policy_for, rules_from_fact


class RuleError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _root():
    return intake._root(users.current()) / 'rules'


def _load(ident):
    if not isinstance(ident, str) or not re.fullmatch('[0-9a-f]{32}', ident):
        raise RuleError('not_found')
    value = intake._read_json(_root() / (ident + '.json'), None)
    if not value or value.get('person') != users.current():
        raise RuleError('not_found')
    return value


def listing():
    policy = policy_for(users.current())
    current = intake.current_version(users.current())
    pending = []
    for path in sorted(_root().glob('*.json')):
        value = _load(path.stem)
        if value.get('base_hash') == digest(current):
            pending.append(value)
    return {'rules': [r.model_dump(mode='json') for r in policy.exclusions] if policy else [],
            'profile_version': current.get('version') if current else None, 'pending': pending}


def propose(config, *, op='add', kind=None, value=None, rule_id=None, request_id, actor):
    if actor != 'person':
        raise RuleError('person_required')
    if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 200:
        raise RuleError('invalid_request')
    if op not in ('add', 'withdraw'):
        raise RuleError('invalid_rule')
    payload = dict(op=op, kind=kind, value=value, rule_id=rule_id)
    if op == 'add':
        found = rules_from_fact(dict(id='pending', section='exclusion', basis='evidence', value=dict(kind=kind,value=value)))
        if not found or len(found[0].value) > 200 or rule_id is not None:
            raise RuleError('invalid_rule')
        payload.update(kind=found[0].kind, value=found[0].value)
    elif not isinstance(rule_id, str) or kind is not None or value is not None:
        raise RuleError('invalid_rule')
    person = users.current()
    ident = digest([person, request_id])[:32]
    with intake._locked(person, 'versions.lock'):
        prior = intake._read_json(_root() / (ident + '.json'), None)
        if prior:
            if prior['payload'] != payload:
                raise RuleError('idempotency_conflict')
            return prior
        approved = intake.current_version(person)
        if not approved or intake.discovery_scope(person) is None:
            raise RuleError('profile_not_ready')
        if op == 'withdraw' and not any(r.rule_id == rule_id for r in policy_for(person).exclusions):
            raise RuleError('rule_not_found')
        result = dict(id=ident, person=person, request_id=request_id, payload=payload,
                      base_hash=digest(approved), base_version=approved['version'],
                      created_at=datetime.now(timezone.utc).isoformat(),
                      authorises='Amend exclusion policy; existing assessments and fits may become stale.')
        result['digest'] = digest(result)
        intake._write_private(_root() / (ident + '.json'), json.dumps(result,sort_keys=True).encode())
        return result


def carry_facts(approved, facts):
    """Full intake confirmation cannot silently discard active approved rules."""
    result = list(facts)
    for original in (approved or {}).get('facts', ()):
        if not rules_from_fact(original):
            continue
        existing = next((f for f in result if f.id == original['id']), None)
        if existing and existing.model_dump(mode='json') != original:
            raise intake.IntakeError('proposal_changed')
        if existing is None:
            result.append(intake.ProfileFact.model_validate(original, strict=False))
    return result


def _finish(person, proposal, approved, vdir):
    name = 'interests_and_criteria.yaml'
    expected = dict(approved.get('file_sha256',{}))
    expected.pop(name,None)
    intake._refuse_hand_edits(profile_dir(),expected)
    try:
        live = hashlib.sha256(read_regular_file(profile_dir()/name,intake.MAX_JSON_BYTES)).hexdigest()
    except FileNotFoundError:
        live = None
    before = intake._approved(person,proposal['base_version']).get('file_sha256',{}).get(name)
    if live is not None and live not in (before,approved['file_sha256'][name]):
        raise RuleError('profile_edited_by_hand')
    intake._write_profile(profile_dir(), {name: read_regular_file(vdir / name, intake.MAX_JSON_BYTES).decode()})
    return dict(proposal_id=proposal['id'],version=approved['version'],
                profile_hash=digest(approved),status='confirmed',assessments='stale_until_reprocessed')


def confirm(config, proposal_id, *, rule_digest, actor):
    if actor != 'person':
        raise RuleError('person_required')
    person = users.current()
    with intake._locked(person, 'versions.lock'):
        proposal = _load(proposal_id)
        if proposal['digest'] != rule_digest or digest({k:v for k,v in proposal.items() if k!='digest'}) != rule_digest:
            raise RuleError('rule_changed')
        nums = intake._numbers(person)
        last = intake.current_version(person)
        # An earlier successful amendment is returned even after subsequent changes;
        # it must never project its older files over the current approved profile.
        for n in reversed(nums):
            previous = intake._approved(person, n)
            if previous.get('rule_amendment',{}).get('digest') == rule_digest:
                if n == nums[-1]:
                    return _finish(person,proposal,previous,intake._versions_root(person)/str(n))
                return dict(proposal_id=proposal_id,version=n,profile_hash=digest(previous),
                            status='confirmed',assessments='stale_until_reprocessed')
        if not last or digest(last) != proposal['base_hash']:
            raise RuleError('profile_changed')
        if intake.discovery_scope(person) is None:
            raise RuleError('profile_not_ready')
        intake._refuse_hand_edits(profile_dir(),last.get('file_sha256',{}))
        approved = copy.deepcopy(last)
        payload = proposal['payload']
        facts = approved['facts']
        if payload['op'] == 'add':
            facts.append(dict(id='rule-'+proposal_id,section='exclusion',basis='evidence',
                value=dict(kind=payload['kind'],value=payload['value']),sources=[],actor='person',note='stated by person'))
        else:
            facts[:] = [f for f in facts if not any(r.rule_id==payload['rule_id'] for r in rules_from_fact(f))]
        approved.update(version=nums[-1]+1, base_version=last['version'],
                        confirmed_at=datetime.now(timezone.utc).isoformat(),rule_amendment=proposal)
        source = intake._versions_root(person)/str(nums[-1])
        root = ensure_dir(intake._versions_root(person))
        stage = root / ('.staging-'+secrets.token_hex(8))
        try:
            shutil.copytree(source,stage)
            name = 'interests_and_criteria.yaml'
            prior = yaml.safe_load(read_regular_file(source/name,intake.MAX_JSON_BYTES)) or {}
            projected = yaml.safe_load(projection.project(approved)[name])
            prior.setdefault('target_roles',{}).update({k:projected['target_roles'][k] for k in ('not_wanted','excluded_families')})
            data = projection._dump(prior).encode()
            intake._write_private(stage/name,data)
            approved['file_sha256'][name] = hashlib.sha256(data).hexdigest()
            intake._write_private(stage/'approved.json',json.dumps(approved,sort_keys=True,ensure_ascii=False,indent=1).encode())
            dest = root/str(approved['version'])
            os.rename(stage,dest)
        except BaseException:
            shutil.rmtree(stage,ignore_errors=True)
            raise
        return _finish(person,proposal,approved,dest)
