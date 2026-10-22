"""Synthetic collector regressions for confirmed, person-specific scopes."""
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from conftest import FakeHttp, make_ctx
from jobwatch.collectors import ats_oracle, ats_workday, jobspy_src, jora, reddit, seek
from jobwatch.occupations import plan as plans


def policy(**kwargs):
    return SimpleNamespace(profile_version=1, policy_hash='a' * 64, focus=('nurse',),
        home=None, regions=(), remote_ok=False, **kwargs)


def scope_plan():
    return plans.search_plan(policy(), [], extra_locations=('Sydney, NSW', 'Perth, WA'))


@pytest.mark.parametrize('collector', ['seek', 'jora', 'jobspy'])
def test_every_confirmed_location_gets_a_bounded_rotated_search(collector, monkeypatch):
    searches = plans.searches_overlay(scope_plan(), {collector: {'searches_per_run': 1,
        'pause_seconds': 0, 'delay_s': 0}}, policy())
    ctx = make_ctx(FakeHttp({'seek.com.au': {'data': []}}), searches=searches)
    calls = []
    if collector == 'seek':
        for _ in range(2):
            seek.collect(ctx)
        calls = [c[2]['where'] for c in ctx.http.calls]
    elif collector == 'jora':
        def get(url, **kwargs):
            calls.append(parse_qs(urlparse(url).query)['l'][0])
            return SimpleNamespace(status_code=200, text='')
        monkeypatch.setattr('curl_cffi.requests.get', get)
        for _ in range(2):
            jora.collect(ctx)
    else:
        def scrape(**kwargs):
            calls.append(kwargs['location'])
            return pd.DataFrame()
        for _ in range(2):
            jobspy_src.collect(ctx, scrape=scrape)
    assert calls == ['Sydney, NSW', 'Perth, WA']


def test_overlay_clears_inherited_remote_and_unknown_home():
    base = {'location': 'Melbourne, VIC', 'seek': {'where': 'Melbourne',
        'remote': {'enabled': True, 'keywords': ['accountant']}},
        'jora': {'where': 'Melbourne'}, 'jobspy': {'location': 'Melbourne'}}
    out = plans.searches_overlay(plans.search_plan(policy(), []), base, policy())
    assert out['seek'].get('remote', {}).get('enabled') is not True
    assert 'Melbourne' not in str(out)
    assert base['seek']['remote']['enabled'] is True


def test_jobspy_missing_home_does_not_invent_a_city():
    seen = []
    ctx = make_ctx(FakeHttp({}), searches={'jobspy': {'searches': [{'term': 'nurse'}]}})
    jobspy_src.collect(ctx, scrape=lambda **kwargs: seen.append(kwargs) or pd.DataFrame())
    assert seen[0]['location'] is None
    assert 'near None' not in seen[0]['google_search_term']


def workday_ctx(*, detail_cap=1):
    rows = [{'externalPath': f'/job/Multiple-Locations/Role_{i}', 'title': title,
             'locationsText': '2 Locations', 'bulletFields': [str(i)]}
            for i, title in enumerate(('Nurse', 'Operations Partner'))]
    http = FakeHttp({'/jobs': {'jobPostings': rows, 'total': 2},
        '/job/': {'jobPostingInfo': {'country': {'alpha2Code': 'AU'},
            'location': 'Sydney NSW', 'jobDescription': 'Nursing and patient care'}}})
    ctx = make_ctx(http, [{'name': 'Synthetic', 'provider': 'workday', 'tenant': 'synthetic',
        'host': 'example.invalid', 'site': 'careers', 'detail_cap': detail_cap}])
    ctx.title_relevant = lambda title: title == 'Nurse'
    return ctx


def test_workday_titles_prioritize_but_never_drop_unknown_listings():
    ctx = workday_ctx()
    rows = ats_workday.collect(ctx)
    assert len(rows) == 2
    assert rows[0].description and not rows[1].description
    assert rows[1].location == '' and rows[1].state is None
    ats_workday.collect(ctx)
    details = [url for method, url, _ in ctx.http.calls if method == 'GET']
    assert len(details) == 2 and details[1].endswith('Role_1')


def test_workday_persisted_unknown_listings_still_get_their_detail_turn():
    ctx = workday_ctx()
    first = ats_workday.collect(ctx)
    known = {(p.source, p.source_id) for p in first}
    ctx.is_known = lambda source, source_id: (source, source_id) in known
    second = ats_workday.collect(ctx)
    assert second[1].description
    details = [url for method, url, _ in ctx.http.calls if method == 'GET']
    assert len(details) == 2 and details[1].endswith('Role_1')


def test_workday_unknown_country_is_not_treated_as_foreign_or_australian():
    employer = {'tenant': 'synthetic', 'host': 'example.invalid', 'site': 'careers'}
    row = {'externalPath': '/job/Somewhere/Role', 'title': 'Role', 'locationsText': '2 Locations'}
    p = ats_workday.row_to_posting(row, employer, {'jobPostingInfo': {'jobDescription': 'Complete duties'}})
    assert p is not None and p.location == '' and p.state is None
    assert ats_workday.row_to_posting(row, employer,
        {'jobPostingInfo': {'country': {'alpha2Code': 'US'}, 'location': 'Seattle'}}) is None


def test_jora_missing_posting_location_does_not_copy_persons_home():
    page = '<div data-job-card="true"><a class="job-link-desktop-only" href="/job/test">Nurse</a></div>'
    assert jora.parse(page)[0].location == ''


def test_oracle_keeps_provider_order_and_all_region_evidence():
    req = {'Id': 1, 'PrimaryLocation': 'Sydney NSW ' + 'Campus ' * 40,
        'PrimaryLocationCountry': 'AU', 'secondaryLocations': [
            {'Name': 'Perth WA', 'CountryCode': 'AU'}, {'Name': 'Melbourne VIC', 'CountryCode': 'AU'}]}
    assert ats_oracle._locations(req)[0][0].startswith('Sydney')
    p = ats_oracle.req_to_posting(req, {'host': 'example.invalid', 'site': 'careers'})
    assert all(state in p.location for state in ('NSW', 'WA', 'VIC'))


def test_reddit_approved_scope_replaces_shared_geography_and_queries():
    p = policy()
    p.regions = ('NSW', 'WA')
    base = {'reddit': {'hiring_keywords': ['hiring'], 'hiring_location': ['melbourne'],
        'feeds': [{'sub': 'melbourne', 'location': 'Melbourne VIC'},
                  {'sub': 'australia', 'q': 'melbourne OR accountant'}]}}
    out = plans.feeds_overlay(scope_plan(), base, p)
    conf = out['reddit']
    assert [f['sub'] for f in conf['feeds']] == ['australia']
    assert 'melbourne' not in str(conf).lower() and 'accountant' not in str(conf).lower()
    assert reddit.classify('[hiring] Nurse', 'Sydney NSW', conf)[0] == 'hiring'
    assert reddit.classify('[hiring] Nurse', 'Melbourne VIC', conf)[0] is None
    assert reddit.classify('[hiring] Nurse', 'Remote Australia', conf)[0] is None


def test_reddit_unknown_location_does_not_invent_remote_australia():
    xml = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>1</id><title>[hiring] Nurse</title>' \
          '<content type="html">New position</content><link href="https://example.invalid"/></entry></feed>'
    conf = {'hiring_keywords': ['hiring'], 'hiring_location': [], '_profile_scope': [], '_remote_ok': None}
    posts, _ = reddit.parse(xml, {'sub': 'example'}, conf)
    assert len(posts) == 1 and posts[0].location == '' and posts[0].remote is False


def test_reddit_local_source_cannot_override_explicit_posting_geography():
    conf = {'hiring_keywords': ['hiring'], '_profile_scope': ['Sydney NSW'],
        '_profile_regions': ['NSW'], '_remote_ok': False}
    assert reddit.classify('[hiring] Nurse', 'Melbourne VIC', conf, local=True)[0] is None


def test_approved_regions_are_searched_when_home_is_unknown():
    p = policy()
    p.regions = ('NSW', 'WA')
    plan = plans.search_plan(p, [])
    assert plan.locations == ('NSW', 'WA')


def test_remote_search_shares_request_cap_and_rotates_after_local_scope():
    p = policy()
    p.home = {'place': 'Sydney', 'state': 'NSW', 'country': 'Australia'}
    p.remote_ok = True
    searches = plans.searches_overlay(plans.search_plan(p, []), {'seek': {'searches_per_run': 1}}, p)
    ctx = make_ctx(FakeHttp({'seek.com.au': {'data': []}}), searches=searches)
    for _ in range(2):
        seek.collect(ctx)
    calls = [c[2] for c in ctx.http.calls]
    assert [c['where'] for c in calls] == ['Sydney, NSW', 'Australia']
    assert calls[1]['workarrangement'] == 3
