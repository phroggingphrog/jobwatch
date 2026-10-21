from datetime import datetime,timezone
import pytest
from jobwatch.interview_ad import InterviewAd,InterviewAdUnavailable
from pipeline.agentic.liveness import observe_posting,PostingObservation
from pydantic import ValidationError

URL='https://example.test/job/1'
BODY='Reconcile accounts and prepare analysis for finance colleagues. '*30
POST={'id':1,'url':URL,'title':'Graduate analyst'}

def reader(*args,**kwargs):return InterviewAd(URL,URL,'Graduate analyst','Example',BODY,'2026-10-11T00:00:00+00:00','browser')

def test_active_observation_binds_full_current_source_without_candidate_data():
    seen=[]
    def capture(url,**kwargs):seen.append((url,kwargs));return reader()
    observed=observe_posting(POST,reader=capture)
    assert observed.status=='active' and observed.text==BODY and len(observed.ad_hash)==64
    assert seen==[(URL,{'fetcher':None,'deadline':None})]
    assert BODY not in repr(observed) and URL not in repr(observed)

@pytest.mark.parametrize('code,status',[('interview_ad_closed','closed'),('interview_ad_unavailable','unknown'),('interview_ad_incomplete','unknown'),('interview_ad_identity_changed','unknown')])
def test_nonlive_pages_never_supply_evaluation_text(code,status):
    def unavailable(*a,**kw):raise InterviewAdUnavailable(code)
    result=observe_posting(POST,reader=unavailable)
    assert result.status==status and result.text=='' and result.ad_hash is None

@pytest.mark.parametrize('title,source,acquisition',[
    ('Other role',URL,'browser'),('Graduate analyst','https://example.test/jobs','browser'),
    ('Graduate analyst',URL,'unconfirmed (fetched without browser)')])
def test_unverified_identity_or_fallback_cannot_pass_gate(title,source,acquisition):
    def changed(*a,**kw):return InterviewAd(URL,source,title,'Example',BODY,'2026-10-11T00:00:00+00:00',acquisition)
    assert observe_posting(POST,reader=changed).status=='unknown'

def test_observation_rejects_modified_ad_bytes():
    observed=observe_posting(POST,reader=reader)
    with pytest.raises(ValidationError):PostingObservation.model_validate({**observed.model_dump(),'text':BODY+' altered'})


def test_seek_public_mirror_preserves_saved_identity_and_actual_source():
    from jobwatch.candidate.contracts import content_hash
    from pipeline.agentic.liveness import observation_current
    saved = 'https://www.seek.com.au/job/95128443'
    actual = 'https://au.seek.com/job/95128443'
    def mirrored(*args, **kwargs):
        return InterviewAd(saved, actual, POST['title'], 'Example', BODY,
                           '2026-10-11T00:00:00+00:00', 'browser')
    observed = observe_posting({**POST, 'url': saved}, reader=mirrored)
    assert observed.status == 'active' and observed.source_url == actual
    assert observed.url_hash == content_hash(saved.encode())
    assert observation_current(observed, posting_id=1, url=saved, ad_hash=observed.ad_hash)
    assert not observation_current(observed, posting_id=1, url=actual, ad_hash=observed.ad_hash)


@pytest.mark.parametrize('source', [
    'https://au.seek.com/job/95128444',
    'https://au.seek.com/job/95128443?different=1',
    'https://au.seek.com.evil.test/job/95128443',
    'https://au.seek.com:8443/job/95128443',
    'http://au.seek.com/job/95128443',
    'https://au.seek.com/job/95128443/apply',
])
def test_seek_mirror_never_accepts_other_job_query_host_port_scheme_or_application(source):
    saved = 'https://www.seek.com.au/job/95128443'
    def changed(*args, **kwargs):
        return InterviewAd(saved, source, POST['title'], 'Example', BODY,
                           '2026-10-11T00:00:00+00:00', 'browser')
    assert observe_posting({**POST, 'url': saved}, reader=changed).status == 'unknown'


def test_latest_observation_absent_table_is_unknown():
    import sqlite3
    from pipeline.agentic.liveness import latest_observation
    assert latest_observation(sqlite3.connect(':memory:'),1) is None


@pytest.mark.parametrize('age,ident,url,ad_hash,expected',[
    (0,1,URL,None,True),(86401,1,URL,None,False),(-1,1,URL,None,False),
    (0,2,URL,None,False),(0,1,URL+'/other',None,False),(0,1,URL,'a'*64,False)])
def test_current_observation_requires_fresh_exact_source(age,ident,url,ad_hash,expected):
    from datetime import timedelta
    from pipeline.agentic.liveness import observation_current
    now=datetime.now(timezone.utc)
    observation=observe_posting(POST,reader=reader,now=now-timedelta(seconds=age))
    assert observation_current(observation,posting_id=ident,url=url,
                               ad_hash=ad_hash or observation.ad_hash,now=now) is expected


def test_unexpected_transport_failure_is_unknown_without_error_details():
    def broken(*a,**kw):raise OSError('sensitive transport details')
    result=observe_posting(POST,reader=broken)
    assert result.status=='unknown' and result.reason=='posting_unavailable'
    assert 'sensitive' not in result.model_dump_json()


def test_fresh_observation_expires_at_closing_day_boundary_without_refetch():
    from pipeline.agentic.liveness import observation_current
    checked=datetime(2026,10,19,12,tzinfo=timezone.utc)  # 23:00 Melbourne
    def closing_reader(*args,**kwargs):
        return InterviewAd(URL,URL,'Graduate analyst','Example',
                           BODY+'\nApplications close: 19 October 2026',checked.isoformat(),'browser')
    observation=observe_posting(POST,reader=closing_reader,now=checked)
    args=dict(posting_id=1,url=URL,ad_hash=observation.ad_hash)
    assert observation_current(observation,**args,now=checked)
    # Only one hour old, but no longer valid for READY or form preparation.
    assert not observation_current(observation,**args,now=datetime(2026,10,19,13,tzinfo=timezone.utc))


WORKDAY='https://example.wd3.myworkdayjobs.com/en-US/Careers/job/Melbourne/Analyst_R123'


def workday_fetcher(**overrides):
    import json
    record={'title':'Graduate analyst','jobDescription':BODY,'jobReqId':'R123',
            'externalUrl':WORKDAY,'posted':True,'canApply':True,'location':'Melbourne, Victoria',
            'timeType':'Part time'}
    record.update(overrides)
    class Fetcher:
        def fetch_bytes(self,url,**kw):
            assert url=='https://example.wd3.myworkdayjobs.com/wday/cxs/example/Careers/job/Melbourne/Analyst_R123'
            return json.dumps({'jobPostingInfo':record}).encode()
    return Fetcher()


def test_workday_explicit_active_record_verifies_without_browser(monkeypatch):
    monkeypatch.setattr('pipeline.agentic.liveness.browser_ad',lambda *a,**kw:pytest.fail('browser used'))
    obs=observe_posting({**POST,'url':WORKDAY},fetcher=workday_fetcher())
    assert (obs.status,obs.reason)==('active','active_ats_posting')
    assert BODY.strip() in obs.text and 'Melbourne, Victoria' in obs.text
    assert obs.source_url==WORKDAY


@pytest.mark.parametrize('changes',[
    {'posted':False},{'posted':None},{'posted':'true'},{'canApply':False},{'canApply':None},
    {'canApply':1},{'jobReqId':'OTHER'},{'externalUrl':WORKDAY.replace('/Careers/','/OtherSite/')},
    {'externalUrl':WORKDAY.replace('example.wd3','other.wd3')},
])
def test_workday_unverified_record_cannot_become_active(monkeypatch,changes):
    def unavailable(*a,**kw):raise InterviewAdUnavailable('interview_ad_unavailable')
    monkeypatch.setattr('pipeline.agentic.liveness.browser_ad',unavailable)
    obs=observe_posting({**POST,'url':WORKDAY},fetcher=workday_fetcher(**changes))
    assert obs.status!='active'


@pytest.mark.parametrize('changes,status',[({'posted':False},'closed'),({'canApply':False},'unknown')])
def test_workday_explicit_unavailable_cannot_fall_back_to_stale_browser(monkeypatch,changes,status):
    monkeypatch.setattr('pipeline.agentic.liveness.browser_ad',lambda *a,**kw:pytest.fail('fallback bypass'))
    assert observe_posting({**POST,'url':WORKDAY},fetcher=workday_fetcher(**changes)).status==status


def test_workday_active_flags_do_not_override_visible_expired_deadline(monkeypatch):
    monkeypatch.setattr('pipeline.agentic.liveness.browser_ad',lambda *a,**kw:pytest.fail('fallback bypass'))
    observed=observe_posting({**POST,'url':WORKDAY},fetcher=workday_fetcher(
        jobDescription=BODY+'<p>Applications close: 1 January 2020</p>'))
    assert observed.status=='closed'


def test_wrong_workday_tenant_cannot_close_requested_job(monkeypatch):
    def unavailable(*a,**kw):raise InterviewAdUnavailable('interview_ad_unavailable')
    monkeypatch.setattr('pipeline.agentic.liveness.browser_ad',unavailable)
    observed=observe_posting({**POST,'url':WORKDAY},fetcher=workday_fetcher(
        externalUrl=WORKDAY.replace('example.wd3','other.wd3'),posted=False))
    assert observed.status=='unknown'


def test_workday_structured_deadline_expires_cached_observation(monkeypatch):
    from pipeline.agentic.liveness import observation_current, PostingObservation
    monkeypatch.setattr('pipeline.agentic.liveness.browser_ad',lambda *a,**kw:pytest.fail('browser used'))
    checked=datetime(2026,10,11,0,tzinfo=timezone.utc)
    obs=observe_posting({**POST,'url':WORKDAY},now=checked,fetcher=workday_fetcher(
        validThrough='2026-10-11T01:00:00Z'))
    assert obs.status=='active'
    obs=PostingObservation.model_validate_json(obs.model_dump_json())
    args=dict(posting_id=POST['id'],url=WORKDAY,ad_hash=obs.ad_hash)
    assert observation_current(obs,**args,now=checked)
    assert not observation_current(obs,**args,now=datetime(2026,10,11,1,tzinfo=timezone.utc))
    assert not observation_current(obs,**args,now=datetime(2026,10,11,2,tzinfo=timezone.utc))


def test_page_furniture_that_changes_between_reads_does_not_change_the_ad():
    from pipeline.agentic.liveness import _strip_page_chrome as strip
    a="Title\nUse AI to assess how you fit\nGet AI-powered advice.\nAm I a good fit for this job?\nTailor my resume\nBody\nGet notified about new\nCoordinator\njobs in\nPreston\n.\nSign in to create job alert\nEnd"
    b="Title\nBody\nGet notified when a new job is posted.\nSet alert\nEnd"
    assert strip(a) == strip(b) == "Title\nBody\nEnd"
    assert strip("Body\nCookie Consent Manager\nRequired Cookies") == "Body\n"
