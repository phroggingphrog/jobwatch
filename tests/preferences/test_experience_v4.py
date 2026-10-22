"""Only explicit general-years requirements can use total approved tenure."""
import hashlib
import pytest
from jobwatch.preferences.features import alternative_from_evaluation
from pipeline.agentic.contracts import AgenticGateDecision, Requirement, RequirementSet, RequirementMatch, SourceCitation
from tests.preferences.test_features_v4 import evaluation


GENERAL='At least 3 years of overall professional experience required.'


def approved(start='2020-01-01', end='Present'):
    return {'confirmed_at':'2024-01-01T12:00:00Z','facts':[
        {'id':'role-1','section':'experience','basis':'evidence','value':{
            'start_date':start,'end_date':end,'role_family':'accounting'}}]}


def alternative(quote=GENERAL, *, profile=None, signal_hash=None, signal_source='ad',
                signal_quote=None, requirement_text=None, years=3, with_ad=True):
    ev=evaluation()
    ad='Synthetic vacancy. '+quote
    sha=hashlib.sha256(ad.encode()).hexdigest()
    key=ev.run_key.model_copy(update={'ad_hash':sha})
    req=Requirement(id='general-years',text=requirement_text or quote,tier='stated',importance='preferred',
        jd_signal=SourceCitation(source_id=signal_source,content_hash=signal_hash or sha,quote=signal_quote or quote))
    ev=ev.model_copy(update={'run_key':key,'facts':ev.facts.model_copy(update={'min_years':years}),
        'requirements':RequirementSet(ad_hash=sha,requirements=(req,)),
        'matches':(RequirementMatch(requirement_id=req.id,match='missing',evidence=()),)})
    gate=AgenticGateDecision(route='draft',reason='eligible',global_score=4,run_key=key)
    return alternative_from_evaluation(ev,title='Synthetic vacancy',company='Synthetic employer',
        profile_hash='b'*64,gate=gate,ad_text=ad if with_ad else None,
        approved=approved() if profile is None else profile)


def test_verified_overall_experience_uses_exact_approved_tenure():
    row=alternative()
    assert row['features']['exp_shortfall']==0
    assert row['features']['exp_excess']==pytest.approx(1.,abs=.01)
    source=row['feature_sources']['exp_excess']
    assert source['quote']==GENERAL and source['requirement_id']=='general-years'
    assert source['confirmed_at']=='2024-01-01T12:00:00Z'
    assert source['scope']=='explicit_overall_work_experience_v1'
    short=alternative(profile=approved('2022-01-01'))
    assert short['features']['exp_shortfall']==pytest.approx(1.,abs=.01)
    assert short['features']['exp_excess']==0


def test_canonical_jd_alias_is_the_same_verified_ad_source():
    assert alternative(signal_source='jd')['features']['exp_excess']==pytest.approx(1.,abs=.01)


@pytest.mark.parametrize('quote',[
    'At least 3 years of accounting experience required.',
    'At least 3 years of general accounting work experience required.',
    '3 years of total work experience in accounting required.',
    '3 years of total work experience, including 2 years in accounting.',
])
def test_specialist_or_mixed_experience_cannot_use_overall_tenure(quote):
    row=alternative(quote)
    assert row['features']['exp_shortfall'] is None and row['features']['exp_excess'] is None


@pytest.mark.parametrize('kwargs',[
    {'signal_hash':'c'*64}, {'with_ad':False}, {'years':4},
    {'signal_source':'cv.md'},
    {'profile':approved('2020-01','2024-01')},
    {'profile':approved('2020','2024')},
])
def test_unverified_scope_or_inexact_dates_stay_missing(kwargs):
    row=alternative(**kwargs)
    assert row['features']['exp_shortfall'] is None and row['features']['exp_excess'] is None


def test_unknown_other_role_dates_cannot_be_treated_as_zero_tenure():
    profile=approved()
    profile['facts'].append({'id':'role-2','section':'experience','basis':'evidence','value':{
        'start_date':'2018','end_date':'2019','role_family':'engineering'}})
    row=alternative(profile=profile)
    assert row['features']['exp_shortfall'] is None and row['features']['exp_excess'] is None


@pytest.mark.parametrize('kwargs',[
    {},
    {'requirement_text':'At least 3 years of overall professional experience'},
])
def test_truncated_exact_quote_cannot_hide_specialist_source_tail(kwargs):
    row=alternative('At least 3 years of overall professional experience in engineering required.',
        signal_quote='At least 3 years of overall professional experience',**kwargs)
    assert row['features']['exp_shortfall'] is None and row['features']['exp_excess'] is None


def test_wrapped_specialist_source_tail_is_not_a_new_condition():
    row=alternative('At least 3 years of overall professional experience\nin engineering required.',
        signal_quote='At least 3 years of overall professional experience',
        requirement_text='At least 3 years of overall professional experience')
    assert row['features']['exp_shortfall'] is None and row['features']['exp_excess'] is None


def test_general_source_quote_cannot_hide_specialist_frozen_requirement():
    row=alternative(requirement_text='At least 3 years of overall professional experience in engineering required.')
    assert row['features']['exp_shortfall'] is None and row['features']['exp_excess'] is None
