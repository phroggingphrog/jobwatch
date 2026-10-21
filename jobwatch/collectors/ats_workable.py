"""Workable widget API: apply.workable.com/api/v1/widget/accounts/{tenant}?details=true"""
from __future__ import annotations

from ..models import Posting, html_to_text, is_australian, iso, work_type_of
from .base import CollectorContext, run_per_employer

NAME = "ats_workable"
API = "https://apply.workable.com/api/v1/widget/accounts/{tenant}"


def parse(payload: dict, employer: dict) -> list[Posting]:
    out = []
    for job in (payload or {}).get("jobs", []):
        locs = job.get("locations") or [{"country": job.get("country"), "countryCode": None,
                                         "city": job.get("city"), "region": job.get("state")}]
        au = [l for l in locs if isinstance(l, dict) and (
            is_australian(l.get("countryCode")) if l.get("countryCode")
            else is_australian(l.get("country")) if l.get("country")
            else is_australian(None, l.get("city"), l.get("region")))]
        if not au:
            continue
        first = au[0]
        location = ", ".join(x for x in (first.get("city"), first.get("region"), "Australia") if x)
        posted = job.get("published_on") or job.get("created_at")
        out.append(Posting(
            source=NAME, source_id=f"{employer['tenant']}:{job.get('shortcode')}",
            url=job.get("url") or job.get("shortlink") or "", title=job.get("title") or "",
            company=(payload or {}).get("name") or employer.get("name", ""), location=location,
            remote=bool(job.get("telecommuting")), work_type=work_type_of(job.get("employment_type")),
            posted_at=iso(posted), posted_at_source="provider" if posted else "observed",
            description=html_to_text(job.get("description")), raw=job,
        ))
    return out


def fetch_one(cfg: CollectorContext, employer: dict):
    payload = cfg.http.get_json(API.format(tenant=employer["tenant"]), params={"details": "true"})
    cfg.count_raw(len((payload or {}).get("jobs") or []))
    return parse(payload, employer)


def collect(cfg: CollectorContext, since=None) -> list[Posting]:
    return run_per_employer(cfg, "workable", fetch_one)
