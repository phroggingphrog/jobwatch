import pytest

from conftest import make_config
from jobwatch.candidate import policy
from jobwatch.filters import Rules
from jobwatch.models import Posting


def posting(location='', state=None, remote=False):
    return Posting(source='synthetic',source_id='1',url='https://example.invalid/1',title='Accounts Officer',location=location,state=state,remote=remote)


@pytest.mark.parametrize('home,inside,outside',[
    ('Sydney NSW','Sydney NSW','Melbourne VIC'),
    ('Melbourne VIC','Melbourne VIC','Perth WA'),
    ('Perth WA','Perth WA','Sydney NSW'),
])
def test_location_prefilter_comes_from_the_confirmed_person_without_feature_flags(monkeypatch, home, inside, outside):
    dp = policy.build_policy({'version':1,'facts':[{'id':'home','section':'location','basis':'evidence','value':home}]})
    monkeypatch.setattr(policy,'policy_for',lambda person:dp)
    cfg = make_config()
    rules = Rules(cfg.rules,cfg.employers)
    assert rules.location_rule(posting(inside)) == 'profile_region'
    assert rules.location_rule(posting(outside)) is None
    assert rules.location_rule(posting()) == 'profile_location_unknown'


def test_remote_and_missing_region_follow_confirmed_preferences(monkeypatch):
    def rules(facts):
        dp = policy.build_policy({'version':1,'facts':facts})
        monkeypatch.setattr(policy,'policy_for',lambda person:dp)
        cfg = make_config()
        return Rules(cfg.rules,cfg.employers)
    location = {'id':'home','section':'location','basis':'evidence','value':'Sydney NSW'}
    allowed = rules([location,{'id':'remote','section':'preference','basis':'evidence','value':{'remote_ok':True}}])
    assert allowed.location_rule(posting('Perth WA',remote=True)) == 'profile_remote'
    refused = rules([location,{'id':'remote','section':'preference','basis':'evidence','value':{'remote_ok':False}}])
    assert refused.location_rule(posting('Perth WA',remote=True)) is None
    # Missing location preferences are unknown, never a default home region.
    assert rules([]).location_rule(posting('Perth WA')) == 'profile_location_unknown'


def test_explicit_remote_location_is_not_lost_when_provider_omits_its_remote_flag(monkeypatch):
    dp = policy.build_policy({'version':1,'facts':[
        {'id':'home','section':'location','basis':'evidence','value':'Melbourne VIC'},
        {'id':'remote','section':'preference','basis':'evidence','value':{'remote_ok':True}}]})
    monkeypatch.setattr(policy,'policy_for',lambda person:dp)
    cfg = make_config()
    assert Rules(cfg.rules,cfg.employers).location_rule(posting('Sydney NSW — Remote')) == 'profile_remote'


def test_shared_title_arms_cannot_exclude_a_confirmed_nonaccounting_profile(monkeypatch):
    dp = policy.build_policy({'version': 1, 'facts': [
        {'id': 'scope', 'section': 'career_focus', 'basis': 'evidence', 'value': 'Engineering'},
        {'id': 'home', 'section': 'location', 'basis': 'evidence', 'value': 'Sydney NSW'}]})
    monkeypatch.setattr(policy, 'policy_for', lambda person: dp)
    cfg = make_config()
    rules = Rules(cfg.rules, cfg.employers)
    item = posting('Sydney NSW')
    item.title = 'Senior Mechanical Engineer'
    assert rules.evaluate(item).matched
    assert rules.evaluate(item).arm == 'profile_discovery'
