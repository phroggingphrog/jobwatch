"""RecruitmentHub (https://{tenant}.recruitmenthub.com.au), used by Maribyrnong, Nillumbik and Moorabool.

Server-rendered list page, robots.txt respected (Fetcher checks it). The path differs per tenant
("/Vacancies/" or "/Current-vacancies/"), so the registry carries it in careers_url. Each job is a
`div.well.apply-desc` holding: `a.title.joblink-{id}` (href /{section}/{id}/title/{slug}), `p.description`
(employment type, band/salary and an intro, truncated), `Location: <span>`, `Job ID: <span>` and
`Closing Date: <span>`. There is no posted date, so postings are observed-dated and the first read seeds.
A tenant whose site is down answers 200 with "Sorry, the site is not available": that is raised as an error.
Registry fields: tenant (subdomain), careers_url (list page), state.
"""
from __future__ import annotations

import html as htmllib
import re
from urllib.parse import urljoin

from ..models import Posting, clean_text, html_to_text, salary_from_text, work_type_of
from .base import CollectorContext, run_per_employer

NAME = "ats_recruitmenthub"
_BLOCK = re.compile(r'<div class="[^"]*\bapply-desc\b[^"]*">', re.I)
_TITLE = re.compile(r'<a class="title joblink-(\d+)"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
_DESC = re.compile(r'<p class="description">(.*?)(?:<a [^>]*mobile-joblink-readmore|</p>)', re.S | re.I)
_LOC = re.compile(r"Location:\s*<span[^>]*>(.*?)</span>", re.S | re.I)
_CLOSE = re.compile(r"Closing Date:\s*<span>(.*?)</span>", re.S | re.I)
_DOWN = re.compile(r"site is not available", re.I)


def list_url(employer: dict) -> str:
    return employer.get("careers_url") or f"https://{employer['tenant']}.recruitmenthub.com.au/Vacancies/"


def parse_list(page: str, employer: dict) -> list[Posting]:
    if _DOWN.search(page) and not _TITLE.search(page):
        raise ValueError(f"{employer.get('tenant')} recruitmenthub site not available")
    base = list_url(employer)
    out = []
    for block in _BLOCK.split(page)[1:]:
        t = _TITLE.search(block)
        if not t:
            continue
        job_id, href, title = t.group(1), t.group(2), clean_text(re.sub(r"<[^>]+>", " ", t.group(3)))
        desc = _DESC.search(block)
        text = clean_text(html_to_text(desc.group(1))) if desc else ""
        loc = _LOC.search(block)
        close = _CLOSE.search(block)
        smin, smax, unit = salary_from_text(text)
        out.append(Posting(
            source=NAME, source_id=f"{employer.get('tenant')}:{job_id}", url=urljoin(base, htmllib.unescape(href)),
            title=title, company=employer.get("name", ""),
            location=clean_text(loc.group(1)) if loc else "", state=employer.get("state") or None,
            work_type=work_type_of(text[:120]), salary_min=smin, salary_max=smax, salary_unit=unit,
            description=text,
            raw={"id": job_id, "closing": clean_text(close.group(1)) if close else None},
        ))
    return out


def fetch_one(cfg: CollectorContext, employer: dict):
    page = cfg.http.get_text(list_url(employer), robots=True)
    jobs = parse_list(page, employer)
    cfg.count_raw(len(jobs))
    return jobs


def collect(cfg: CollectorContext, since=None) -> list[Posting]:
    return run_per_employer(cfg, "recruitmenthub", fetch_one)
