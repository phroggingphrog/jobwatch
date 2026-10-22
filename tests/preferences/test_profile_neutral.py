"""Synthetic regressions for neutral model inputs and immutable stale history."""
import copy
import sqlite3
from pathlib import Path

import pytest

from jobwatch.candidate.contracts import JOB_ROLE_FAMILIES, TargetPolicy, digest
from jobwatch.preferences.features import (FAMILIES, NAMES, PRIOR_MEANS, PreferenceError,
    family_index, validate_alternatives, versions)
from jobwatch.preferences.store import PreferenceStore
from tests.preferences.test_core import CTX, alternative


def test_new_target_policies_have_no_unconfirmed_personal_exclusions(tmp_path, monkeypatch):
    (tmp_path / 'interests_and_criteria.yaml').write_text('target_roles:\n  excluded_families: [hospitality]\n')
    monkeypatch.setenv('JOBWATCH_PROFILE_DIR', str(tmp_path))
    policy = TargetPolicy(version='neutral-current')
    assert policy.excluded_codes == ()
    assert 'hospitality' in policy.allowed_families
    assert TargetPolicy(version='custom', allowed_families=('hospitality',), excluded_codes=('123456',)).excluded_codes == ('123456',)


def test_historical_policy_payload_keeps_its_digest_and_parses_across_people(tmp_path, monkeypatch):
    (tmp_path / 'interests_and_criteria.yaml').write_text('target_roles:\n  excluded_families: [hospitality]\n')
    monkeypatch.setenv('JOBWATCH_PROFILE_DIR', str(tmp_path))
    historical = {'version':'owner-targets-v1', 'allowed_families':['accounting','hospitality'],
                  'excluded_codes':['431111','541211']}
    before = digest(historical)
    parsed = TargetPolicy.model_validate(historical)
    assert parsed.model_dump(mode='json') == historical
    assert digest(parsed.model_dump(mode='json')) == before


def test_cold_start_tastes_and_family_intercepts_are_neutral():
    assert len(PRIOR_MEANS) == len(NAMES)
    assert all(x == 0 for x in PRIOR_MEANS)
    assert tuple(FAMILIES) == tuple(JOB_ROLE_FAMILIES)
    assert len({family_index(f) for f in JOB_ROLE_FAMILIES}) == len(JOB_ROLE_FAMILIES)
    assert family_index('Data Analyst') == family_index('data_analyst')
    source = (Path(__file__).parents[2] / 'jobwatch/preferences/fit_choice_model.R').read_text()
    assert 'a0 <- rep(0, F)' in source


def test_alternative_validation_does_not_reapply_unapproved_legacy_preferences(tmp_path, monkeypatch):
    (tmp_path / 'interests_and_criteria.yaml').write_text('target_roles:\n  excluded_families: [hospitality]\n')
    monkeypatch.setenv('JOBWATCH_PROFILE_DIR', str(tmp_path))
    rows = [alternative(i) for i in (1,2,3)]
    rows[0]['family'] = 'hospitality'
    assert validate_alternatives(rows)[0]['family'] == 'hospitality'


def historical_store():
    store = PreferenceStore(sqlite3.connect(':memory:'), origin='synthetic')
    store.ensure()
    old_versions = copy.deepcopy(versions())
    old_versions.update(feature='choice-features-v2', model='conditional-logit-outside-v1',
                        prior='archived-directions-sd05-missing-sd05-v1')
    from jobwatch.preferences.features import canonical, digest
    payload = {'alternatives':[alternative(i) for i in (1,2,3)], 'versions':old_versions,
               'origin':'synthetic', 'context_hash':CTX}
    store.conn.execute('INSERT INTO preference_sets VALUES(?,?,?,?,?,?)',
        ('historic', CTX, '2020-01-01', 0, canonical(payload), digest(payload)))
    store.conn.commit()
    return store


def test_historical_choices_stay_readable_explicitly_stale_and_unmodified():
    store = historical_store()
    store.conn.execute('INSERT INTO preference_picks VALUES(?,?,?,?,?)',
                       ('historic', 2, 'original-owner-response', 'owner', '2020-01-02'))
    store.conn.commit()
    before = list(store.conn.iterdump())
    state = store.status('c'*64)
    assert state['status'] == 'stale'
    assert state['historical_choices'] == 1 and state['stale_choices'] == 1
    assert state['n_choices'] == 0 and store.dataset(CTX) == []
    assert store.get_set('historic')['selected'] == 2
    assert list(store.conn.iterdump()) == before


def test_a_stale_unanswered_set_cannot_acquire_a_new_owner_response():
    store = historical_store()
    with pytest.raises(PreferenceError, match='stale_set'):
        store.pick('historic', 2, actor='owner', request_id='new')
    assert not store.get_set('historic')['answered']


def test_fit_payload_preserves_canonical_families_and_has_no_directional_prior():
    from jobwatch.preferences.model import prepare_data
    from tests.preferences.test_core import populate
    store = PreferenceStore(sqlite3.connect(':memory:'), origin='synthetic')
    sets = populate(store)
    for s in sets:
        for a, family in zip(s['alternatives'], ('engineering', 'education', 'health')):
            a['family'] = family
    payload = prepare_data(sets)
    assert payload['families'] == list(JOB_ROLE_FAMILIES)
    assert payload['prior_means'] == [0.] * (2 * len(NAMES))
    assert payload['sets'][0]['family'] == [family_index(f) for f in ('engineering', 'education', 'health')]


def test_historical_fit_is_stale_without_rewriting_its_posterior_or_owner_labels():
    store = historical_store()
    store.conn.execute('INSERT INTO preference_picks VALUES(?,?,?,?,?)',
                       ('historic', 2, 'original-owner-response', 'owner', '2020-01-02'))
    old_versions = store.get_set('historic')['versions']
    store.conn.commit()
    store.save_fit({'id':'archived-fit', 'context_hash':CTX, 'dataset_hash':'d'*64,
                    'versions':old_versions, 'draws':{'alpha':[[.5,0,0,0,0]]}})
    before = list(store.conn.iterdump())
    assert store.status(CTX)['status'] == 'stale'
    assert store.latest_fit(CTX)['draws']['alpha'] == [[.5,0,0,0,0]]
    # Retrying the original immutable response remains idempotent after an upgrade.
    assert store.pick('historic', 2, actor='owner', request_id='original-owner-response')['selected'] == 2
    assert list(store.conn.iterdump()) == before


def test_read_only_insights_refuse_stale_synthetic_choices_without_predicting_or_fitting(monkeypatch):
    from pipeline.agentic.model_insights import preference_insights
    from jobwatch import preference_service
    store = historical_store()
    store.conn.execute('INSERT INTO preference_picks VALUES(?,?,?,?,?)',
                       ('historic', 2, 'original-owner-response', 'owner', '2020-01-02'))
    store.conn.commit()
    monkeypatch.setattr(preference_service, 'pool', lambda conn, config: ('c'*64, []))
    # The advisory endpoint normally reads owner state. This store remains synthetic;
    # origin filtering must never present its synthetic choices as an owner's history.
    state = preference_insights(store.conn, None, 'historic')
    assert state['prediction_status'] == 'stale_set'
    assert state['historical_choices'] == 0
    assert 'prediction' not in state
    assert store.get_set('historic')['selected'] == 2


def test_confirmed_preference_only_change_stales_choices_and_fit_without_rewriting(monkeypatch):
    from types import SimpleNamespace
    from jobwatch import users
    from jobwatch.candidate import intake
    from jobwatch.preference_service import preference_context
    from tests.preferences.test_core import good_summary
    from tests.candidate.policy_fixtures import approved, fact
    current = {'value': approved(fact('preference', {'kind':'writing_style', 'value':'formal'}), version=2)}
    monkeypatch.setattr(users, 'current', lambda: 'synthetic-person')
    monkeypatch.setattr(intake, 'current_version', lambda person: current['value'] if person == 'synthetic-person' else None)
    # Writing preferences are absent from the evidence allowlist and do not change the structural projection.
    inputs = dict(bundle=SimpleNamespace(bundle_hash='b'*64), policy=TargetPolicy(version='confirmed-targets-v2'),
                  cfg={}, structural=SimpleNamespace(run_key='a'*64))
    old_context = preference_context(**inputs)
    store = PreferenceStore(sqlite3.connect(':memory:'), origin='synthetic')
    for i in range(25):
        choice = store.create_set([alternative(3*i+j+1) for j in range(3)], old_context)
        store.pick(choice['id'], None, actor='owner', request_id=f'synthetic-{i}')
    fit = {**good_summary(), 'id':'synthetic-fit', 'context_hash':old_context,
           'dataset_hash':store.dataset_hash(old_context), 'versions':versions(), 'origin':'synthetic'}
    store.save_fit(fit)
    assert store.status(old_context)['status'] == 'synthetic_valid'
    before = list(store.conn.iterdump())
    current['value'] = approved(fact('preference', {'kind':'writing_style', 'value':'direct'}), version=3)
    new_context = preference_context(**inputs)
    assert new_context != old_context
    state = store.status(new_context)
    assert state['status'] == 'stale' and state['stale_choices'] == 25
    assert state['n_choices'] == 0 and store.dataset(new_context) == []
    assert store.latest_fit(old_context) == fit
    assert list(store.conn.iterdump()) == before
