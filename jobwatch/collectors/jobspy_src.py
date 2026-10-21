"""python-jobspy scrape_jobs for LinkedIn, Indeed (Australia) and Google.

searches.yaml -> jobspy: sites, location ("Melbourne, VIC"), hours_old (default 6),
results_wanted (<= 25), searches_per_run (rotation), searches: [{term, google_term?}].
No proxies. JobSpy makes its own requests; we pause between searches.
"""
from __future__ import annotations

import logging
import math
import time
from contextlib import contextmanager
from typing import Any

from ..models import Posting, is_australian, iso, work_type_of
from .base import CollectorContext, rotate

NAME = "jobspy_src"


def _clean(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if type(value).__module__ == "numpy":
        return value.item()
    return value


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(f"{record.name.split(':')[-1]}: {record.getMessage()}"[:200])


@contextmanager
def capture_jobspy_logs():
    """JobSpy logs site failures (e.g. 'Google response status code 429') instead of raising.
    Route them into the collector's error list rather than stderr."""
    handler = _Capture()
    saved = {}
    for site in ("LinkedIn", "Indeed", "Google"):
        logger = logging.getLogger(f"JobSpy:{site}")
        saved[site] = logger.handlers[:]
        logger.handlers = [handler]
        logger.propagate = False
    try:
        yield handler.messages
    finally:
        for site, handlers in saved.items():
            logging.getLogger(f"JobSpy:{site}").handlers = handlers


def row_to_posting(row: dict, term: str) -> Posting | None:
    row = {k: _clean(v) for k, v in row.items()}
    location = row.get("location") or ""
    if not is_australian(None, location, "Australia" if row.get("site") == "indeed" else ""):
        return None
    interval = row.get("interval")
    unit = {"yearly": "year", "hourly": "hour", "monthly": "month", "weekly": "week",
            "daily": "day"}.get(str(interval or "").lower())
    smin, smax = row.get("min_amount"), row.get("max_amount")
    salary_text = None
    if smin or smax:
        salary_text = f"{row.get('currency') or 'AUD'} {smin or ''}-{smax or ''} {interval or ''}".strip()
    site = row.get("site") or "jobspy"
    posted = row.get("date_posted")
    return Posting(
        source=NAME, source_id=f"{site}:{row.get('id') or row.get('job_url')}",
        url=row.get("job_url") or row.get("job_url_direct") or "",
        title=row.get("title") or "", company=row.get("company") or "", location=location,
        remote=bool(row.get("is_remote")), work_type=work_type_of(row.get("job_type")),
        salary_text=salary_text, salary_min=smin, salary_max=smax, salary_unit=unit,
        posted_at=iso(posted), posted_at_source="provider" if posted else "observed",
        description=(row.get("description") or "")[:2000],
        raw={k: v for k, v in row.items() if k not in ("description", "emails")},
        flags=[f"via_{site}"], origin=f"jobspy:{site}:{term}",
    )


def collect(cfg: CollectorContext, since=None, scrape=None) -> list[Posting]:
    conf = cfg.config.searches.get("jobspy") or {}
    if conf.get("enabled") is False:
        return []
    if scrape is None:
        from jobspy import scrape_jobs as scrape
    searches = rotate(cfg, "jobspy", list(conf.get("searches") or []), conf.get("searches_per_run"))
    sites = conf.get("sites") or ["linkedin", "indeed", "google"]
    location = conf.get("location") or cfg.config.searches.get("location") or "Melbourne, VIC"
    results: list[Posting] = []
    for i, search in enumerate(searches):
        if cfg.full(results):
            break
        search = search if isinstance(search, dict) else {"term": str(search)}
        term = search["term"]
        where = search.get("location") or location      # e.g. "Australia" for remote searches
        if i:
            time.sleep(float(conf.get("pause_seconds", 2)))
        wanted = min(int(conf.get("results_wanted", 20)), 25)
        if cfg.limit:
            wanted = min(wanted, cfg.limit)
        try:
            with capture_jobspy_logs() as messages:
                frame = scrape(
                    site_name=search.get("sites") or sites, search_term=term,
                    google_search_term=search.get("google_term") or f"{term} jobs near {where} since yesterday",
                    location=where, is_remote=bool(search.get("is_remote")), results_wanted=wanted,
                    hours_old=int(conf.get("hours_old", 6)), country_indeed="Australia",
                    description_format="markdown", verbose=0,
                )
            for message in messages:
                cfg.error(f"jobspy '{term}'", message)
        except Exception as exc:  # jobspy raises assorted errors per site
            cfg.error(f"jobspy '{term}'", f"{type(exc).__name__}: {str(exc)[:160]}")
            continue
        rows = frame.to_dict("records") if frame is not None and len(frame) else []
        cfg.count_raw(len(rows))
        for row in rows:
            posting = row_to_posting(row, term)
            if posting:
                results.append(posting)
        cfg.origins.add(f"jobspy:{term}")
    return results[: cfg.limit] if cfg.limit else results
