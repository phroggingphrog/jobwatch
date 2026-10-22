"""Explicit, conservative copies of immutable answered owner comparisons.

No automatic refit, candidate writes, new choices or model calls. Historical
records lacking complete profile and policy provenance remain readable history.
"""
from __future__ import annotations

from .features import PreferenceError, versions, validate_alternatives
from .store import PreferenceStore


_HASHES = ('approved_hash', 'policy_hash', 'profile_hash', 'ad_hash', 'run_key', 'evaluation_hash')


def _same_source(old, current):
    for key in _HASHES:
        value = old.get(key)
        if (type(value) is not str or len(value) != 64
                or any(c not in '0123456789abcdef' for c in value)
                or current.get(key) != value):
            return False
    return all(type(old.get(key)) is str and old[key].strip() and old[key] == current.get(key)
               for key in ('title', 'company'))


def refeaturise(conn, config, *, actor):
    """Copy verifiably unchanged owner picks, preserving original splits and none."""
    if actor != 'owner':
        raise PreferenceError('explicit_owner_required')
    from jobwatch import preference_service

    store = PreferenceStore(conn)
    records = store.list_sets()
    current_versions = versions()
    # Migrations are copies of the original answer, never additional training labels.
    # Repeated upgrades always use the root original rather than duplicating copies.
    sources = [s for s in records if s.get('origin') == 'owner' and s['answered']
               and s['versions'] != current_versions and not s.get('migrated_from')]
    counts = {'migrated':0, 'already':0, 'not_current':0, 'changed':0}
    if not sources:
        return counts
    identity, pool = preference_service.pool(conn, config, statuses=('eligible', 'held'))
    current = {a['posting_id']:a for a in pool}
    for source in sources:
        old = source.get('alternatives', [])
        ids = [a.get('posting_id') for a in old]
        if len(ids) != 3 or len(set(ids)) != 3:
            counts['changed'] += 1
            continue
        if any(pid not in current for pid in ids):
            counts['not_current'] += 1
            continue
        alternatives = [current[pid] for pid in ids]
        if not all(_same_source(a,b) for a,b in zip(old, alternatives)):
            counts['changed'] += 1
            continue
        # A later confirmation changes full approved_hash even when primary
        # evidence and run_key are unchanged; it must not inherit this answer.
        try:
            alternatives = validate_alternatives(alternatives)
        except PreferenceError:
            counts['changed'] += 1
            continue
        existing = next((s for s in records if s.get('migrated_from') == source['id']
                         and s['context_hash'] == identity and s['versions'] == current_versions), None)
        if existing:
            if (existing['alternatives'] != alternatives or existing['holdout'] != source['holdout']
                    or (existing['answered'] and existing['selected'] != source['selected'])):
                counts['changed'] += 1
                continue
            if existing['answered']:
                counts['already'] += 1
                continue
        fresh_identity, fresh_pool = preference_service.pool(conn, config, statuses=('eligible', 'held'))
        fresh = {a['posting_id']:a for a in fresh_pool}
        if any(pid not in fresh for pid in ids):
            counts['not_current'] += 1
            continue
        if fresh_identity != identity or any(fresh[pid] != current[pid] for pid in ids):
            counts['changed'] += 1
            continue
        try:
            copied = store.create_set(alternatives, identity, holdout=source['holdout'], migrated_from=source['id'])
        except PreferenceError as exc:
            if str(exc) != 'split_overlap':
                raise
            counts['changed'] += 1
            continue
        # If interrupted after create_set, the next explicit invocation completes
        # this same copy with the already-recorded answer and request id.
        request_id = 'migrate:'+source['id']
        # A later feature upgrade must not reuse the unique request id of its
        # earlier copy. This suffix is stable across interrupted retries.
        prior = conn.execute('SELECT set_id FROM preference_picks WHERE request_id=?', (request_id,)).fetchone()
        if prior and prior[0] != copied['id']:
            request_id += ':'+copied['id']
        store.pick(copied['id'], source['selected'], actor='owner', request_id=request_id)
        counts['migrated'] += 1
        records.append(store.get_set(copied['id']))
    return counts
