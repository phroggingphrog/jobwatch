"""Seek public search JSON (no login): https://www.seek.com.au/api/jobsearch/v5/search

Params: siteKey=AU-Main, where=<search location>, keywords, dateRange=1, page<=2.
NOTE: Seek's robots.txt disallows /api/jobsearch/ for all agents. The owner accepted the
ToS risk for personal, low-volume use (PLAN D3); set seek.respect_robots: true in
searches.yaml to honour robots.txt instead (the collector then records a clean error).
"""
from __future__ import annotations

from jobwatch.util.place import location_text

from jobwatch.util.http import HttpError
from ..models import Posting, is_australian, iso, salary_from_text, work_type_of
from .base import CollectorContext, rotate

NAME = "seek"
API = "https://www.seek.com.au/api/jobsearch/v5/search"


def to_posting(job: dict, keyword: str = "") -> Posting | None:
    locs = job.get("locations") or [{}]
    loc = locs[0] if isinstance(locs[0], dict) else {}
    location = loc.get("label") or ""
    if not is_australian(loc.get("countryCode"), location):
        return None
    arrangements = " ".join(((a.get("label") or {}).get("text") or "")
                            for a in (job.get("workArrangements") or {}).get("data") or [])
    salary = job.get("salaryLabel") or None
    smin, smax, unit = salary_from_text(salary)
    teaser = " ".join([job.get("teaser") or ""] + list(job.get("bulletPoints") or []))
    jid = str(job.get("id"))
    return Posting(
        source=NAME, source_id=jid, url=f"https://www.seek.com.au/job/{jid}",
        title=job.get("title") or "",
        company=job.get("companyName") or (job.get("advertiser") or {}).get("description") or "",
        location=location, remote="remote" in arrangements.lower(),
        work_type=work_type_of(*(job.get("workTypes") or [])),
        salary_text=salary, salary_min=smin, salary_max=smax, salary_unit=unit,
        posted_at=iso(job.get("listingDate")),
        posted_at_source="provider" if job.get("listingDate") else "observed",
        description=teaser.strip(), raw=job, origin=f"seek:{keyword}",
    )


def collect(cfg: CollectorContext, since=None) -> list[Posting]:
    conf = cfg.config.searches.get("seek") or {}
    if conf.get("enabled") is False:
        return []
    items = conf['searches'] if 'searches' in conf else list(conf.get('keywords') or [])
    keywords = rotate(cfg, "seek", items, conf.get("searches_per_run"))
    remote = conf.get("remote") or {}
    if remote.get("enabled"):                # remote-only jobs anywhere in Australia
        keywords += [("remote", k) for k in rotate(cfg, "seek_remote", list(remote.get("keywords") or []),
                                                   remote.get("searches_per_run"))]
    max_pages = min(int(conf.get("max_pages", 2)), 2)
    results: list[Posting] = []
    seen: set[str] = set()
    for keyword in keywords:
        extra, failed = {}, False
        if isinstance(keyword, dict):
            search = keyword
            keyword = search['term']
            extra = {'where': search.get('location') or 'All Australia'}
            if search.get('is_remote'):
                extra['workarrangement'] = 3
        elif isinstance(keyword, tuple):       # ("remote", kw): one page, All Australia, remote only
            keyword = keyword[1]
            extra = {"where": remote.get("where", "All Australia"), "workarrangement": 3}
        for page in range(1, (1 if extra.get('workarrangement') else max_pages) + 1):
            if cfg.full(results):
                return results
            params = {"siteKey": "AU-Main", "where": conf.get("where") or location_text() or "All Australia",
                      "keywords": keyword, "dateRange": conf.get("date_range", 1), "page": page,
                      "pageSize": conf.get("page_size", 22), "sortmode": "ListedDate", "locale": "en-AU"}
            params.update(extra)
            try:
                if conf.get("respect_robots") and not cfg.http.allowed(API):
                    cfg.error("seek", "robots.txt disallows /api/jobsearch/ (seek.respect_robots: true)")
                    return results
                data = cfg.http.get_json(API, params=params)
            except HttpError as exc:
                cfg.error(f"seek '{keyword}' p{page}", exc)
                if exc.status in (0, 403, 429) or exc.status >= 500:
                    return results          # back off for the rest of the run
                failed = True
                break
            rows = data.get("data") or []
            cfg.count_raw(len(rows))
            for job in rows:
                posting = to_posting(job, keyword)
                if posting and posting.source_id not in seen:
                    seen.add(posting.source_id)
                    results.append(posting)
                    if cfg.full(results):
                        return results
            if len(rows) < int(params["pageSize"]):
                break
        if not failed:
            cfg.origins.add(f"seek:{'remote:' if extra.get('workarrangement') else ''}{keyword}")
    return results
