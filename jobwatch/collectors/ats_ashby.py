"""Ashby posting API: api.ashbyhq.com/posting-api/job-board/{tenant}?includeCompensation=true"""
from __future__ import annotations

from ..models import Posting, is_australian, iso, salary_from_text, work_type_of
from .base import CollectorContext, run_per_employer

NAME = "ats_ashby"
API = "https://api.ashbyhq.com/posting-api/job-board/{tenant}"


def parse(payload: dict, employer: dict) -> list[Posting]:
    out = []
    for job in (payload or {}).get("jobs", []):
        if job.get("isListed") is False:
            continue
        addr = ((job.get("address") or {}).get("postalAddress") or {})
        secondary = [s.get("location", "") for s in job.get("secondaryLocations") or [] if isinstance(s, dict)]
        location = " / ".join(x for x in [job.get("location") or ""] + secondary if x)
        country = addr.get("addressCountry")
        if not (is_australian(None, location, addr.get("addressRegion"), addr.get("addressLocality"))
                or is_australian(country)):
            continue
        comp = ((job.get("compensation") or {}).get("compensationTierSummary")
                or (job.get("compensation") or {}).get("scrapeableCompensationSalarySummary"))
        smin, smax, unit = salary_from_text(comp)
        out.append(Posting(
            source=NAME, source_id=f"{employer['tenant']}:{job.get('id') or job.get('jobUrl')}",
            url=job.get("jobUrl") or "", title=job.get("title") or "",
            company=employer.get("name", ""), location=location,
            remote=bool(job.get("isRemote")) or job.get("workplaceType") == "Remote",
            work_type=work_type_of(job.get("employmentType")),
            salary_text=comp, salary_min=smin, salary_max=smax, salary_unit=unit,
            posted_at=iso(job.get("publishedAt")),
            posted_at_source="provider" if job.get("publishedAt") else "observed",
            description=(job.get("descriptionPlain") or "")[:2000],
            raw={k: v for k, v in job.items() if k != "descriptionHtml"},
        ))
    return out


def fetch_one(cfg: CollectorContext, employer: dict):
    payload = cfg.http.get_json(API.format(tenant=employer["tenant"]),
                                params={"includeCompensation": "true"})
    cfg.count_raw(len((payload or {}).get("jobs") or []))
    return parse(payload, employer)


def collect(cfg: CollectorContext, since=None) -> list[Posting]:
    return run_per_employer(cfg, "ashby", fetch_one)
