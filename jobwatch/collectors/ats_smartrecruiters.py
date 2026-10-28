"""SmartRecruiters public API: api.smartrecruiters.com/v1/companies/{tenant}/postings?country=au

Listing rows carry no description; the detail call is made only for titles that pass the
target-arm pre-check, capped at `detail_cap` (default 10) per employer per run.
"""
from __future__ import annotations

from ..http import HttpError
from ..models import Posting, html_to_text, is_australian, iso, work_type_of
from .base import CollectorContext, run_per_employer

NAME = "ats_smartrecruiters"
API = "https://api.smartrecruiters.com/v1/companies/{tenant}/postings"
PAGE = 100
MAX_PAGES = 3


def to_posting(job: dict, employer: dict, description: str = "") -> Posting | None:
    loc = job.get("location") or {}
    if not is_australian(loc.get("country"), loc.get("fullLocation")):
        return None
    location = loc.get("fullLocation") or ", ".join(x for x in (loc.get("city"), loc.get("region")) if x)
    location = location.replace(", ,", ",")
    tenant = employer["tenant"]
    return Posting(
        source=NAME, source_id=f"{tenant}:{job.get('id')}",
        url=f"https://jobs.smartrecruiters.com/{tenant}/{job.get('id')}",
        title=job.get("name") or "", company=(job.get("company") or {}).get("name") or employer.get("name", ""),
        location=location, remote=bool(loc.get("remote")),
        work_type=work_type_of((job.get("typeOfEmployment") or {}).get("label")),
        posted_at=iso(job.get("releasedDate")),
        posted_at_source="provider" if job.get("releasedDate") else "observed",
        description=description, raw=job,
    )


def detail_text(detail: dict) -> str:
    sections = ((detail or {}).get("jobAd") or {}).get("sections") or {}
    parts = [html_to_text((sections.get(k) or {}).get("text"), 1200)
             for k in ("jobDescription", "qualifications", "additionalInformation")]
    return "\n".join(p for p in parts if p)[:2000]


def fetch_one(cfg: CollectorContext, employer: dict):
    tenant = employer["tenant"]
    rows: list[dict] = []
    for page in range(MAX_PAGES):
        data = cfg.http.get_json(API.format(tenant=tenant),
                                 params={"country": "au", "limit": PAGE, "offset": page * PAGE})
        content = data.get("content") or []
        rows += content
        if len(content) < PAGE or len(rows) >= int(data.get("totalFound") or 0):
            break
    cfg.count_raw(len(rows))
    cap = int(employer.get("detail_cap", 10))
    out = []
    for job in rows:
        posting = to_posting(job, employer)
        if posting is None:
            continue
        if cap > 0 and cfg.title_relevant(posting.title) and not cfg.is_known(NAME, posting.source_id):
            cap -= 1
            try:
                posting.description = detail_text(cfg.http.get_json(f"{API.format(tenant=tenant)}/{job.get('id')}"))
            except HttpError as exc:
                cfg.error(f"{employer.get('name')} detail", exc)
        out.append(posting)
    return out


def collect(cfg: CollectorContext, since=None) -> list[Posting]:
    return run_per_employer(cfg, "smartrecruiters", fetch_one)
