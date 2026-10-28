"""Source-bound public vacancy observations before agent/model work.

No candidate data is accepted or forwarded. The service owns persistence/stage
changes; this module only observes the public URL with the existing browser.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit
import time
from dataclasses import replace
from datetime import datetime,timezone
from typing import Literal

from pydantic import Field,model_validator

from jobwatch.candidate.contracts import content_hash
from jobwatch.interview.ad import InterviewAdUnavailable, structured_ad
from jobwatch.interview.browser import browser_ad, _closing_date, _snapshot_ad, public_posting_urls
from jobwatch.models import canonical_url,fold
from pipeline.agentic.contracts import StrictFrozen, AgenticError

log=logging.getLogger('jobwatch.agentic')


class PostingObservation(StrictFrozen):
    status: Literal['active','closed','unknown']
    reason: Literal['visible_job_description','active_ats_posting','posting_closed','posting_unavailable','posting_identity_unverified']
    posting_id: int = Field(gt=0)
    url_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    checked_at: str = Field(max_length=64)
    title: str = Field(default='',max_length=500,repr=False)
    text: str = Field(default='',max_length=100000,repr=False)
    ad_hash: str | None = None
    expires_at: str | None = Field(default=None,max_length=64)
    source_url: str = Field(default='',max_length=8192,repr=False)

    @model_validator(mode='after')
    def bound_source(self):
        if datetime.fromisoformat(self.checked_at).utcoffset() is None:raise ValueError('observation_time_invalid')
        if self.expires_at is not None and datetime.fromisoformat(self.expires_at).utcoffset() is None:
            raise ValueError('observation_expiration_invalid')
        allowed={'active':{'visible_job_description','active_ats_posting'},'closed':{'posting_closed'},
                 'unknown':{'posting_unavailable','posting_identity_unverified'}}
        if self.reason not in allowed[self.status]:raise ValueError('observation_reason_invalid')
        if self.status=='active':
            if not self.title.strip() or len(self.text.strip())<200 or self.ad_hash!=content_hash(self.text.encode()):
                raise ValueError('observation_source_invalid')
            if self.url_hash not in {content_hash(url.encode()) for url in public_posting_urls(self.source_url)}:
                raise ValueError('observation_identity_invalid')
        elif self.text or self.ad_hash or self.source_url or self.title or self.expires_at:
            raise ValueError('unverified_observation_has_content')
        return self


def _strip_page_chrome(text):
    """Page furniture that differs between two reads of the same ad made every run end in snapshot_changed (2026-10-18:
    about 20 postings, never judged): LinkedIn swaps its "Use AI to assess" box and its job-alert prompt between loads, and
    SuccessFactors sites append a cookie-consent manager (or an Accept/Close bar) to some loads only."""
    text=re.sub(r'^[ \t]*Use AI to assess how you fit[ \t]*\n(?:[^\n]*\n){0,3}?[ \t]*Tailor my resume[ \t]*\n?','',text,flags=re.I|re.M)
    text=re.sub(r'^[ \t]*Get notified about new[ \t]*\n(?:[^\n]*\n){0,4}?[ \t]*Sign in to create job alert[ \t]*\n?','',text,flags=re.I|re.M)
    text=re.sub(r'^[ \t]*Get notified when a new job is posted\.[ \t]*\n(?:[ \t]*Set alert[ \t]*\n?)?','',text,flags=re.I|re.M)
    text=re.sub(r'^[ \t]*\*{3}[ \t]*\n?[ \t]*Please note: We have recently updated our system[^\n]*\n(?:[ \t]*\*{3}[ \t]*\n?)?','',text,flags=re.I|re.M)  # BHP SuccessFactors notice
    text=re.sub(r'^[ \t]*Cookie Consent Manager[ \t]*\n.*\Z','',text,flags=re.I|re.M|re.S)
    text=re.sub(r'^[ \t]*By continuing to use and navigate this website, you are agreeing to the use of cookies\.[ \t]*\n(?:[ \t]*(?:Accept|Close)[ \t]*\n?){0,2}','',text,flags=re.I|re.M)
    return text.rstrip('\n') if text.endswith('\n\n') else text


def observe_posting(posting,*,reader=None,fetcher=None,deadline=None,now=None):
    """Unknown means hold, never evidence that an unavailable page is active."""
    url=posting.get('url') or ''
    base={'posting_id':posting['id'],'url_hash':content_hash(canonical_url(url).encode()),
          'checked_at':(now or datetime.now(timezone.utc)).isoformat()}
    budget=None if deadline is None else deadline-time.monotonic()
    if budget is not None and budget <= 0:
        raise AgenticError('deadline_exceeded')
    # Readers accept https only; some boards (Greenhouse/block.xyz) store http. Identity (url_hash) keeps the stored URL.
    stored_url=url
    if url[:7].lower()=='http://':url='https://'+url[7:]
    try:
        ad=None
        if reader is None:
            ad=structured_ad(url,fetcher=fetcher,deadline=deadline,now=now,require_active_workday=True)
            if ad is not None:
                _snapshot_ad(url,{'url':url,'title':ad.title,'text':ad.text},acquisition='active_workday')
            elif 'ashbyhq.com' in url or 'oraclecloud.com' in url:
                # Ashby and Oracle pages are script-only (the page renders empty); the API reports isListed/isActive/validThrough.
                ad=structured_ad(url,fetcher=fetcher,deadline=deadline,now=now)
                if ad is not None:ad=replace(ad,source_url=url,acquisition='active_workday')
        if ad is None:ad=(reader or browser_ad)(url,fetcher=fetcher,deadline=deadline)
        expected,observed=fold(posting.get('title') or ''),fold(ad.title)
        if (ad.acquisition not in {'browser','active_workday'} or canonical_url(ad.source_url) not in public_posting_urls(url)
                or not expected or not observed or not (expected in observed or observed in expected
                                                        # PageUp's h1 is the site's "Job Search"; the job's own title
                                                        # is a line of the visible ad.
                                                        or any(fold(line) == expected for line in ad.text.splitlines()))):
            log.warning('posting %s not verified: acquisition=%s title=%r (budget %s s)',posting['id'],ad.acquisition,ad.title[:60],
                        None if budget is None else round(budget))
            return PostingObservation(**base,status='unknown',reason='posting_identity_unverified')
        # SEEK's "Posted 7h ago" changes every run, which made the ad hash differ each time (snapshot_changed forever).
        text=re.sub(r'^[ \t]*Posted\s+\d+\+?\s*[a-z]+\s+ago[ \t]*\n?','',ad.text,flags=re.I|re.M)
        # A cookie banner that is on the page for some loads and not others (Monash Health, 2026-10-18) made the same
        # ad differ between reads: snapshot_changed on every run.
        text=re.sub(r'^[ \t]*(?:We use cookies\b[^\n]*|(?:Modify Cookie Preferences|Reject All Cookies|Accept All Cookies))[ \t]*\n?','',text,flags=re.I|re.M)
        text=_strip_page_chrome(text)
        return PostingObservation(**base,status='active',reason='active_ats_posting' if ad.acquisition=='active_workday' else 'visible_job_description',
            title=ad.title,text=text,ad_hash=content_hash(text.encode()),source_url=stored_url if stored_url!=url else ad.source_url,expires_at=ad.expires_at)
    except InterviewAdUnavailable as exc:
        closed=str(exc)=='interview_ad_closed'
        if not closed and deadline is not None and time.monotonic() >= deadline:
            raise AgenticError('deadline_exceeded') from None
        if not closed:
            log.warning('posting %s unreadable: %s %s (budget %s s)',posting['id'],str(exc),repr(exc.__context__)[:200],
                        None if budget is None else round(budget))
        return PostingObservation(**base,status='closed' if closed else 'unknown',
            reason='posting_closed' if closed else 'posting_unavailable')
    except Exception as exc:
        if deadline is not None and time.monotonic() >= deadline:
            raise AgenticError('deadline_exceeded') from None
        # Transport/parser failures cannot establish public posting availability.
        log.warning('posting %s read failed: %s: %s (budget %s s)',posting['id'],type(exc).__name__,str(exc)[:200],
                    None if budget is None else round(budget))
        return PostingObservation(**base,status='unknown',reason='posting_unavailable')


def latest_observation(conn, posting_id):
    """Read the latest fenced public observation; legacy databases are unknown."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='agentic_posting_observations'").fetchone():
        return None
    row=conn.execute('SELECT observation_json FROM agentic_posting_observations WHERE posting_id=? '
                     'ORDER BY id DESC LIMIT 1',(posting_id,)).fetchone()
    if not row:return None
    try:return PostingObservation.model_validate_json(row[0])
    except ValueError:return None


def observation_current(observation, *, posting_id, url, ad_hash, max_age_seconds=86400, now=None):
    if observation is None or observation.status!='active':return False
    now = now or datetime.now(timezone.utc)
    if observation.expires_at is not None and now>=datetime.fromisoformat(observation.expires_at):return False
    try:
        _closing_date(observation.text, now)
    except InterviewAdUnavailable:
        return False
    age=(now-datetime.fromisoformat(observation.checked_at)).total_seconds()
    return (0<=age<=max_age_seconds and observation.posting_id==posting_id
            and observation.url_hash==content_hash(canonical_url(url).encode()) and observation.ad_hash==ad_hash)


def observation_metadata(observation):
    return observation.model_dump(exclude={'title','text','source_url'}) if observation else None
