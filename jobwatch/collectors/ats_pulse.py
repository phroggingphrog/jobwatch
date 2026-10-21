"""Pulse Software recruitment portals (registry provider: pulse), used by Banyule, Brimbank, Manningham.

Each tenant's public job page (https://{tenant}.pulsesoftware.com/Pulse/jobs) is a Vue app that loads its
list from an anonymous JSON call: GET https://{tenant}.pulsesoftware.com/WebServices/RCM/Jobs/Jobs
?internalOnly=false&workArrangement=&employmentType=  -> {"Jobs": [{"JobInfo": {...}, "LinkId", "ApplyUrl"}]}.
It returns every open external job in one response (verified 2026-10-06, 2-9 jobs per council).
robots.txt on these hosts is a 404 (allowed); the Fetcher still checks it once per run.
JobInfo gives Title, PostDate ("5 Oct 2026"), ClosingDate, Location (street address), Department,
Compensation, EmploymentType, WorkArrangement, Summary and Description (HTML).
Registry fields: tenant (subdomain), optional host / api_url, state (VIC for councils).
"""
from __future__ import annotations

import json

from ..models import Posting, html_to_text, iso, salary_from_text, work_type_of
from .base import CollectorContext, run_per_employer

NAME = "ats_pulse"
QUERY = "internalOnly=false&workArrangement=&employmentType="


def host_of(employer: dict) -> str:
    return employer.get("host") or f"{employer['tenant']}.pulsesoftware.com"


def api_url(employer: dict) -> str:
    return employer.get("api_url") or f"https://{host_of(employer)}/WebServices/RCM/Jobs/Jobs?{QUERY}"


def parse_jobs(data: dict, employer: dict) -> list[Posting]:
    host, tenant = host_of(employer), employer.get("tenant") or host_of(employer).split(".")[0]
    out = []
    for job in data.get("Jobs") or []:
        info = job.get("JobInfo") or {}
        link = job.get("LinkId")
        if not info.get("Title") or not link:
            continue
        url = job.get("ApplyUrl") or f"https://{host}/Pulse/job/{link}"
        pay = info.get("Compensation") or ""
        smin, smax, unit = salary_from_text(pay)
        posted = iso(info.get("PostDate"))
        location = info.get("Location") or ""
        out.append(Posting(
            source=NAME, source_id=f"{tenant}:{link}", url=url, title=info["Title"],
            company=employer.get("name", ""), location=location, state=employer.get("state") or None,
            remote="remote" in str(info.get("WorkArrangement") or "").lower(),
            work_type=work_type_of(info.get("EmploymentType")),
            salary_text=pay or None, salary_min=smin, salary_max=smax, salary_unit=unit,
            posted_at=posted, posted_at_source="provider" if posted else "observed",
            description=html_to_text(info.get("Description") or info.get("Summary")),
            raw={k: info.get(k) for k in ("Title", "PostDate", "ClosingDate", "Location", "Department",
                                          "Compensation", "EmploymentType", "WorkArrangement", "JobRef")},
        ))
    return out


def fetch_one(cfg: CollectorContext, employer: dict):
    text = cfg.http.get_text(api_url(employer), robots=True, headers={"Accept": "application/json"})
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"{host_of(employer)} did not return JSON") from exc
    cfg.count_raw(len(data.get("Jobs") or []))
    return parse_jobs(data, employer)


def collect(cfg: CollectorContext, since=None) -> list[Posting]:
    return run_per_employer(cfg, "pulse", fetch_one)
