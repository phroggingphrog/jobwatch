"""Greenhouse job board API: boards-api.greenhouse.io/v1/boards/{tenant}/jobs?content=true"""
from __future__ import annotations

from ..models import Posting, html_to_text, is_australian, iso, work_type_of
from .base import CollectorContext, run_per_employer

NAME = "ats_greenhouse"
API = "https://boards-api.greenhouse.io/v1/boards/{tenant}/jobs"


def parse(payload: dict, employer: dict) -> list[Posting]:
    out = []
    for job in (payload or {}).get("jobs", []):
        location = (job.get("location") or {}).get("name") or ""
        offices = " ".join(o.get("name", "") + " " + (o.get("location") or "")
                           for o in job.get("offices") or [] if isinstance(o, dict))
        if not is_australian(None, location, offices):
            continue
        desc = html_to_text(job.get("content"))
        meta = " ".join(str(m.get("value")) for m in job.get("metadata") or [] if isinstance(m, dict))
        posted = job.get("first_published") or job.get("updated_at")
        out.append(Posting(
            source=NAME, source_id=f"{employer['tenant']}:{job.get('id')}",
            url=job.get("absolute_url") or "", title=job.get("title") or "",
            company=job.get("company_name") or employer.get("name", ""),
            location=location, remote="remote" in location.lower(),
            work_type=work_type_of(meta, job.get("title")),
            posted_at=iso(posted), posted_at_source="provider" if posted else "observed",
            description=desc, raw=job,
        ))
    return out


def fetch_one(cfg: CollectorContext, employer: dict):
    payload = cfg.http.get_json(API.format(tenant=employer["tenant"]), params={"content": "true"})
    cfg.count_raw(len((payload or {}).get("jobs") or []))
    return parse(payload, employer)


def collect(cfg: CollectorContext, since=None) -> list[Posting]:
    return run_per_employer(cfg, "greenhouse", fetch_one)
