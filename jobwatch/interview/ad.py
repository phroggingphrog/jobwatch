"""Complete public ATS descriptions for explicit standalone interview preparation.

This module does not write postings or applications. Browser/paste acquisition is
handled by the caller when an ATS does not provide a complete identified record.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import html
import json
import re
from urllib.parse import quote, urlsplit

from jobwatch.candidate.contracts import content_hash
from pipeline.agentic.research import SafeFetcher, ResearchUnavailable, PublicHTTPStatus, _readable_public_text

MAX_AD_CHARS = 100_000


class InterviewAdUnavailable(ValueError):
    """Fixed codes only; no URLs or retrieved contents in exception messages."""


@dataclass(frozen=True, repr=False)
class InterviewAd:
    url: str
    source_url: str
    title: str
    company: str
    text: str
    acquired_at: str
    acquisition: str = 'structured_ats'
    expires_at: str | None = None

    @property
    def text_hash(self):
        return content_hash(self.text.encode())


def _segment(value):
    # Provider IDs/tenants only. Never let URL path content change the API host.
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', value):
        raise InterviewAdUnavailable('interview_url_invalid')
    return quote(value, safe='')


def ats_target(url):
    """Known URL shapes only; no model-selected endpoints or arbitrary redirects."""
    try:
        if type(url) is not str or len(url)>8192 or any(ord(c)<32 or ord(c)==127 for c in url):raise ValueError
        p=urlsplit(url)
        if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):raise ValueError
        parts=p.path.strip('/').split('/')
        host=p.hostname.lower()
        if host in ('boards.greenhouse.io','job-boards.greenhouse.io') and len(parts)==3 and parts[1]=='jobs':
            tenant,job=_segment(parts[0]),_segment(parts[2])
            return 'greenhouse',f'https://boards-api.greenhouse.io/v1/boards/{tenant}/jobs/{job}?content=true',job
        if host in ('jobs.lever.co','jobs.eu.lever.co') and len(parts)==2:
            tenant,job=map(_segment,parts)
            api='api.eu.lever.co' if host=='jobs.eu.lever.co' else 'api.lever.co'
            return 'lever',f'https://{api}/v0/postings/{tenant}/{job}?mode=json',job
        if host=='jobs.ashbyhq.com' and len(parts)==2:
            tenant,job=map(_segment,parts)
            return 'ashby',f'https://api.ashbyhq.com/posting-api/job-board/{tenant}',job
        if re.fullmatch(r'[a-z0-9-]+\.wd[0-9]+\.myworkdayjobs\.com',host):
            if parts and re.fullmatch(r'[a-z]{2}-[A-Z]{2}',parts[0]):parts=parts[1:]
            if len(parts)>=3 and parts[1]=='job':
                tenant=_segment(host.split('.')[0]);site=_segment(parts[0])
                # Workday external paths contain location/title segments; encode each separately.
                path='/'.join(quote(v,safe='_-') for v in parts[1:])
                if any(v in ('.','..','') or '%' in v for v in parts):raise ValueError
                return 'workday',f'https://{host}/wday/cxs/{tenant}/{site}/{path}','/'+path
        if re.fullmatch(r'[a-z0-9-]+(?:\.[a-z0-9-]+)*\.oraclecloud\.com',host) and len(parts)==7 and parts[3]=='sites' and parts[5]=='job':
            site,job=_segment(parts[4]),_segment(parts[6])
            if job.isdigit():
                return 'oracle',(f'https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails'
                                 f'?expand=all&onlyData=true&finder=ById%3BId%3D%22{job}%22%2CsiteNumber%3D{site}'),job
        return None
    except (ValueError,TypeError):
        raise InterviewAdUnavailable('interview_url_invalid') from None


def _plain(value, *, encoded=False):
    if not isinstance(value,str):return ''
    # A higher parser limit avoids the research excerpt cap. Oversize descriptions
    # are rejected below, rather than labelled whole after silent truncation.
    if len(value)>1_000_000:raise InterviewAdUnavailable('interview_ad_too_large')
    if encoded and not re.search(r'<[A-Za-z][^>]*>',value) and re.search(r'&lt;(?:p|div|ul|ol|li|br|h[1-6])(?:&gt;|\s)',value):
        value=html.unescape(value)
    return _readable_public_text(value,limit=1_000_001).strip()


def structured_ad(url, *, fetcher=None, deadline=None, now=None, require_active_workday=False):
    """Return a complete identified ATS record, or None for browser acquisition.

    Explicit closed/expired records are terminal and require owner-supplied text.
    Network failure or unfamiliar provider data never becomes a fabricated JD.
    """
    target=ats_target(url)
    if target is None:return None
    provider,endpoint,job_id=target
    if require_active_workday and provider!='workday':return None
    try:
        # 16 MB: Ashby boards return every job with its description (Airwallex: 8 MB on 2026-10-12).
        raw=json.loads((fetcher or SafeFetcher(max_bytes=16_000_000)).fetch_bytes(endpoint,deadline=deadline))
        if not isinstance(raw,dict):return None
        if provider=='ashby':
            matches=[j for j in raw.get('jobs',[]) if isinstance(j,dict) and str(j.get('id'))==job_id]
            if len(matches)!=1:return None
            record=matches[0]
        elif provider=='workday':
            record=raw.get('jobPostingInfo')
            if not isinstance(record,dict):return None
            external=record.get('externalPath')
            requisition=record.get('jobReqId')
            if not external and not requisition:return None
            if external and external!=job_id:return None
            expected=job_id.rsplit('_',1)[-1]
            # Re-posted requisitions end "_R0015646-1" in the URL while jobReqId is "R0015646"; jobPostingId is the exact URL tail.
            if requisition and requisition!=expected and not (record.get('jobPostingId')==job_id.rsplit('/',1)[-1]
                                                              and expected.startswith(requisition+'-')):return None
            if require_active_workday:
                # Some tenants publish the same job as https://wdN.myworkdaysite.com/recruiting/<tenant>/<site>/job/...
                external_url=re.sub(r'^https://(wd[0-9]+)\.myworkdaysite\.com/recruiting/([a-z0-9-]+)/([^/]+)/',
                                    r'https://\2.\1.myworkdayjobs.com/\3/',record.get('externalUrl') or '')
                if not requisition or ats_target(external_url)!=target:return None
                if record.get('posted') is False:raise InterviewAdUnavailable('interview_ad_closed')
                if record.get('canApply') is False:raise InterviewAdUnavailable('interview_ad_unavailable')
                if record.get('posted') is not True or record.get('canApply') is not True:return None
        elif provider=='oracle':
            items=raw.get('items')
            # A valid answer with no requisition for this Id: the posting was taken down (a block or error is not this shape).
            if items==[] and raw.get('count')==0 and raw.get('hasMore') is False:raise InterviewAdUnavailable('interview_ad_closed')
            if not isinstance(items,list) or len(items)!=1 or not isinstance(items[0],dict):return None
            record=dict(items[0])
            if str(record.get('Id'))!=job_id:return None
            record['validThrough']=record.get('ExternalPostedEndDate')
        else:
            record=raw
            if str(record.get('id'))!=job_id:return None
        if record.get('isListed') is False or record.get('isActive') is False:
            raise InterviewAdUnavailable('interview_ad_closed')
        expires=record.get('validThrough')
        current=now or datetime.now(timezone.utc)
        end=None
        if expires:
            try:
                end=datetime.fromisoformat(str(expires).replace('Z','+00:00'))
                if end.tzinfo is None:end=end.replace(tzinfo=timezone.utc)
                if end<=current:raise InterviewAdUnavailable('interview_ad_closed')
            except ValueError as exc:
                if isinstance(exc,InterviewAdUnavailable):raise
                return None
        title=record.get('Title') if provider=='oracle' else record.get('title') if provider!='lever' else record.get('text')
        company=record.get('companyName') or record.get('hiringOrganization',{}).get('name','')
        if provider=='greenhouse':body=_plain(record.get('content'),encoded=True)
        elif provider=='workday':body=_plain(record.get('jobDescription'))
        elif provider=='oracle':
            body='\n\n'.join(v for v in (_plain(record.get(k)) for k in ('ExternalDescriptionStr','ExternalResponsibilitiesStr',
                'ExternalQualificationsStr','CorporateDescriptionStr')) if v)
        elif provider=='ashby':body=record.get('descriptionPlain') or _plain(record.get('descriptionHtml'))
        else:
            sections=[record.get('descriptionPlain') or _plain(record.get('description'))]
            for item in record.get('lists',[]):
                if not isinstance(item,dict):return None
                sections += [item.get('text',''),_plain(item.get('content'))]
            sections += [record.get('additionalPlain') or _plain(record.get('additional'))]
            if any(not isinstance(v,str) for v in sections):return None
            body='\n\n'.join(v for v in sections if v)
        if not isinstance(title,str) or not title.strip() or len(title)>500:return None
        if not isinstance(body,str) or len(body.strip())<200:return None
        if len(body)>MAX_AD_CHARS:raise InterviewAdUnavailable('interview_ad_too_large')
        if not isinstance(company,str):company=''
        if require_active_workday:
            metadata=[record.get('location'),record.get('timeType')]
            if any(v is not None and not isinstance(v,str) for v in metadata):return None
            body='\n'.join([title.strip(),*(v for v in metadata if v),body.strip()])
            if len(body)>MAX_AD_CHARS:raise InterviewAdUnavailable('interview_ad_too_large')
            return InterviewAd(url,url,title.strip(),company.strip(),body,current.isoformat(),'active_workday',end.isoformat() if end else None)
        return InterviewAd(url,endpoint,title.strip(),company.strip(),body.strip(),current.isoformat())
    except InterviewAdUnavailable:raise
    except PublicHTTPStatus:
        # Workday answers 403 "permission denied" for requisitions that were taken down, but a 403 is also what a bot
        # block looks like (careers.vic taught that), and the job-list check I tried missed 1 of 22 live ads. So a 403
        # is only "not readable here": the browser reads the page next, and the ad is held and rechecked, never closed.
        return None
    except (ResearchUnavailable,ValueError,TypeError,AttributeError,KeyError):
        return None
