"""Public-only acquisition with synthetic HTTP responses and real Chromium."""
import json
import time
import pytest
from datetime import datetime, timezone
from jobwatch.interview_ad import InterviewAdUnavailable
from jobwatch.interview_browser import PublicBrowserTransport,_snapshot_ad,acquire_ad,http_ad,browser_ad
URL='https://employer.example/jobs/analyst'
BODY='Analyse accounts using SQL and communicate accurate findings. '*400
class Fetcher:
    def __init__(self,body):self.body=body;self.calls=[]
    def fetch_bytes(self,url,**kwargs):self.calls.append(url);return self.body
    def fetch_document(self,url,**kwargs):
        from pipeline.agentic.research import PublicDocument
        return PublicDocument(self.fetch_bytes(url,**kwargs),'text/html; charset=utf-8')

def snapshot(**kwargs):return dict(url=URL,title='Analyst',text=BODY,**kwargs)


def test_saved_seek_job_reads_official_mirror_with_chrome_fetch(monkeypatch):
    # Seek 403s plain fetches and 308s to au.seek.com (2026-10-20): read the page with the Chrome-fingerprint fetcher.
    import json as _json
    from jobwatch import adtext
    saved = 'https://www.seek.com.au/job/95128443'
    actual = 'https://au.seek.com/job/95128443'
    redux = {"jobdetails": {"result": {"job": {"title": "Analyst", "content": "<p>" + BODY + "</p>",
                                               "advertiser": {"name": "Acme"}}}}}
    page = "<script>window.SEEK_REDUX_DATA = " + _json.dumps(redux) + ";\n</script>"
    calls = []
    def fake_get(url, allowed, **kw):
        calls.append((url, allowed))
        return actual, page
    monkeypatch.setattr(adtext, "_http_get", fake_get)
    ad = browser_ad(saved)
    assert calls == [('https://www.seek.com.au/job/95128443', ('seek.com.au', 'seek.com'))]
    assert ad.url == saved and ad.source_url == actual and ad.title == 'Analyst' and BODY.strip()[:40] in ad.text


@pytest.mark.parametrize('url', [
    'https://www.seek.com.au/job/95128443/apply',
    'https://www.seek.com.au/login',
    'https://www.seek.com.au.evil.test/job/95128443',
    'https://www.seek.com.au:8443/job/95128443',
    'https://owner@www.seek.com.au/job/95128443',
    'http://www.seek.com.au/job/95128443',
])
def test_seek_alias_scope_excludes_non_public_job_urls(url):
    from jobwatch.interview_browser import public_posting_urls
    from jobwatch.models import canonical_url
    assert public_posting_urls(url) == (canonical_url(url),)

@pytest.mark.parametrize('label', [
    'Applications close: 19 October, 2026',
    'Applications close: 19th October 2026.',
    'Job Posting End Date: 19/10/2026 (',
    'Closing date:\n19-Oct-2026',
    'Applications close on Monday 19 October 2026',
    'Closing date: 2026-10-19',
])
def test_explicit_past_closing_date_rejects_still_visible_ad(label):
    data=snapshot();data['text'] += '\n'+label
    with pytest.raises(InterviewAdUnavailable,match='interview_ad_closed'):
        _snapshot_ad(URL,data,acquisition='browser',now=datetime(2026,10,21,tzinfo=timezone.utc))

def test_date_only_closing_day_remains_open_until_melbourne_day_ends():
    data=snapshot();data['text'] += '\nApplications close: 19 October 2026'
    assert _snapshot_ad(URL,data,acquisition='browser',now=datetime(2026,10,19,12,tzinfo=timezone.utc))
    with pytest.raises(InterviewAdUnavailable,match='interview_ad_closed'):
        _snapshot_ad(URL,data,acquisition='browser',now=datetime(2026,10,19,13,tzinfo=timezone.utc))

@pytest.mark.parametrize('ending', ['Closing date: 31 November 2026',
    'Closing date: 19 October 2026\nApplications close: 20 October 2026'])
def test_invalid_or_conflicting_deadlines_hold_instead_of_claiming_active(ending):
    data=snapshot();data['text'] += '\n'+ending
    with pytest.raises(InterviewAdUnavailable,match='interview_ad_unavailable'):
        _snapshot_ad(URL,data,acquisition='browser',now=datetime(2026,10,18,tzinfo=timezone.utc))

@pytest.mark.parametrize('ending', [
    'Applications close: 19 October 2026',
    'Closing date: 19 October 2026\nApplications close: 19 October 2026',
    'Posted: 19 October 2025\nEmployment began 19 October 2024.',
    'We may close before the closing date if enough applications arrive.',
])
def test_future_duplicate_and_unrelated_dates_remain_readable(ending):
    data=snapshot();data['text'] += '\n'+ending
    assert _snapshot_ad(URL,data,acquisition='browser',now=datetime(2026,10,18,tzinfo=timezone.utc))

@pytest.mark.parametrize('ending', [
    'Closing date: 19 October 2026 at noon',
    'Closing date: 19 October 2026\n9:00 am',
    'Closing date: 31 November 2026',
    'Closing date: 19 Octoberr 2026',
    'Closing date: to be confirmed',
])
def test_uncertain_deadline_cannot_fall_back_to_stale_structured_ad(ending):
    fetcher=Fetcher(b'{}')
    def uncertain(*args,**kwargs):
        data=snapshot();data['text'] += '\n'+ending
        return _snapshot_ad(URL,data,acquisition='browser',now=datetime(2026,10,18,tzinfo=timezone.utc))
    with pytest.raises(InterviewAdUnavailable,match='interview_ad_unavailable'):
        acquire_ad(URL,fetcher=fetcher,browser_reader=uncertain)
    assert not fetcher.calls

def test_real_chromium_rejects_visible_expired_deadline():
    fetcher=Fetcher(('<html><body><main><h1>Analyst</h1><p>'+BODY+
                     '</p><p>Closing date:</p><p>19 October 2000</p></main></body></html>').encode())
    with pytest.raises(InterviewAdUnavailable,match='interview_ad_closed'):
        browser_ad(URL,fetcher=fetcher)

@pytest.mark.parametrize('patch,code',[
    ({'text':'This job is no longer available. Please search other roles.'},'closed'),
    ({'text':'Copyright Careers Privacy'},'incomplete'),
    ({'title':'Verify you are human'},'unavailable'),
    ({'text':'x'*100001},'too_large'),
    ({'url':'https://employer.example/jobs'},'identity_changed'),
])
def test_unusable_pages_never_become_preparation(patch,code):
    data=snapshot();data.update(patch)
    with pytest.raises(InterviewAdUnavailable,match='interview_ad_'+code):_snapshot_ad(URL,data,acquisition='browser')

def test_a_real_ad_that_mentions_a_security_check_is_not_a_block_page():
    text=BODY+' Successful applicants must pass a police and security check. Access denied to unvetted staff.'
    data=snapshot();data['text']=text
    ad=_snapshot_ad(URL,data,acquisition='browser')
    assert 'security check' in ad.text
    for short in ('Security check','Access denied. Please verify you are human.','Please sign in to continue.'):
        data=snapshot();data['text']=short
        with pytest.raises(InterviewAdUnavailable,match='interview_ad_unavailable'):_snapshot_ad(URL,data,acquisition='browser')

class Request:
    method='GET';resource_type='document';url=URL
class Route:
    def __init__(self):self.request=Request();self.aborted=False;self.fulfilled=None
    def abort(self):self.aborted=True
    def fulfill(self,**kwargs):self.fulfilled=kwargs

@pytest.mark.parametrize('kind',['post','image','deadline','request_limit','byte_limit'])
def test_browser_transport_blocks_nonread_actions_and_exhaustion(kind):
    fetcher=Fetcher(b'page');transport=PublicBrowserTransport(fetcher,time.monotonic()+10);route=Route()
    if kind=='post':route.request.method='POST'
    if kind=='image':route.request.resource_type='image'
    if kind=='deadline':transport.deadline=0
    if kind=='request_limit':transport.requests=250
    if kind=='byte_limit':transport.bytes=8_000_000
    transport.route(route)
    assert route.aborted and not fetcher.calls

def test_http_fallback_requires_matching_structured_job_and_labels_unconfirmed():
    job={'@type':'JobPosting','url':URL,'title':'Analyst','description':BODY,'hiringOrganization':{'name':'Example'}}
    fetcher=Fetcher(('<script type="application/ld+json">'+json.dumps(job)+'</script>').encode())
    ad=http_ad(URL,fetcher=fetcher)
    assert ad.text==BODY.strip() and ad.company=='Example'
    assert ad.acquisition=='unconfirmed (fetched without browser)'
    job['url']='https://employer.example/jobs/other'
    with pytest.raises(InterviewAdUnavailable,match='incomplete'):
        http_ad(URL,fetcher=Fetcher(('<script type="application/ld+json">'+json.dumps(job)+'</script>').encode()))

def test_closed_browser_never_falls_through_to_stale_http():
    fetcher=Fetcher(b'{}')
    def closed(*a,**kw):raise InterviewAdUnavailable('interview_ad_closed')
    with pytest.raises(InterviewAdUnavailable,match='closed'):acquire_ad(URL,fetcher=fetcher,browser_reader=closed)
    assert fetcher.calls==[]

def test_real_chromium_reads_visible_whole_ad_and_excludes_navigation():
    fetcher=Fetcher(('<html><head><title>Analyst</title></head><body><nav>NOT AD</nav><main><h1>Analyst</h1><p>'+BODY+'</p><p hidden>HIDDEN</p></main><footer>FOOTER</footer></body></html>').encode())
    ad=browser_ad(URL,fetcher=fetcher)
    assert ad.acquisition=='browser' and len(ad.text)>16000 and BODY.strip() in ad.text
    assert 'NOT AD' not in ad.text and 'HIDDEN' not in ad.text and 'FOOTER' not in ad.text
    assert fetcher.calls==[URL]


def test_acquisition_prefers_structured_record_without_starting_browser():
    fetcher=Fetcher(json.dumps({'id':123,'title':'Analyst','content':BODY}).encode())
    def forbidden(*a,**kw):raise AssertionError('browser must not start')
    ad=acquire_ad('https://boards.greenhouse.io/example/jobs/123',fetcher=fetcher,browser_reader=forbidden)
    assert ad.acquisition=='structured_ats' and len(fetcher.calls)==1


def test_unavailable_browser_uses_explicitly_unconfirmed_fallback():
    job={'@type':'JobPosting','url':URL,'title':'Analyst','description':BODY}
    fetcher=Fetcher(('<script type="application/ld+json">'+json.dumps(job)+'</script>').encode())
    def unavailable(*a,**kw):raise InterviewAdUnavailable('interview_ad_unavailable')
    ad=acquire_ad(URL,fetcher=fetcher,browser_reader=unavailable)
    assert ad.acquisition=='unconfirmed (fetched without browser)' and fetcher.calls==[URL]


@pytest.mark.parametrize('text',['Applications closed.','This position is closed.','This job is no longer available.'])
def test_visible_closure_outside_ad_root_is_terminal(text):
    with pytest.raises(InterviewAdUnavailable,match='closed'):
        _snapshot_ad(URL,snapshot(page_text=text+' '+BODY),acquisition='browser')

def test_readable_ad_with_form_captcha_is_not_a_blocked_page():
    data=snapshot(html='<form><div class="g-recaptcha"></div></form>')
    assert _snapshot_ad(URL,data,acquisition='browser').text==BODY.strip()

def test_real_chromium_checks_status_banner_outside_main():
    fetcher=Fetcher(('<html><body><aside>Applications closed.</aside><main><h1>Analyst</h1><p>'+BODY+'</p></main></body></html>').encode())
    with pytest.raises(InterviewAdUnavailable,match='closed'):browser_ad(URL,fetcher=fetcher)

def test_browser_preserves_upstream_charset():
    from pipeline.agentic.research import PublicDocument
    class Latin(Fetcher):
        def fetch_document(self,url,**kwargs):return PublicDocument(self.body,'text/html; charset=iso-8859-1')
    fetcher=Latin(('<html><main><h1>Analyst</h1><p>Café '+BODY+'</p></main></html>').encode('latin-1'))
    assert 'Café' in browser_ad(URL,fetcher=fetcher).text


def test_transport_does_not_relabel_xhr_as_json():
    from pipeline.agentic.research import PublicDocument
    class Plain:
        def fetch_document(self,*a,**kw):return PublicDocument(b'plain','text/plain; charset=utf-8')
    route=Route();route.request.resource_type='xhr'
    PublicBrowserTransport(Plain(),time.monotonic()+10).route(route)
    assert route.fulfilled['content_type']=='text/plain; charset=utf-8'


@pytest.mark.parametrize('status,closed',[(404,True),(410,True),(403,False),(429,False),(503,False)])
def test_explicit_document_status_is_closed_only_for_missing_or_gone(status,closed):
    from pipeline.agentic.research import PublicHTTPStatus
    class Error:
        def fetch_document(self,*a,**kw):raise PublicHTTPStatus(status)
    route=Route();transport=PublicBrowserTransport(Error(),time.monotonic()+5,URL)
    transport.route(route)
    assert route.aborted and transport.closed_document is closed


def test_missing_subresource_does_not_close_the_posting():
    from pipeline.agentic.research import PublicHTTPStatus
    class Error:
        def fetch_document(self,*a,**kw):raise PublicHTTPStatus(404)
    route=Route();route.request.url=URL+'/frame'
    transport=PublicBrowserTransport(Error(),time.monotonic()+5,URL);transport.route(route)
    assert not transport.closed_document


def test_real_browser_404_produces_closed_and_never_http_fallback():
    from pipeline.agentic.research import PublicHTTPStatus
    class Gone:
        def fetch_document(self,*a,**kw):raise PublicHTTPStatus(404)
        def fetch_bytes(self,*a,**kw):raise AssertionError('closed browser must not fall through')
    with pytest.raises(InterviewAdUnavailable,match='interview_ad_closed'):
        acquire_ad(URL,fetcher=Gone())


@pytest.mark.parametrize('hidden', ['hidden','aria-hidden="true"','style="display:none"','style="visibility:hidden"','style="opacity:0"'])
def test_real_chromium_uses_visible_job_heading_not_hidden_other_job(hidden):
    fetcher=Fetcher(('<html><head><title>Careers</title></head><body><main>'
        '<section '+hidden+'><h1>Electrical Engineering Internship</h1><p>Other role</p></section>'
        '<section><h1>Finance Internship</h1><p>'+BODY+'</p></section></main></body></html>').encode())
    ad=browser_ad(URL,fetcher=fetcher)
    assert ad.title=='Finance Internship'
    assert 'Electrical Engineering Internship' not in ad.text


@pytest.mark.parametrize('script_bytes,readable', [(2_400_000, True), (3_100_000, False)])
def test_default_public_browser_bounds_required_large_ats_script(monkeypatch, script_bytes, readable):
    import pipeline.agentic.research as research
    html = b'<html><head><title>Analyst</title></head><body><script src="/app.js"></script></body></html>'
    code = ('document.body.innerHTML=' + json.dumps('<main><h1>Analyst</h1><p>'+BODY+'</p></main>') + ';').encode()
    script = code + b'/*' + b'x'*(script_bytes-len(code)-4) + b'*/'
    assert len(script) == script_bytes
    calls = []
    def connector(url, **kwargs):
        calls.append(kwargs)
        payload, kind = (script, 'application/javascript') if url.endswith('/app.js') else (html, 'text/html')
        return research.PublicDocument(payload, kind)
    monkeypatch.setattr(research.SafeFetcher, '_resolve', staticmethod(lambda host: ['8.8.8.8']))
    monkeypatch.setattr(research, '_pinned_https_fetch', connector)
    if readable:
        assert BODY.strip() in browser_ad(URL).text
    else:
        with pytest.raises(InterviewAdUnavailable):
            browser_ad(URL)
    assert len(calls) == 2
    assert all(c['addresses'] == ('8.8.8.8',) and not c['allow_redirects'] and not c['trust_env'] for c in calls)
    # Raising the browser cap must not raise the separate public research cap.
    with pytest.raises(research.ResearchUnavailable):
        research.SafeFetcher().fetch_bytes(URL.replace('/jobs/analyst','/app.js'))


def test_close_label_with_no_date_states_no_deadline():
    from datetime import datetime, timezone
    from jobwatch.interview_browser import _closing_date
    _closing_date("Advertised:\n01 Sep 2026\nApplications close:\n← Back to search results\nApply now",
                  datetime(2026, 10, 12, tzinfo=timezone.utc))  # PageUp open-until-filled: no exception


def test_same_host_redirect_is_handed_to_the_browser_other_hosts_are_not():
    from pipeline.agentic.research import PublicHTTPStatus
    def go(location,status=302):
        class Redirect:
            def fetch_document(self,*a,**kw):raise PublicHTTPStatus(status,location)
        route=Route();transport=PublicBrowserTransport(Redirect(),time.monotonic()+5,URL);transport.route(route)
        return route,transport
    from urllib.parse import urlsplit;host=urlsplit(URL).hostname
    route,transport=go('/job/x/12-en_GB/')
    assert transport.redirected and route.fulfilled['status']==302 and not route.aborted
    route,transport=go('https://other.example/search')
    assert route.aborted and not transport.redirected
    route,transport=go('http://'+host+'/job/x')
    assert route.aborted and not transport.redirected


def test_unreadable_backoff_after_three_same_failures():
    import sqlite3
    from pipeline.agentic.service import _unreadable_backoff
    c=sqlite3.connect(':memory:')
    c.execute('create table agentic_runs(run_key,posting_id,status,reason,checkpoint_json)')
    def add(reason,deadline):c.execute('insert into agentic_runs values(?,?,?,?,?)',('k',1,'held',reason,'{"job_deadline":%s}'%deadline))
    for _ in range(2):add('posting_unavailable',1000)
    assert not _unreadable_backoff(c,1,now=1500)            # only 2 failures
    add('posting_unavailable',1000)
    assert _unreadable_backoff(c,1,now=1500)                # 3 in a row, recent
    assert not _unreadable_backoff(c,1,now=1000+13*3600)    # the wait has passed
    add('snapshot_changed',1000)
    assert not _unreadable_backoff(c,1,now=1500)            # a different outcome resets it


@pytest.mark.parametrize('location,closed',[('/621/cw/en/listing/?jobnotfound=true',True),('https://jobs.example.com.au',True),
                                            ('/other/page',False)])
def test_pageup_redirect_for_a_gone_vacancy_is_closed(location,closed):
    from pipeline.agentic.research import PublicHTTPStatus
    class Gone:
        def fetch_document(self,*a,**kw):raise PublicHTTPStatus(302,location)
    url='https://careers.pageuppeople.com/621/cw/en/job/524618'
    route=Route();route.request.url=url
    transport=PublicBrowserTransport(Gone(),time.monotonic()+5,url);transport.route(route)
    assert transport.closed_document is closed


# Regression: ISSUE-001 — "28th of October 2026" read "of" as the month and crashed (TypeError), so the ad was
# marked unreadable. Found by /qa on 2026-10-19 (posting 7535, careers.vic.gov.au).
def test_closing_date_with_of_between_day_and_month():
    from jobwatch.interview_browser import _closing_date
    _closing_date("Application close date: Wednesday 28th of October 2026\n",
                  datetime(2026, 10, 19, tzinfo=timezone.utc))  # still open: no exception


# Regression: Workday "Applications close: Monday 26th October at 11:55 PM; Melbourne time zone." was read as an
# ambiguous deadline, so the whole ad was marked unreadable (unimelb, posting 1718).
def test_closing_date_with_time_and_melbourne_zone():
    import pytest
    from jobwatch.interview_browser import InterviewAdUnavailable, _closing_date
    text = "Applications close: Monday 26th October at 11:55 PM; Melbourne time zone.\nPosition Description:"
    _closing_date(text, datetime(2026, 10, 19, tzinfo=timezone.utc))  # still open: no exception
    with pytest.raises(InterviewAdUnavailable, match='interview_ad_closed'):
        _closing_date(text, datetime(2026, 10, 27, tzinfo=timezone.utc))


# Regression: Jora "Applications close: 11th November 2026 - don't miss out!" was read as an ambiguous deadline,
# so every such Jora ad stayed "couldn't read".
def test_closing_date_with_trailing_slogan_jora():
    import pytest
    from jobwatch.interview_browser import InterviewAdUnavailable, _closing_date
    text = "Duties\nApplications close: 11th November 2026 - don’t miss out!\nFor further information please contact:"
    _closing_date(text, datetime(2026, 10, 19, tzinfo=timezone.utc))  # still open: no exception
    with pytest.raises(InterviewAdUnavailable, match='interview_ad_closed'):
        _closing_date(text, datetime(2026, 11, 12, tzinfo=timezone.utc))
