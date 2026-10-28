"""Ephemeral, read-only public browser acquisition for standalone interview prep."""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
import time
import json
import re
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

from jobwatch.util.adtext import _FILLED, _WALL
from jobwatch.util.place import person_timezone
from jobwatch.interview.ad import InterviewAd, InterviewAdUnavailable, MAX_AD_CHARS, ats_target, structured_ad, _plain
from jobwatch.models import canonical_url
from jobwatch.collectors.jsonld_pages import job_postings
from pipeline.agentic.research import SafeFetcher, ResearchUnavailable, PublicHTTPStatus


# Modern ATS pages require scripts larger than the research excerpt transport.
# The browser retains its separate 8 MB total and 50-request limits.
MAX_PUBLIC_DOCUMENT_BYTES = 3_000_000


def public_posting_urls(url):
    """Exact public SEEK job mirrors only; never application/login URLs.

    Keep this separate from collector canonicalization and stored URL hashes.
    The original URL remains the observation identity; its actual fetched
    mirror remains recorded as the source.
    """
    canonical = canonical_url(url)
    parts = urlsplit(canonical)
    mirrors = {'www.seek.com.au': 'au.seek.com', 'au.seek.com': 'www.seek.com.au'}
    if (parts.scheme == 'https' and parts.netloc in mirrors
            and re.fullmatch(r'/job/[0-9]+', parts.path)):
        alternate = urlunsplit((parts.scheme, mirrors[parts.netloc], parts.path, parts.query, ''))
        return (canonical, alternate)
    return (canonical,)


class PublicBrowserTransport:
    """Every browser GET uses the same IP-pinned, bounded public HTTPS reader."""
    def __init__(self, fetcher, deadline, initial_url=None):
        self.fetcher,self.deadline=fetcher,deadline
        self.initial_url=initial_url
        self.closed_document=False
        self.redirected=False     # a same-host redirect was handed to the browser (ERR_FAILED before: it was refused)
        self.requests=0
        self.bytes=0

    def route(self,route):
        request=route.request
        try:
            if request.method!='GET' or request.resource_type in ('image','media','font'):
                raise ResearchUnavailable()
            if self.requests>=250 or self.bytes>=8_000_000 or time.monotonic()>=self.deadline:
                raise ResearchUnavailable()
            self.requests+=1
            document=self.fetcher.fetch_document(request.url,deadline=self.deadline)
            body=document.body
            self.bytes+=len(body)
            if self.bytes>8_000_000:raise ResearchUnavailable()
            if request.resource_type=='document' and self.initial_url and canonical_url(request.url)==canonical_url(self.initial_url):
                # Compass's PageUp tenant ships a head script that sends direct visitors to its framed home page, which
                # the public transport refuses (chrome-error page); the ad itself is in this document.
                body=re.sub(rb'window\.location\.href\s*=\s*"[^"]*"',b'',body)
            route.fulfill(status=200,body=body,content_type=document.content_type)
        except PublicHTTPStatus as exc:
            gone=(request.resource_type=='document' and self.initial_url
                  and canonical_url(request.url)==canonical_url(self.initial_url) and self._vacancy_gone_redirect(request.url,exc))
            target=None if gone else self._same_host_redirect(request.url,exc)
            if target:
                self.redirected=True
                route.fulfill(status=302,headers={'Location':target},body=b'')
                return
            if (request.resource_type=='document' and self.initial_url
                    and canonical_url(request.url)==canonical_url(self.initial_url)
                    and (exc.status in (404,410) or self._vacancy_gone_redirect(request.url,exc))):
                self.closed_document=True
            route.abort()
        except Exception:
            route.abort()

    def _vacancy_gone_redirect(self,url,exc):
        """PageUp answers a vacancy that no longer exists with a redirect: to its listing ('?jobnotfound=true') or, for a
        retired tenant, to the employer's own home page on another host (careers.pageuppeople.com/454, 2026-10-18: ten
        ads re-tried every run, each ending in net::ERR_FAILED). Either way the ad is gone: closed, not unreadable."""
        if exc.status not in (301,302,303,307,308) or not exc.location:return False
        a=urlsplit(url)
        if not (a.hostname or '').endswith('pageuppeople.com'):return False
        b=urlsplit(urljoin(url,exc.location))
        return 'jobnotfound' in b.query.lower() or (b.hostname!=a.hostname and b.path in ('','/'))

    def _same_host_redirect(self,url,exc):
        """Locale or trailing-slash redirects (careers.bendigobank.com.au, thermh, cardinia) stay on the same HTTPS
        host; the browser asks again and the request comes back through route(), so the pinned public fetch still
        applies to every hop. Anything that leaves the host (PageUp's moved tenants) is still refused."""
        if exc.status not in (301,302,303,307,308) or not exc.location or self.requests>=20:return None
        target=urljoin(url,exc.location)
        a,b=urlsplit(url),urlsplit(target)
        return target if b.scheme=='https' and b.hostname and b.hostname==a.hostname and b.port in (None,443) else None



def _liveness(title,text):
    if not isinstance(text,str):raise InterviewAdUnavailable('interview_ad_unavailable')
    visible=title+' '+text
    # "keep a copy ... it cannot be accessed once the job has closed" is advice in a live ad, not a closed notice
    # (Victorian government ads on Indeed, 2026-10-20).
    visible=re.sub(r"\b(?:once|after|when|until|before|if)\s+(?:the\s+|this\s+)?(?:job|position|role|vacancy|advert(?:isement)?|applications?)\s+(?:has\s+|have\s+|is\s+|are\s+)?(?:been\s+)?(?:closed|expired|filled)",' ',visible,flags=re.I)
    if _FILLED.search(visible) or re.search(r"\b(?:applications? (?:are |now |are now )?closed|(?:job|position|role|vacancy) (?:is |has |has been )?(?:closed|filled|expired))\b",visible,re.I):
        raise InterviewAdUnavailable('interview_ad_closed')
    # a challenge/login page is short: the same words inside a full ad ("a police and security check") are just ad text
    blocked=('verify you are human','access denied','security check','sign in to continue')
    if _WALL.search('<title>'+title+'</title>') or any(s in title.lower() for s in blocked) or (
            len(text.strip())<1500 and any(s in visible.lower() for s in blocked)):
        raise InterviewAdUnavailable('interview_ad_unavailable')

class _UncertainDeadline(InterviewAdUnavailable):
    """Observed deadline uncertainty must not be erased by an HTTP fallback."""


def _closing_date(text, now):
    """Check labelled Australian ad deadlines, not arbitrary dates in the ad.

    Date-only deadlines include the entire closing day (in the person's timezone). Ambiguous
    explicit fields are unavailable rather than evidence of an active vacancy.
    """
    text = re.sub(r'(\d)\s*\n(?:st|nd|rd|th)\s*\n', r'\1 ', re.sub(r'[ \xa0]', ' ', text))
    labels = re.finditer(
        r'^[ \t]*(?:applications? clos(?:e|es|ing)(?: date)?|closing date|job posting end date)'
        r'\b[ \t]*(?::|\bon\b)?\s*([^\n]+)', text, re.I | re.M)
    deadlines = set()
    months = {name: i for i, name in enumerate(
        ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'), 1)}
    for label in labels:
        value = re.sub(r'^(?:by\s+)?(?:\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm)[,]?\s+(?:on\s+)?)?', '', label[1].replace('\xa0', ' ').strip(), flags=re.I)
        value = re.sub(r'^(?:mon|tues|wednes|thurs|fri|satur|sun)day[,]?\s+', '', value, flags=re.I)
        # A label with no date after it (PageUp "Applications close:" then "Back to search results") states no
        # deadline; only a value that names a date can be ambiguous.
        if ('\n' in label[0][:label.start(1) - label.start(0)] and
                not re.search(r'\d|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b', value, re.I)):
            continue
        match = re.match(r'(\d{4})-(\d{2})-(\d{2})\b', value)
        if match:
            year, month, day = map(int, match.groups())
        else:
            match = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})\b', value)
            if match:
                day, month, year = map(int, match.groups())
            else:
                match = re.match(r'(\d{1,2})(?:st|nd|rd|th)?(?:\s+of)?[\s-]+'  # "28th of October" (careers.vic.gov.au)
                                 r'([A-Za-z]+)[,]?(?:[\s-]+(\d{4}))?\b', value, re.I)
                if not match:
                    raise _UncertainDeadline('interview_ad_unavailable')
                day, month_name, year = match.groups()
                month = months.get(month_name.lower()[:3], 0)
                # Reject misspellings instead of guessing from the prefix.
                if month_name.lower() not in (
                        'jan january feb february mar march apr april may jun june '
                        'jul july aug august sep sept september oct october nov november dec december').split():
                    month = 0
                day = int(day)
                year = int(year) if year else None
                if year is None and month:
                    today = now.astimezone(person_timezone()).date()
                    year = today.year + (1 if (today - date(today.year, month, min(day, 28))).days > 180 else 0)
        try:
            deadlines.add(date(year, month, day))
        except (TypeError, ValueError):  # no month and no year: uncertain, not a crash
            raise _UncertainDeadline('interview_ad_unavailable') from None
        # A clock time or timezone needs a separate, unambiguous interpretation.
        # Do not silently turn an explicit timed deadline into end-of-day.
        tail = value[match.end():].strip(' \t.,():')
        # Jora: "Applications close: 11th November 2026 - don't miss out!" (trailing slogan, no time or zone words)
        if re.fullmatch(r"[-\u2013\u2014]\s*[A-Za-z\u2019' !.,]+",tail) and not re.search(
                r'\b(?:at|by|am|pm|noon|midnight|aest|aedt|utc|gmt|time)\b',tail,re.I):tail=''
        at = re.fullmatch(r'(?:at\s+)?(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)(?:[;,]?\s*(?:melbourne|sydney|brisbane|perth|adelaide|hobart|darwin|canberra)(?:\s+time)?(?:\s+zone)?)?', tail, re.I)  # Workday: "3 November 2026 11:59pm"
        if at:
            hour = int(at[1]) % 12 + (12 if at[3].lower() == 'pm' else 0)
            end_of = datetime(year, month, day, hour, int(at[2] or 0), tzinfo=person_timezone())
            if end_of < now:
                raise InterviewAdUnavailable('interview_ad_closed')
            tail = ''
        next_line = text[label.end():].lstrip('\n').split('\n', 1)[0].strip()
        if tail or re.match(r'(?:at\b|by\b|\d{1,2}:|\d{1,2}\s*(?:am|pm)\b|'
                            r'noon\b|midnight\b|aest\b|aedt\b|utc\b|gmt\b)', next_line, re.I):
            raise _UncertainDeadline('interview_ad_unavailable')
    if len(deadlines) > 1:
        raise _UncertainDeadline('interview_ad_unavailable')
    if deadlines and next(iter(deadlines)) < now.astimezone(person_timezone()).date():
        raise InterviewAdUnavailable('interview_ad_closed')


def _same_posting(final_url, url):
    """Same posting when the redirect keeps the address and every original link parameter."""
    final = urlsplit(canonical_url(final_url))
    for allowed in public_posting_urls(url):
        if canonical_url(final_url) == allowed:
            return True
        want = urlsplit(allowed)
        if ((final.scheme, final.netloc, final.path) == (want.scheme, want.netloc, want.path)
                and set(parse_qsl(want.query)) <= set(parse_qsl(final.query))):
            return True
    return False


def _same_host_path_stem(final_url, url):
    a,b=urlsplit(url),urlsplit(final_url)
    return (a.hostname==b.hostname and a.path.rstrip('/').rsplit('/',1)[0]==b.path.rstrip('/').rsplit('/',1)[0]
            and a.path.count('/')>=3)


def _snapshot_ad(url,snapshot,*,acquisition,now=None,redirected=False):
    """Validate observable page content; unavailable pages never become reports."""
    if not isinstance(snapshot,dict):raise InterviewAdUnavailable('interview_ad_unavailable')
    title,text,final_url=(snapshot.get(k,'') for k in ('title','text','url'))
    if not all(isinstance(v,str) for v in (title,text,final_url)):
        raise InterviewAdUnavailable('interview_ad_unavailable')
    if final_url.startswith('chrome-error:'):raise InterviewAdUnavailable('interview_ad_unavailable')  # navigation refused
    ats_target(final_url)  # validates even an unknown public-page URL shape
    # A same-host redirect (Bendigo: /job/<slug>/<id> -> /job/<slug>/<n>-en_GB/) changes the last path segment only;
    # observe_posting still checks the ad's own title against the posting's.
    if not _same_posting(final_url, url) and not (redirected and _same_host_path_stem(final_url, url)):
        raise InterviewAdUnavailable('interview_ad_identity_changed')
    if canonical_url(final_url) not in public_posting_urls(url):
        final_url = canonical_url(url)  # same page plus display parameters (e.g. iCIMS ?mobile=false&width=...)
    _liveness(title,snapshot.get('page_text',text))
    if not title.strip() or len(title)>500 or len(text.strip())<200:
        raise InterviewAdUnavailable('interview_ad_incomplete')
    if len(text)>MAX_AD_CHARS:raise InterviewAdUnavailable('interview_ad_too_large')
    now = now or datetime.now(timezone.utc)
    _closing_date(text, now)
    company=snapshot.get('company','')
    if not isinstance(company,str):company=''
    return InterviewAd(url,final_url,title.strip(),company.strip(),text.strip(),
                       now.isoformat(),acquisition)


def browser_ad(url,*,fetcher=None,deadline=None,playwright_factory=None):
    """Read the visible ad in a fresh browser; close everything before returning."""
    ats_target(url)
    if (urlsplit(url).hostname or '').endswith('seek.com.au'):return seek_ad(url)  # Seek answers 403 to plain fetches
    if (urlsplit(url).hostname or '').endswith('jora.com'):return jora_ad(url)  # headless Chromium is blocked there
    if (urlsplit(url).hostname or '').endswith('indeed.com'):return indeed_ad(url)  # its web pages challenge every browser
    public_urls = public_posting_urls(url)
    browse_url = (public_urls[1] if len(public_urls) == 2
                  and urlsplit(public_urls[0]).netloc == 'www.seek.com.au' else url)
    deadline=deadline if deadline is not None else time.monotonic()+30
    if time.monotonic()>=deadline:raise InterviewAdUnavailable('interview_ad_unavailable')
    if playwright_factory is None:
        from playwright.sync_api import sync_playwright
        playwright_factory=sync_playwright
    browser=None
    transport=None
    try:
        with playwright_factory() as pw:
            try:
                browser=pw.chromium.launch(headless=True)
                context=browser.new_context(service_workers='block',accept_downloads=False)
                transport=PublicBrowserTransport(fetcher or SafeFetcher(max_bytes=MAX_PUBLIC_DOCUMENT_BYTES),deadline,browse_url)
                context.route('**/*',transport.route)
                context.route_web_socket('**/*',lambda ws:ws.close())
                page=context.new_page()
                page.on('popup',lambda popup:popup.close())
                remaining=lambda:max(1,int((deadline-time.monotonic())*1000))
                # LinkedIn's page polls its own analytics forever, so 'networkidle' never comes (it ate the whole time
                # budget on every posting); its job description is in the first document.
                settle='domcontentloaded' if urlsplit(browse_url).netloc.endswith('linkedin.com') else 'networkidle'
                page.goto(browse_url,wait_until=settle,timeout=remaining())
                if time.monotonic()>=deadline:raise InterviewAdUnavailable('interview_ad_unavailable')
                expression='''(() => {
                    const root=document.querySelector('main') || document.querySelector('article') || document.body;
                    const isVisible=(p) => !!p &&
                        !p.closest('script,style,nav,footer,header,[hidden],[aria-hidden="true"]') &&
                        (!p.checkVisibility || p.checkVisibility({checkVisibilityCSS:true,checkOpacity:true}));
                    // SuccessFactors sites put a "*** Please note: We have recently updated our system ***" notice in an h1
                    // above the real title (BHP, 2026-10-18): skip headings that start with asterisks.
                    const heading=[...root.querySelectorAll('h1')].find((h) => isVisible(h) && !/^\\s*\\*{2,}/.test(h.innerText));
                    const visible=[];
                    const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
                    while(walker.nextNode()) {
                        const n=walker.currentNode,p=n.parentElement;
                        if (!isVisible(p)) continue;
                        if (n.textContent.trim()) visible.push(n.textContent.trim());
                    }
                    return {url:location.href,title:heading?.innerText || document.title,
                            text:visible.join('\\n'),page_text:document.body.innerText};
                })()'''
                cdp=context.new_cdp_session(page)
                evaluated=cdp.send('Runtime.evaluate',{'expression':expression,'returnByValue':True,
                    'timeout':min(3000,remaining())})
                if evaluated.get('exceptionDetails') or time.monotonic()>=deadline:
                    raise InterviewAdUnavailable('interview_ad_unavailable')
                snapshot=evaluated.get('result',{}).get('value')
                return _snapshot_ad(url,snapshot,acquisition='browser',redirected=transport.redirected)
            finally:
                if browser is not None:browser.close()
    except InterviewAdUnavailable:raise
    except Exception:
        if transport is not None and transport.closed_document:
            raise InterviewAdUnavailable('interview_ad_closed') from None
        raise InterviewAdUnavailable('interview_ad_unavailable') from None


def acquire_ad(url,*,fetcher=None,browser_reader=None,deadline=None):
    """Structured API then browser. HTTP fallback is separate and must be labelled."""
    deadline=deadline if deadline is not None else time.monotonic()+40
    fetcher=fetcher or SafeFetcher(max_bytes=MAX_PUBLIC_DOCUMENT_BYTES)
    ad=structured_ad(url,fetcher=fetcher,deadline=deadline)
    if ad is not None:return ad
    if (urlsplit(url).hostname or '').endswith('jora.com'):return jora_ad(url)
    try:
        return (browser_reader or browser_ad)(url,fetcher=fetcher,deadline=deadline)
    except InterviewAdUnavailable as exc:
        if isinstance(exc, _UncertainDeadline):raise
        if str(exc)!='interview_ad_unavailable':raise
        return http_ad(url,fetcher=fetcher,deadline=deadline)


def indeed_ad(url):
    """Live check of one Indeed job through Indeed's own app API (the one the job search uses): its web pages show a
    human-verification challenge to this server, a home connection and the Tencent VPS alike (2026-10-20). The API says
    whether the job has expired and returns today's full ad, so nothing relies on the text saved at search time."""
    import requests
    from jobspy.indeed.constant import headers
    from jobwatch.models import html_to_text
    m=re.search(r'[?&]jk=([0-9a-f]{16})\b',url)
    if not m:raise InterviewAdUnavailable('interview_ad_unavailable')
    query=('query { jobData(jobKeys: ["%s"]) { results { job { key title expired sourceEmployerName '
           'description { html } } } } }' % m[1])
    try:
        resp=requests.post('https://apis.indeed.com/graphql',json={'query':query},timeout=20,
                           headers=headers|{'indeed-co':'AU','indeed-locale':'en-AU'})
        data=resp.json() if resp.status_code==200 else None
    except Exception:raise InterviewAdUnavailable('interview_ad_unavailable') from None
    if not isinstance(data,dict) or data.get('errors') or not isinstance(data.get('data'),dict):
        raise InterviewAdUnavailable('interview_ad_unavailable')
    results=(data['data'].get('jobData') or {}).get('results')
    if results==[]:raise InterviewAdUnavailable('interview_ad_closed')  # Indeed no longer has this job
    job=(results or [{}])[0].get('job') or {}
    if job.get('expired') is True:raise InterviewAdUnavailable('interview_ad_closed')
    text=html_to_text((job.get('description') or {}).get('html') or '',limit=MAX_AD_CHARS)
    if job.get('expired') is not False or not text.strip():raise InterviewAdUnavailable('interview_ad_unavailable')
    return _snapshot_ad(url,{'url':url,'title':job.get('title') or '','text':text,
                             'company':job.get('sourceEmployerName') or '','page_text':text},acquisition='browser')


def seek_ad(url):
    """Seek returns 403 to the browser's plain fetches but serves its job page to a Chrome TLS fingerprint
    (2026-10-20); the ad is in the page's SEEK_REDUX_DATA, the same parser the collectors use."""
    from jobwatch.util.adtext import _http_get, _REDUX, parse_seek_page, last_status
    m=re.search(r'/job/(\d+)',urlsplit(url).path)
    if not m:raise InterviewAdUnavailable('interview_ad_unavailable')
    page_url=f'https://www.seek.com.au/job/{m[1]}'
    # Seek 308-redirects job pages to au.seek.com (2026-10-20); both hosts are Seek's own.
    try:got=_http_get(page_url,('seek.com.au','seek.com'),name='seek',timeout=20)
    except Exception:raise InterviewAdUnavailable('interview_ad_unavailable') from None
    if got is None:
        raise InterviewAdUnavailable('interview_ad_closed' if last_status()=='gone' else 'interview_ad_unavailable')
    page_url,page=got
    text=parse_seek_page(page)
    if not text:raise InterviewAdUnavailable('interview_ad_unavailable')
    resp=type('R',(),{'text':page})
    title=company=''
    found=_REDUX.search(resp.text)
    if found:
        try:
            job=((json.loads(found[1]).get('jobdetails') or {}).get('result') or {}).get('job') or {}
            title=job.get('title') or ''
            company=(job.get('advertiser') or {}).get('name') or ''
        except (ValueError,AttributeError):pass
    if not title:
        h1=re.search(r'<h1[^>]*>(.*?)</h1>',resp.text,re.S)
        title=_plain(h1[1]) if h1 else ''
    return _snapshot_ad(url,{'url':page_url,'title':title,'text':text,'company':company,'page_text':text},
                        acquisition='browser')  # fetched with a Chrome TLS fingerprint


def jora_ad(url):
    """Jora's Cloudflare check blocks headless Chromium (net::ERR_FAILED) and plain HTTP (403), but lets a
    Chrome TLS fingerprint through; the ad is div#job-description-container on the job page itself."""
    from jobwatch.util.adtext import _do_get, _host_ok, _inner_html, _JORA_BODY, _JORA_PATH
    parts=urlsplit(url)
    if not _host_ok(url,('jora.com',)) or not _JORA_PATH.match(parts.path):
        raise InterviewAdUnavailable('interview_ad_unavailable')
    page_url=f'https://{parts.hostname}{parts.path}'
    try:resp=_do_get(page_url,True,20)
    except Exception:raise InterviewAdUnavailable('interview_ad_unavailable') from None
    if resp.status in (404,410):raise InterviewAdUnavailable('interview_ad_closed')
    body=_inner_html(resp.text,_JORA_BODY) if resp.status==200 else ''
    if not body:raise InterviewAdUnavailable('interview_ad_unavailable')
    h1=re.search(r'<h1[^>]*>(.*?)</h1>',resp.text,re.S)
    company=re.search(r'<span[^>]*\bclass="[^"]*\bcompany\b[^"]*"[^>]*>(.*?)</span>',resp.text,re.S)
    return _snapshot_ad(url,{'url':page_url,'title':_plain(h1[1]) if h1 else '','text':_plain(body),
        'company':_plain(company[1]) if company else '','page_text':_plain(body)},acquisition='browser')  # fetched with a Chrome TLS fingerprint


def http_ad(url,*,fetcher=None,deadline=None):
    """Unconfirmed fallback requires one URL-matching JobPosting, never page chrome."""
    ats_target(url)
    try:
        page=(fetcher or SafeFetcher()).fetch_bytes(url,deadline=deadline).decode('utf-8',errors='strict')
        visible=_plain(page)
        title=re.search(r'<title[^>]*>(.*?)</title>',page,re.I|re.S)
        _liveness(_plain(title[1]) if title else '',visible)
        records=[j for j in job_postings(page) if isinstance(j.get('url'),str)
                 and canonical_url(urljoin(url,j['url']))==canonical_url(url)]
        if len(records)!=1:raise InterviewAdUnavailable('interview_ad_incomplete')
        job=records[0]
        if job.get('validThrough'):
            end=datetime.fromisoformat(str(job['validThrough']).replace('Z','+00:00'))
            if end.tzinfo is None:end=end.replace(tzinfo=timezone.utc)
            if end<datetime.now(timezone.utc):raise InterviewAdUnavailable('interview_ad_closed')
        company=job.get('hiringOrganization') or {}
        return _snapshot_ad(url,{'url':url,'title':job.get('title'),
            'text':_plain(job.get('description')),'company':company.get('name','') if isinstance(company,dict) else ''},
            acquisition='unconfirmed (fetched without browser)')
    except InterviewAdUnavailable:raise
    except PublicHTTPStatus as exc:
        code='interview_ad_closed' if exc.status in (404,410) else 'interview_ad_unavailable'
        raise InterviewAdUnavailable(code) from None
    except Exception:raise InterviewAdUnavailable('interview_ad_unavailable') from None
