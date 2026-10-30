"""Adzuna AU job search API (public, keyed): https://api.adzuna.com/v1/api/jobs/au/search/<page>

A sanctioned aggregator rather than a scrape: no browser fingerprint, no bot wall, and a documented JSON
shape. It covers Australia and returns full descriptions, salary where the advertiser gave one, and the
original posting date, so it fills the gap that LinkedIn and Indeed leave when they block us.

The keys never live in this file or in config. `searches.yaml -> adzuna.app_id_file` / `app_key_file` name
the files that hold them; the value is read at run time and never logged. With no key the collector records
a clean `not_configured` error and collects nothing, so a missing key is visible, not silent.
"""
from __future__ import annotations

import logging
from pathlib import Path

from jobwatch.util.place import location_text

from jobwatch.util.http import HttpError
from ..models import Posting, iso, work_type_of
from .base import CollectorContext, rotate

NAME = "adzuna"
API = "https://api.adzuna.com/v1/api/jobs/au/search"
log = logging.getLogger("jobwatch.collectors")


def _secret(path: str | None) -> str:
    if not path:
        return ""
    try:
        return Path(path).expanduser().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def to_posting(job: dict) -> Posting | None:
    jid = str(job.get("id") or "").strip()
    title = (job.get("title") or "").strip()
    if not jid or not title:
        return None
    location = ((job.get("location") or {}).get("display_name") or "").strip()
    company = ((job.get("company") or {}).get("display_name") or "").strip()
    # Adzuna gives numbers, not a formatted range, so take them directly and keep a readable label beside them.
    lo, hi = job.get("salary_min"), job.get("salary_max")
    numbers = [float(v) for v in (lo, hi) if isinstance(v, (int, float)) and v]
    smin = min(numbers) if numbers else None
    smax = max(numbers) if numbers else None
    unit = "year" if numbers and max(numbers) > 2000 else (None if not numbers else "hour")
    salary_text = (f"${int(smin):,} - ${int(smax):,} a year" if smin and smax and unit == "year"
                   else (f"${int(smin):,} a year" if smin and unit == "year" else "")) or None
    contract = " ".join(job.get("contract_time") and [job["contract_time"]] or [])
    return Posting(
        source=NAME, source_id=jid, url=job.get("redirect_url") or f"https://www.adzuna.com.au/details/{jid}",
        title=title, company=company, location=location,
        remote="remote" in f"{location} {title} {job.get('contract_type') or ''}".lower(),
        work_type=work_type_of(contract, job.get("contract_type") or ""),
        salary_text=salary_text or None, salary_min=smin, salary_max=smax, salary_unit=unit,
        posted_at=iso(job.get("created")),
        posted_at_source="provider" if job.get("created") else "observed",
        description=(job.get("description") or "").strip()[:2000],
        raw=job,
    )


def collect(cfg: CollectorContext) -> list[Posting]:
    conf = cfg.config.searches.get("adzuna") or {}
    if conf.get("enabled") is False:
        return []
    app_id = conf.get("app_id") or _secret(conf.get("app_id_file"))
    app_key = _secret(conf.get("app_key_file"))
    if not app_id or not app_key:
        cfg.error("adzuna", f"not_configured: put the Adzuna app id and key in {conf.get('app_id_file') or 'searches.yaml'} "
                            f"and {conf.get('app_key_file') or 'searches.yaml'}")
        return []
    keywords = rotate(cfg, NAME, conf.get("searches") or conf.get("keywords") or [""],
                      int(conf.get("searches_per_run", 3)))
    where = conf.get("where") or location_text() or "Australia"
    per_page = max(1, min(int(conf.get("results_per_page", 25)), cfg.limit or 50))
    max_days = int(conf.get("max_days_old", 2))
    pages = max(1, min(int(conf.get("pages", 1)), 5))
    results: list[Posting] = []
    seen: set[str] = set()
    for keyword in keywords:
        for page in range(1, pages + 1):
            params = {"app_id": app_id, "app_key": app_key, "results_per_page": per_page,
                      "what": keyword, "where": where, "max_days_old": max_days,
                      "sort_by": "date", "content-type": "application/json"}
            if conf.get("category"):
                params["category"] = conf["category"]
            try:
                data = cfg.http.get_json(f"{API}/{page}", params=params)
            except HttpError as exc:
                cfg.error(f"adzuna '{keyword}' p{page}", exc)
                if exc.status in (0, 401, 403, 429) or exc.status >= 500:
                    return results      # a key or quota problem will not improve this run
                break
            rows = (data or {}).get("results") or []
            cfg.count_raw(len(rows))
            for job in rows:
                posting = to_posting(job)
                if posting and posting.source_id not in seen:
                    seen.add(posting.source_id)
                    results.append(posting)
                    if cfg.full(results):
                        return results
            if len(rows) < per_page:
                break
    return results
