"""Phenom People career sites (registry provider: phenom), slow tier.

The search-results page (careers_url, e.g. https://colescareers.com.au/au/en/search-results)
embeds its state as `phApp.ddo = {...}`; `eagerLoadRefineSearch` holds totalHits and the first
10 jobs, and siteConfig/phApp hold refNum, locale and pageId. The rest is read the way the page
itself pages: POST {origin}/widgets {ddoKey: refineSearch, from, size: 100} (allowed by
robots.txt; only */px-widgets is disallowed). Phenom ignores sort requests from the URL and the
widget, so the default (relevance) order is read in full, up to `max_pages` x 100 (default 10).
Job URL: {origin}/{country}/{lang}/job/{jobId}/{title-slug}.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from ..http import HttpError
from ..models import Posting, html_to_text, is_australian, iso
from .base import CollectorContext, run_per_employer

NAME = "ats_phenom"
SIZE = 100
_DDO = re.compile(r"phApp\.ddo\s*=\s*")


def page_state(text: str) -> dict:
    """{'total', 'jobs', 'refNum', 'locale', 'country', 'pageId', 'siteType'} from the page HTML."""
    m = _DDO.search(text)
    if not m:
        raise ValueError("no phApp.ddo state in page (not a Phenom search page?)")
    ddo, _ = json.JSONDecoder().raw_decode(text[m.end():])
    eager = ddo.get("eagerLoadRefineSearch") or {}
    head = text[:m.start() + 20000]

    def meta(key, default=""):
        found = re.search(rf'"{key}"\s*:\s*"([^"]*)"', head)
        return found.group(1) if found else default
    page_id = re.search(r'phApp\.pageId\s*=\s*"([^"]*)"', text)
    return {"total": int(eager.get("totalHits") or 0),
            "jobs": (eager.get("data") or {}).get("jobs") or [],
            "refNum": meta("refNum"), "locale": meta("locale", "en_us"), "country": meta("country", "us"),
            "siteType": meta("siteType", "external"),
            "pageId": meta("pageId") or (page_id.group(1).replace("-ds", "") if page_id else "")}


def _slug(title: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", title or "").strip("-")


def job_to_posting(job: dict, employer: dict, job_base: str) -> Posting | None:
    locs = job.get("multi_location") or [job.get("location") or job.get("cityStateCountry") or ""]
    country = job.get("country") or ""
    au_locs = [l for l in locs if is_australian(None, l)]
    if country and not is_australian(country) and not au_locs:
        return None
    if not country and not au_locs:
        return None
    location = " | ".join(au_locs or locs)[:200]
    job_id = job.get("jobId") or job.get("reqId") or job.get("jobSeqNo")
    if not job_id:
        return None
    title = job.get("title") or ""
    posted = job.get("postedDate") or job.get("dateCreated")
    return Posting(
        source=NAME, source_id=f"{employer.get('name')}:{job_id}",
        url=f"{job_base}/job/{job_id}/{_slug(title)}", title=title, company=employer.get("name", ""),
        location=location, remote="remote" in f"{location} {job.get('workLocation') or ''}".lower(),
        posted_at=iso(posted), posted_at_source="provider" if posted else "observed",
        description=html_to_text(job.get("descriptionTeaser")),
        raw={k: job.get(k) for k in ("jobId", "reqId", "title", "location", "multi_location", "category",
                                      "type", "postedDate", "dateCreated", "applyUrl")},
    )


def fetch_one(cfg: CollectorContext, employer: dict):
    url = employer["careers_url"]
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    job_base = origin + re.sub(r"/search-results.*$", "", parts.path).rstrip("/")
    state = page_state(cfg.http.get_text(url, robots=True))
    jobs, total = list(state["jobs"]), state["total"]
    max_pages = int(employer.get("max_pages", 10))
    widgets = f"{origin}/widgets"
    if total > len(jobs) and not cfg.http.allowed(widgets):
        cfg.error(employer.get("name", "?"), "robots.txt disallows /widgets; first page only")
        max_pages = 0
    lang = state["locale"]
    for page in range(max_pages):
        offset = len(jobs)
        if offset >= total:
            break
        body = {"lang": lang, "deviceType": "desktop", "country": state["country"],
                "pageName": "search-results", "ddoKey": "refineSearch", "sortBy": "", "subsearch": "",
                "from": offset, "jobs": True, "counts": False, "all_fields": [], "size": SIZE,
                "clearAll": False, "jdsource": "facets", "isSliderEnable": False,
                "pageId": state["pageId"], "siteType": state["siteType"], "keywords": "",
                "global": True, "selected_fields": {}, "locationData": {}, "refNum": state["refNum"]}
        try:
            data = cfg.http.post_json(widgets, body)
        except HttpError as exc:
            cfg.error(f"{employer.get('name')} widgets", exc)
            break
        batch = (((data or {}).get("refineSearch") or {}).get("data") or {}).get("jobs") or []
        if not batch:
            break
        jobs += batch
    cfg.count_raw(len(jobs))
    seen, out = set(), []
    for job in jobs:
        p = job_to_posting(job, employer, job_base)
        if p and p.source_id not in seen:
            seen.add(p.source_id)
            out.append(p)
    return out


def collect(cfg: CollectorContext, since=None) -> list[Posting]:
    return run_per_employer(cfg, "phenom", fetch_one)
