"""Atlassian's own careers listing JSON (registry provider: atlassian), slow tier.

GET https://www.atlassian.com/endpoint/careers/listings (public, allowed by robots.txt): a list
of {id, title, type, locations[], category, overview, applyUrl, portalJobPost{updatedDate}}.
About 350 jobs worldwide, ~11 in Australia. Locations look like
"Melbourne - Australia -   Melbourne,  3000 Australia"; only Australian ones are kept.
updatedDate is not a posting date, so postings are observed-dated (first read seeds).
"""
from __future__ import annotations

import re

from ..models import Posting, html_to_text, work_type_of
from .base import CollectorContext, run_per_employer

NAME = "ats_atlassian"
DEFAULT_URL = "https://www.atlassian.com/endpoint/careers/listings"


def _place(loc: str) -> str:
    # "Melbourne - Australia -   Melbourne,  3000 Australia" -> "Melbourne, Australia"
    head = [p.strip() for p in loc.split(" - ") if p.strip()]
    return f"{head[0]}, Australia" if head else loc


def row_to_posting(row: dict, employer: dict) -> Posting | None:
    au = [_place(l) for l in row.get("locations") or [] if re.search(r"\bAustralia\b", l)]
    if not au:
        return None
    portal = row.get("portalJobPost") or {}
    url = portal.get("portalUrl") or (row.get("applyUrl") or "").split("?")[0]
    return Posting(
        source=NAME, source_id=f"atlassian:{row.get('id')}", url=url, title=row.get("title") or "",
        company=employer.get("name", "Atlassian"), location=" | ".join(dict.fromkeys(au)),
        work_type=work_type_of(row.get("type")),
        description=html_to_text(row.get("responsibilities") or row.get("overview")),
        raw={k: row.get(k) for k in ("id", "title", "type", "locations", "category", "applyUrl")},
    )


def fetch_one(cfg: CollectorContext, employer: dict):
    rows = cfg.http.get_json(employer.get("api_url") or DEFAULT_URL)
    rows = rows if isinstance(rows, list) else []
    cfg.count_raw(len(rows))
    return [p for p in (row_to_posting(r, employer) for r in rows) if p]


def collect(cfg: CollectorContext, since=None) -> list[Posting]:
    return run_per_employer(cfg, "atlassian", fetch_one)
