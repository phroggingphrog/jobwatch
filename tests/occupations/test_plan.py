from types import SimpleNamespace
import json

import pytest

from jobwatch.occupations.plan import (search_plan, searches_overlay, query_for,
    title_matches_plan, save_plan, load_plan)
from pipeline.agentic.discovery import settings, recall_filter, prepare_run
from conftest import make_config


def policy(**kw):
    return SimpleNamespace(profile_version=1, policy_hash='a' * 64,
        focus=kw.get('focus', ()), home=kw.get('home'), remote_ok=kw.get('remote_ok', False))


def hyps(*titles):
    return [SimpleNamespace(title=t, id=f'anzsco2022:{i}') for i, t in enumerate(titles)]


def test_queries_and_hash_are_stable_deduplicated_and_capped():
    p = policy(focus=('anything related to my CV please',))
    h = hyps('Accountant (General)', 'Bookkeeper', 'Accountant (General)', *[f'Role {i}' for i in range(20)])
    plan = search_plan(p, h)
    assert plan.queries['seek'][:2] == ('accountant', 'bookkeeper')
    assert not {'anything related to my cv please'} & set(plan.queries['seek'])
    assert len(plan.queries['seek']) == 12
    assert plan.queries['seek'] == plan.queries['jora'] == plan.queries['jobspy']
    assert plan == search_plan(p, h)
    assert plan.plan_hash != search_plan(p, hyps('Nurse')).plan_hash


def test_overlay_keeps_settings_and_uses_home_without_mutating_base():
    base = {'location': 'Elsewhere', 'seek': {'enabled': True, 'max_pages': 2, 'keywords': ['old']},
            'jobspy': {'sites': ['indeed'], 'searches': [{'term': 'old'}]}}
    plan = search_plan(policy(home={'place': 'Sydney', 'state': 'NSW'}), hyps('Accountant'))
    out = searches_overlay(plan, base)
    assert out['seek']['where'] == 'Sydney, NSW'
    assert out['seek']['keywords'] == ['accountant'] and out['seek']['max_pages'] == 2
    assert out['jobspy']['sites'] == ['indeed']
    assert out['jobspy']['searches'] == [{'term': 'accountant', 'location': 'Sydney, NSW'}]
    assert base['seek']['keywords'] == ['old']


def test_remote_searches_and_extra_locations():
    p = policy(home={'place': 'Sydney', 'state': 'NSW', 'country': 'Australia'}, remote_ok=True)
    plan = search_plan(p, hyps('Accountant'), extra_locations=('Sydney, NSW', 'Perth, WA'))
    assert plan.locations == ('Sydney, NSW', 'Perth, WA')
    out = searches_overlay(plan, {}, p)
    assert out['seek']['searches'][-1] == {'term': 'accountant', 'location': 'Australia', 'is_remote': True}
    assert out['jobspy']['searches'][-1]['is_remote'] is True
    pv = policy(home={'place': 'Brunswick', 'state': 'VIC'})
    pv.regions = ('VIC',)
    planv = search_plan(pv, hyps('Nurse'),
        extra_locations=('I want work near Brunswick, VIC', 'not Sydney'))
    assert planv.locations == ('Brunswick, VIC', 'VIC')


def test_query_cleanup_and_whole_word_recall_only_widens():
    assert query_for('Accountant (General), n.e.c.') == 'accountant'
    plan = search_plan(policy(), hyps('Bookkeeper', 'Data Analysis Specialist'))
    cfg = make_config(); cfg.extra['search_plan'] = plan
    f = recall_filter(lambda t: t == 'Payroll Officer', cfg)
    assert f('Payroll Officer') and f('Senior Bookkeeper - urgent')
    assert f('Data Analysis Consultant') and not f('Bookkeepers') and not f('Barista')
    assert title_matches_plan('Bookkeeper', plan)


def test_plan_storage_is_private_and_per_person():
    from jobwatch import users
    plan = search_plan(policy(), hyps('Accountant'))
    save_plan('fixture-a', plan)
    assert load_plan('fixture-a') == plan and load_plan('fixture-b') is None
    path = users.user_dir('fixture-a') / 'discovery/search-plan.json'
    assert path.stat().st_mode & 0o777 == 0o600
    payload = json.loads(path.read_text()); payload['policy_hash'] = 'tampered'
    path.write_text(json.dumps(payload))
    assert load_plan('fixture-a') is None


def test_defaults_and_flag_separation():
    cfg = make_config()
    d = settings(cfg)
    assert (d['search_plan'], d['relevance'], d['dedupe'], d['ordering']) == (False, 'shadow', 'legacy', 'legacy')
    assert prepare_run(None, cfg) is cfg
    cfg.settings['pipeline'] = {'agentic': {'relevance': 'on'}, 'discovery': {'similar_at': .7}}
    assert settings(cfg)['similar_at'] == .7 and settings(cfg)['relevance'] == 'on'


@pytest.mark.parametrize('key,value', [('relevance', 'sometimes'), ('search_plan', 1),
    ('similar_at', 1.5), ('screen_per_run', True), ('screen_token_ceiling', 0)])
def test_invalid_settings_refused(key, value):
    from jobwatch.occupations import DiscoveryError
    block = 'agentic' if key in ('relevance', 'search_plan') else 'discovery'
    with pytest.raises(DiscoveryError, match='invalid_configuration'):
        settings({'pipeline': {block: {key: value}}})
