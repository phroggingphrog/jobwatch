"""Private frozen evaluation inputs, write-once grouped splits and audited access.

Only freezing reads live state. Replay/monitor use this person's frozen files.
Development loading never opens a holdout case or the shared human-label log.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import time

from jobwatch import users
from jobwatch.apply.paths import ensure_dir, safe_write_bytes
from jobwatch.candidate import intake
from jobwatch.candidate.contracts import digest
from pipeline.agentic import baseline
from pipeline.agentic.contracts import AgenticError

VERSION = 'evaluation-inputs-v1'
SPLIT_VERSION = 'grouped-split-v1'


def code_hash():
    """Pin actual source bytes, including uncommitted source, rather than just HEAD."""
    root = Path(__file__).parents[2]
    sources = {}
    for package in ('pipeline', 'jobwatch'):
        for path in sorted((root/package).rglob('*.py')):
            sources[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest({'python':sources,'gate':baseline.gate_sources()})


def private_dir(path):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.is_symlink():
            raise AgenticError('unsafe_evaluation_path')
    ensure_dir(path)
    path.chmod(0o700)
    return path


@contextlib.contextmanager
def locked(folder):
    folder = private_dir(folder)
    fd = os.open(folder/'evaluation.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def write_once(path, value):
    private_dir(path.parent)
    raw = baseline._canonical(value)
    if os.path.lexists(path):
        if path.is_symlink() or path.read_bytes()!=raw:
            raise AgenticError('evaluation_conflict')
    else:
        safe_write_bytes(path, raw)
    path.chmod(0o600)


def capture_case_context(conn, config, case):
    from pipeline.agentic import discovery
    _, plan = discovery._current_plan(users.current())
    judgment = discovery.latest_judgment(conn,case.posting_id)
    if (judgment and plan and judgment.ad_hash==case.evaluation['run_key']['ad_hash']
            and judgment.plan_hash==plan.plan_hash):
        return {'relevance':judgment.model_dump(mode='json')}
    return {'relevance':None}


def capture_inputs(conn, config, cases, approved, *, staging):
    """Called inside baseline staging; no model, schema or database writes."""
    from pipeline.agentic import service, discovery, shortlist
    from jobwatch.preferences import PreferenceStore
    _, plan = discovery._current_plan(users.current())
    fields = shortlist._fields(config)
    by_posting = {case.posting_id:case for case in cases}
    choices = {}
    for choice in PreferenceStore(conn).list_sets():
        if not choice['answered'] or choice.get('origin')!='owner':
            continue
        alternatives=choice['alternatives']
        if not all(a['posting_id'] in by_posting for a in alternatives):
            continue
        if not all(a.get('run_key')==by_posting[a['posting_id']].run_key
                   and a.get('evaluation_hash')==digest(by_posting[a['posting_id']].evaluation)
                   and a.get('approved_hash',a.get('source_provenance',{}).get('approved_hash'))==digest(approved)
                   for a in alternatives):
            continue
        raw=baseline._canonical(choice)
        sha=baseline._sha(raw)
        private_dir(staging/'choices')
        safe_write_bytes(staging/'choices'/f'{sha}.json',raw)
        choices[sha]={'sha256':sha,'posting_ids':sorted(a['posting_id'] for a in alternatives)}
    return dict(version=VERSION,person=users.current(),runtime=service._config(config),
                discovery=discovery.settings(config),approved_hash=digest(approved),
                plan=plan.model_dump(mode='json') if plan else None,
                fields=[h.model_dump(mode='json') for h in fields],choice_index=choices)


def freeze_cases(conn, config, *, posting_ids=None, limit=500):
    if conn.in_transaction:
        raise AgenticError('transaction_active')
    with intake._locked(users.current(),'versions.lock'):
        conn.execute('BEGIN')  # stable read snapshot; connection is read-only in CLI
        try:
            return baseline.freeze_baseline(conn,config,posting_ids=posting_ids,limit=limit)
        finally:
            conn.rollback()


def record_for(baseline_id):
    folder = baseline._baseline_dir(baseline_id)
    for path in (folder, *folder.parents):
        if path.is_symlink():
            raise AgenticError('unsafe_evaluation_path')
    record = baseline._read_record(folder,baseline_id)
    if record.person!=users.current():
        raise AgenticError('evaluation_person_mismatch')
    return record


def load_inputs(baseline_id):
    record = record_for(baseline_id)
    if record.evaluation_inputs_sha256 is None:
        raise AgenticError('frozen_context_unavailable')
    folder = baseline._baseline_dir(baseline_id)
    try:
        result = json.loads(baseline._read_verified(folder/'evaluation_inputs.json',record.evaluation_inputs_sha256))
        if (result['version']!=VERSION or result['person']!=users.current()
                or digest(result['runtime'])!=record.runtime_config_sha256
                or result['approved_hash']!=digest(baseline.frozen_approved(baseline_id))):
            raise ValueError
        return result
    except (ValueError,KeyError,TypeError):
        raise AgenticError('baseline_corrupt') from None


def _case(record, case_id, cache):
    if case_id not in record.case_ids or not baseline._CASE_ID.fullmatch(case_id):
        raise AgenticError('unknown_case')
    folder = baseline._baseline_dir(record.baseline_id)
    raw = baseline._read_verified(folder/'cases'/f'{case_id}.json',record.case_sha256[case_id])
    case = baseline._inflate(folder,raw,cache)
    from .contracts import RunKey
    if case.case_id!=case_id or case.run_key!=RunKey.model_validate(case.evaluation['run_key']).value:
        raise AgenticError('baseline_corrupt')
    # Every ad is bound to its actual bytes, even if historical grouping metadata is missing.
    baseline._snapshot_ad_hash(case.snapshot,case.run_key)
    return case


def _seal(value, key):
    return {**value,key:digest(value)}


def _validate_seal(value,key):
    if not isinstance(value,dict) or value.get(key)!=digest({k:v for k,v in value.items() if k!=key}):
        raise AgenticError('evaluation_corrupt')


def create_split(baseline_id, *, seed=1729):
    if type(seed) is not int or not 0<=seed<2**32:
        raise AgenticError('invalid_split_seed')
    record=record_for(baseline_id)
    load_inputs(baseline_id)
    folder=private_dir(baseline._baseline_dir(baseline_id)/'evaluation')
    with locked(folder):
        path=folder/'split.json'
        if path.exists():
            result=load_split(baseline_id)
            if result['seed']!=seed:
                raise AgenticError('split_conflict')
            return result
        cache={}; keys={}
        for cid in record.case_ids:
            case=_case(record,cid,cache)
            posting=case.snapshot['posting']
            ad_hash=case.evaluation['run_key']['ad_hash']
            # Union old explicit keys with freshly derived keys; no caller can separate duplicates.
            keys[cid]=tuple(set(case.group_keys)|set(baseline.group_keys_for(posting,ad_hash)))
        grouped=baseline.group_ids(keys)
        groups=sorted(set(grouped.values()),key=lambda g:(digest([seed,g]),g))
        if len(groups)<2:
            raise AgenticError('insufficient_groups')
        n_holdout=min(len(groups)-1,max(1,math.ceil(.30*len(groups))))
        holdout_groups=set(groups[:n_holdout])
        index={cid:dict(group=grouped[cid],keys=sorted(digest(k) for k in keys[cid])) for cid in sorted(keys)}
        result=_seal(dict(version=SPLIT_VERSION,baseline_id=baseline_id,data_hash=digest(record.model_dump(mode='json')),
            seed=seed,holdout_fraction=.30,allocation='ceil_30_percent_groups',index=index,
            development=sorted(cid for cid in keys if grouped[cid] not in holdout_groups),
            holdout=sorted(cid for cid in keys if grouped[cid] in holdout_groups)), 'split_hash')
        _check_split(record,result)
        write_once(path,result)
        return result


def _check_split(record,value):
    _validate_seal(value,'split_hash')
    try:
        dev,held=value['development'],value['holdout']
        if (value['version']!=SPLIT_VERSION or value['baseline_id']!=record.baseline_id
                or value['data_hash']!=digest(record.model_dump(mode='json'))
                or not dev or not held or len(set(dev+held))!=len(dev+held)
                or set(dev+held)!=set(record.case_ids) or set(value['index'])!=set(record.case_ids)):
            raise ValueError
        dgroups={value['index'][cid]['group'] for cid in dev}
        hgroups={value['index'][cid]['group'] for cid in held}
        dkeys={k for cid in dev for k in value['index'][cid]['keys']}
        hkeys={k for cid in held for k in value['index'][cid]['keys']}
        if dgroups & hgroups or dkeys & hkeys:
            raise AgenticError('split_leakage')
    except AgenticError:
        raise
    except (KeyError,TypeError,ValueError):
        raise AgenticError('evaluation_corrupt') from None


def load_split(baseline_id):
    record=record_for(baseline_id)
    path=baseline._baseline_dir(baseline_id)/'evaluation'/'split.json'
    if any(part.is_symlink() for part in (path,*path.parents)):
        raise AgenticError('unsafe_evaluation_path')
    try:
        value=json.loads(path.read_bytes())
    except (OSError,ValueError):
        raise AgenticError('split_unavailable') from None
    _check_split(record,value)
    return value


def audit_holdout(baseline_id, operation, *, allow_holdout=False):
    if not allow_holdout:
        raise AgenticError('holdout_approval_required')
    if operation not in ('replay','report','label','fit'):
        raise AgenticError('invalid_holdout_operation')
    split=load_split(baseline_id)
    folder=private_dir(baseline._baseline_dir(baseline_id)/'evaluation')
    with locked(folder):
        path=folder/'holdout_access.jsonl'
        fd=os.open(path,os.O_CREAT|os.O_APPEND|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        try:
            row=dict(operation=operation,data_hash=split['data_hash'],split_hash=split['split_hash'],
                     code_hash=code_hash(),person=users.current(),accessed_at=baseline._utcnow())
            os.write(fd,baseline._canonical(row)+b'\n')
            os.fsync(fd)
        finally:
            os.close(fd)


def partition_ids(baseline_id, partition, *, allow_holdout=False, operation='replay'):
    if partition not in ('development','holdout'):
        raise AgenticError('invalid_partition')
    split=load_split(baseline_id)
    if partition=='holdout':
        audit_holdout(baseline_id,operation,allow_holdout=allow_holdout)
    return list(split[partition])


def load_partition(baseline_id,partition,*,allow_holdout=False):
    record=record_for(baseline_id)
    ids=partition_ids(baseline_id,partition,allow_holdout=allow_holdout)
    cache={}
    return record,[_case(record,cid,cache) for cid in ids]
