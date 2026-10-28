"""Oracle Recruiting Cloud (HCM) candidate-experience sites (registry provider: oracle-hcm).

Public, no login: GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions
  ?onlyData=true&expand=requisitionList.secondaryLocations
  &finder=findReqs;siteNumber={site},limit=25,offset=N,sortBy=POSTING_DATES_DESC
This is the call the employer's own careers site makes for anonymous visitors. Results are
newest first; the collector reads pages until it meets an already-seen requisition or
`max_pages` (default 2 on fast runs, 4 on slow runs). AU gate: primary or secondary location
country is AU. Job URL: https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{Id}.
"""
from __future__ import annotations

import re

from ..models import Posting, is_australian, iso, work_type_of
from .base import CollectorContext, run_per_employer

NAME = "ats_oracle"
PAGE = 25


def api_url(employer: dict, offset: int) -> str:
    base = employer.get("api_url")
    if base:
        base = re.sub(r",offset=\d+", "", base)
        base = re.sub(r"limit=\d+", f"limit={PAGE},offset={offset}", base, count=1)
        if "offset=" not in base:                       # finder had no limit: add both
            base = base.replace(f"siteNumber={employer['site']}",
                                f"siteNumber={employer['site']},limit={PAGE},offset={offset}", 1)
        return base
    return (f"https://{employer['host']}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
            f"?onlyData=true&expand=requisitionList.secondaryLocations"
            f"&finder=findReqs;siteNumber={employer['site']},limit={PAGE},offset={offset},"
            f"sortBy=POSTING_DATES_DESC")


def _locations(req: dict) -> list[tuple[str, str]]:
    """[(name, country)] for primary + secondary locations, VIC first."""
    locs = [(req.get("PrimaryLocation") or "", req.get("PrimaryLocationCountry") or "")]
    for sec in req.get("secondaryLocations") or []:
        locs.append((sec.get("Name") or "", sec.get("CountryCode") or ""))
    locs = [(n, c) for n, c in locs if n or c]
    return sorted(locs, key=lambda x: 0 if re.search(r"\bVIC\b|Victoria", x[0]) else 1)


def req_to_posting(req: dict, employer: dict) -> Posting | None:
    locs = _locations(req)
    au = [(n, c) for n, c in locs if (is_australian(c) if c else is_australian(None, n))]
    if not au:
        return None
    location = " | ".join(n for n, _ in au)[:200]
    host, site = employer["host"], employer["site"]
    workplace = f"{req.get('WorkplaceType') or ''} {req.get('WorkplaceTypeCode') or ''}".lower()
    return Posting(
        source=NAME, source_id=f"{host}:{site}:{req['Id']}",
        url=f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{req['Id']}",
        title=req.get("Title") or "", company=employer.get("name", ""), location=location,
        remote="remote" in workplace,
        work_type=work_type_of(req.get("JobType"), req.get("JobSchedule"), req.get("ContractType")),
        posted_at=iso(req.get("PostedDate")), posted_at_source="provider" if req.get("PostedDate") else "observed",
        description=req.get("ShortDescriptionStr") or "",
        raw={k: v for k, v in req.items() if k in ("Id", "Title", "PostedDate", "PrimaryLocation",
                                                   "PrimaryLocationCountry", "JobType", "JobFunction",
                                                   "WorkplaceType", "secondaryLocations")},
    )


def fetch_one(cfg: CollectorContext, employer: dict):
    max_pages = int(employer.get("max_pages", 4 if cfg.deep else 2))
    out: list[Posting] = []
    for page in range(max_pages):
        data = cfg.http.get_json(api_url(employer, page * PAGE))
        items = data.get("items") or [{}]
        reqs = items[0].get("requisitionList") or []
        total = int(items[0].get("TotalJobsCount") or 0)
        cfg.count_raw(len(reqs))
        hit_known = False
        for req in reqs:
            if not req.get("Id"):
                continue
            posting = req_to_posting(req, employer)
            if posting is None:
                continue
            hit_known = hit_known or cfg.is_known(NAME, posting.source_id)
            out.append(posting)
        if hit_known or len(reqs) < PAGE or (page + 1) * PAGE >= total:
            break
    return out


def collect(cfg: CollectorContext, since=None) -> list[Posting]:
    return run_per_employer(cfg, "oracle-hcm", fetch_one)
