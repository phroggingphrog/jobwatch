"""Read-only access to existing career models; no fitting or owner-label writes."""
from __future__ import annotations

import sqlite3

from jobwatch.preferences import PreferenceStore, PreferenceError, predict_set
from pipeline.agentic import service


def candidate_paths(config) -> dict:
    from jobwatch.candidate.analysis import structural_summary
    bundle = service.snapshot_evidence(service.profile_dir())
    result = service.analyse_candidate(bundle, *service.load_inputs(bundle, service._config(config)), service.default_policy())
    summary = structural_summary(result)
    summary.pop('detail_tool', None)
    return summary


def preference_insights(conn, config, set_id: str = '') -> dict:
    from jobwatch.preference_service import pool
    if type(set_id) is not str or len(set_id) > 128:
        raise PreferenceError('invalid_set')
    identity, alternatives = pool(conn, config)
    store = PreferenceStore(conn)
    state = store.status(identity)
    result = {key: state[key] for key in ('status', 'n_sets', 'n_choices', 'n_train', 'n_holdout',
                                        'minimum_train', 'minimum_holdout', 'historical_choices', 'stale_choices')}
    result['meaning'] = 'Owner-choice preference within three eligible jobs plus none; not hiring probability or qualification.'
    from jobwatch.preferences.features import NAMES, FEATURE_VERSION
    result['feature_coverage'] = {'version': FEATURE_VERSION, 'alternatives': len(alternatives),
        'observed_counts': {name: sum(a['features'][name] is not None for a in alternatives) for name in NAMES}}
    if not set_id:
        # Only already answered sets are offered for prediction, preserving blind owner labels.
        result['answered_set_ids'] = [s['id'] for s in store.list_sets(identity) if s['answered']][-10:]
        return result
    item = store.get_set(set_id)
    current = {a['posting_id']: a for a in alternatives}
    if item is None:
        result['prediction_status'] = 'unknown_set'
    elif not item['answered']:
        result['prediction_status'] = 'owner_choice_required'
    elif item['context_hash'] != identity or not all(current.get(a['posting_id']) == a for a in item['alternatives']):
        result['prediction_status'] = 'stale_set'
    elif state['status'] != 'valid':
        result['prediction_status'] = 'valid_current_fit_required'
    else:
        result['prediction'] = predict_set(store, item['alternatives'], identity)
        result['prediction_status'] = 'available'
    return result


def callback_insights(conn) -> dict:
    from jobwatch.outcomes.callback import callback_stats
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'applications', 'application_events', 'matches'} <= tables:
        return {'status': 'no_data', 'reason': 'application_history_unavailable'}
    stats = callback_stats(conn)
    return {'status': 'available' if stats['_all']['n'] else 'prior_only', 'arms': stats,
            'meaning': 'Callbacks among explicitly resolved submissions with Beta(1,15) prior and 95% interval. Pending cases are censored, unsubmitted drafts excluded. Resolved-subset selection bias remains; no individual-job or eventual-callback forecast.'}


def pipeline_insights(conn, config, *, bundle, policy, cfg, structural) -> dict:
    """Persist the existing model layers alongside every core job assessment."""
    from jobwatch.candidate.analysis import structural_summary
    from jobwatch.preference_service import preference_context
    identity = preference_context(bundle=bundle, policy=policy, cfg=cfg, structural=structural)
    store = PreferenceStore(conn)
    try:
        state = store.status(identity)
        preferences = {k: state[k] for k in ('status', 'n_choices', 'n_train', 'n_holdout',
                                           'minimum_train', 'minimum_holdout', 'historical_choices', 'stale_choices')}
        preferences['meaning'] = 'Owner-choice model readiness; not qualification, motivation or hiring odds.'
    except (ValueError, OSError, sqlite3.DatabaseError):
        preferences = {'status': 'unavailable', 'reason': 'preference_state_unavailable'}
    try:
        callbacks = callback_insights(conn)
    except (ValueError, OSError, ImportError, sqlite3.DatabaseError):
        callbacks = {'status': 'unavailable', 'reason': 'callback_model_unavailable'}
    overview = structural_summary(structural)
    # Full fits remain in the saved candidate assessment and evaluator's lookup tool.
    overview.pop('detail_tool', None)
    return {'stage': 'market_evaluator', 'structural_fit': overview, 'preferences': preferences, 'callbacks': callbacks,
            'role': 'Advisory model context; canonical eligibility and factual gates remain authoritative.'}
