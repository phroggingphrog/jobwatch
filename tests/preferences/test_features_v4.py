"""Synthetic factual feature and current utility contracts."""
import copy
import hashlib
from datetime import date

import pytest

from jobwatch.preferences import PreferenceError
from jobwatch.preferences.features import (FEATURE_VERSION, NAMES, PRIOR_MEANS,
    alternative_from_evaluation, validate_alternatives)
from tests.preferences.test_core import CTX, alternative
from tests.test_agentic_gate import evaluation as evaluation_fixture


def evaluation():
    return evaluation_fixture.__wrapped__()


def make_alt(*, text=None, posting=None, approved=None, held=False, **facts):
    from pipeline.agentic.contracts import AgenticGateDecision
    ev = evaluation()
    if facts:
        ev = ev.model_copy(update={'facts': ev.facts.model_copy(update=facts)})
    if text is not None:
        key = ev.run_key.model_copy(update={'ad_hash': hashlib.sha256(text.encode()).hexdigest()})
        ev = ev.model_copy(update={'run_key': key,
            'requirements':ev.requirements.model_copy(update={'ad_hash':key.ad_hash})})
    gate = AgenticGateDecision(route='hold' if held else 'draft',
        reason='insufficient_evidence' if held else 'eligible', global_score=4, run_key=ev.run_key)
    return alternative_from_evaluation(ev, title='Synthetic vacancy', company='Synthetic employer',
        profile_hash='b'*64, gate=gate, posting=posting, ad_text=text, approved=approved)


def test_v4_neutral_and_held_is_never_eligible():
    assert FEATURE_VERSION.startswith('choice-features-v4')
    assert 'automation_angle' not in NAMES and 'status_held' in NAMES
    assert set(PRIOR_MEANS) == {0.}
    row = make_alt(held=True)
    assert row['status'] == 'held' and row['eligible'] is False
    assert row['features']['status_held'] == 1
    assert make_alt()['features']['status_held'] == 0
    rows=[make_alt(held=True)]
    validate_alternatives(rows, size=None)
    rows[0]['eligible']=True
    with pytest.raises(PreferenceError): validate_alternatives(rows, size=None)


def test_arbitrary_bounded_alternatives_preserve_three_default():
    rows=[alternative(i) for i in range(1,9)]
    assert len(validate_alternatives(rows, size=None)) == 8
    with pytest.raises(PreferenceError, match='three_alternatives_required'):
        validate_alternatives(rows)
    for invalid in ([], [alternative(i) for i in range(1,102)]):
        with pytest.raises(PreferenceError): validate_alternatives(invalid, size=None)


def test_hourly_salary_and_frozen_provider_age():
    posting={'salary_min':30, 'salary_max':40, 'salary_unit':'hour', 'salary_text':'AUD 30–40 per hour',
             'posted_at':'2026-01-01T00:00:00Z', 'first_seen_at':'2026-01-10T12:00:00Z',
             'posted_at_source':'provider'}
    row=make_alt(posting=posting)
    assert (row['features']['pay_low_c'],row['features']['pay_high_c']) == (30,40)
    assert row['features']['age_days'] == 9
    assert row['feature_sources']['pay_low_c']
    assert row['source_provenance']['posting_hash']
    for change in ({'salary_text':'USD 30–40 per hour'}, {'salary_unit':'year'}, {'salary_text':'$30–40 per hour'}):
        assert make_alt(posting={**posting,**change})['features']['pay_low_c'] is None
    assert make_alt(posting={**posting, 'posted_at_source':'observed'})['features']['age_days'] is None
    assert make_alt(posting={**posting,'first_seen_at':'2027-01-01T00:00:00Z'})['features']['age_days'] == 90


def test_conversion_requires_exact_source_hours_and_verified_ad():
    posting={'salary_min':1200,'salary_max':1600,'salary_unit':'week','salary_text':'AUD 1200–1600/week'}
    row=make_alt(posting=posting,text='Full time, 40 hours per week.')
    assert (row['features']['pay_low_c'],row['features']['pay_high_c']) == (30,40)
    assert make_alt(posting=posting,text='Full time.')['features']['pay_low_c'] is None
    ev=evaluation()
    from pipeline.agentic.contracts import AgenticGateDecision
    gate=AgenticGateDecision(route='draft',reason='eligible',global_score=4,run_key=ev.run_key)
    with pytest.raises(PreferenceError,match='ad_hash_mismatch'):
        alternative_from_evaluation(ev,title='X',company='Y',profile_hash='b'*64,gate=gate,ad_text='changed')


@pytest.mark.parametrize('text,flex,visa',[
    ('Full time with flexible working hours. Visa holders are welcome to apply.',1,1),
    ('Full time with fixed working hours. Visa sponsorship is not available.',0,None),
    ('Full time. A flexible and welcoming workplace.',None,None),
    ('Full time, no flexible working hours. Visa holders are not welcome.',0,None),
])
def test_explicit_positive_negative_ad_facts(text,flex,visa):
    row=make_alt(text=text,hours='full_time_only')
    assert row['features']['hours_flexible_full_time'] == flex
    assert row['features']['rights_welcomes_visa'] == visa
    for name,value in row['features'].items():
        assert (name in row['missing_features']) == (value is None)
        if value is not None: assert name in row['feature_sources']


def test_exact_approved_tenure_merges_overlaps_and_pins_present():
    from jobwatch.preferences.experience import candidate_years
    approved={'confirmed_at':'2024-01-01T12:00:00Z','facts':[
        {'id':'r1','section':'experience','basis':'evidence','value':{
            'start_date':'2020-01-01','end_date':'2022-01-01','role_family':'accounting'}},
        {'id':'r2','section':'experience','basis':'evidence','value':{
            'start_date':'2021-01-01','end_date':'Present','role_family':'accounting'}}]}
    assert candidate_years(approved) == pytest.approx(4.,abs=.01)
    assert candidate_years(approved,family='accounting') == pytest.approx(4.,abs=.01)
    assert candidate_years(approved,family='engineering') is None
    assert candidate_years({'facts':approved['facts']}) is None  # Present has no approved end date
    for date_text in ('2020','Jan 2020','2020-01'):
        unknown=copy.deepcopy(approved); unknown['facts']=[unknown['facts'][0]]
        unknown['facts'][0]['value']['start_date']=date_text
        assert candidate_years(unknown) is None
    row=make_alt(approved=approved,min_years=3)
    assert row['features']['exp_shortfall'] is None  # no proved occupational requirement scope
    assert row['features']['exp_excess'] is None


@pytest.mark.parametrize('text',[
    'This job is 30–40 hours per week.', 'Work up to 40 hours per week.',
    'This job is not 40 hours per week.', 'Work approximately 40 hours per week.',
])
def test_ambiguous_hours_cannot_convert_pay(text):
    posting={'salary_min':1200,'salary_unit':'week','salary_text':'AUD 1200/week'}
    assert make_alt(posting=posting,text=text)['features']['pay_low_c'] is None


@pytest.mark.parametrize('text',[
    'Full time. Flexible hours may be available.',
    'Full time. We do not have fixed working hours.',
    'Full time. Flexible hours are available, but fixed hours are mandatory.',
])
def test_ambiguous_flexibility_stays_missing(text):
    assert make_alt(text=text,hours='full_time_only')['features']['hours_flexible_full_time'] is None


@pytest.mark.parametrize('text',[
    'Work between 37.5 and 40 hours per week.',
    'Our office is open for 40 hours per week.',
    'Office opening hours are 40 hours per week.',
    'Hours of operation: 40 hours per week.',
])
def test_salary_conversion_does_not_use_ranged_or_office_hours(text):
    posting={'salary_min':1200,'salary_unit':'week','salary_text':'AUD 1200/week'}
    assert make_alt(posting=posting,text=text)['features']['pay_low_c'] is None


@pytest.mark.parametrize('text',[
    'Full time. Flexible hours cannot be accommodated.',
    "Full time. Flexible hours aren't available.",
    'Full time. Flexible working hours are not offered.',
])
def test_explicit_flexibility_refusal_is_observed_zero(text):
    row=make_alt(text=text,hours='full_time_only')
    assert row['features']['hours_flexible_full_time'] == 0
    assert row['feature_sources']['hours_flexible_full_time']['quote'] in text
