"""Lever postings API: api.lever.co/v0/postings/{tenant}?mode=json (api.eu.lever.co if region: eu)."""
from __future__ import annotations

from ..models import Posting, is_australian, iso, work_type_of
from .base import CollectorContext, run_per_employer

NAME = "ats_lever"


def parse(payload: list, employer: dict) -> list[Posting]:
    out = []
    for job in payload if isinstance(payload, list) else []:
        cats = job.get("categories") or {}
        locations = cats.get("allLocations") or [cats.get("location") or ""]
        location = " / ".join(x for x in locations if x)
        if not is_australian(job.get("country"), location):
            continue
        salary = job.get("salaryRange") or {}
        unit = {"per-year-salary": "year", "per-hour-wage": "hour", "per-month-salary": "month",
                "per-day-wage": "day", "per-week-wage": "week"}.get(salary.get("interval"))
        out.append(Posting(
            source=NAME, source_id=f"{employer['tenant']}:{job.get('id')}",
            url=job.get("hostedUrl") or "", title=job.get("text") or "",
            company=employer.get("name", ""), location=location,
            remote=(job.get("workplaceType") == "remote") or "remote" in location.lower(),
            work_type=work_type_of(cats.get("commitment")),
            salary_min=salary.get("min"), salary_max=salary.get("max"), salary_unit=unit,
            salary_text=(f"{salary.get('currency', '')} {salary.get('min')}-{salary.get('max')}"
                         if salary.get("min") else None),
            posted_at=iso(job.get("createdAt")),
            posted_at_source="provider" if job.get("createdAt") else "observed",
            description=(job.get("descriptionPlain") or "")[:2000], raw=job,
        ))
    return out


def fetch_one(cfg: CollectorContext, employer: dict):
    host = "api.eu.lever.co" if str(employer.get("region", "")).lower() == "eu" else "api.lever.co"
    payload = cfg.http.get_json(f"https://{host}/v0/postings/{employer['tenant']}", params={"mode": "json"})
    if isinstance(payload, dict) and payload.get("ok") is False:
        raise ValueError(payload.get("error") or "lever board not found")
    cfg.count_raw(len(payload) if isinstance(payload, list) else 0)
    return parse(payload, employer)


def collect(cfg: CollectorContext, since=None) -> list[Posting]:
    return run_per_employer(cfg, "lever", fetch_one)
