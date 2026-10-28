"""Employment Hero careers API (per archived au_ats.py contract):
GET https://services.employmenthero.com/ats/api/v1/career_page/organisations/{tenant}/jobs
    ?page_index={n}&item_per_page=50   (data.items, data.total_pages; capped at 5 pages)
"""
from __future__ import annotations

from urllib.parse import quote

from ..models import Posting, html_to_text, is_australian, iso, work_type_of
from .base import CollectorContext, run_per_employer

NAME = "ats_employmenthero"
API = "https://services.employmenthero.com/ats/api/v1/career_page/organisations/{tenant}/jobs"
MAX_PAGES = 5


def parse(payload: dict, employer: dict) -> list[Posting]:
    data = (payload or {}).get("data") or {}
    out = []
    for item in data.get("items") or []:
        remote = item.get("remote_setting") if isinstance(item.get("remote_setting"), dict) else {}
        country = item.get("country_code") or remote.get("country_code")
        location = item.get("vendor_location_name") or item.get("location") or ""
        if not is_australian(country, location):
            continue
        friendly = item.get("friendly_id")
        if not friendly:
            continue
        smin, smax = item.get("salary_min"), item.get("salary_max")
        unit = {"hour": "hour", "year": "year", "annum": "year", "month": "month", "day": "day",
                "week": "week"}.get(str(item.get("salary_rate_name") or "").lower())
        out.append(Posting(
            source=NAME, source_id=f"{employer['tenant']}:{item.get('id')}",
            url=f"https://employmenthero.com/jobs/position/{quote(str(friendly), safe='')}/",
            title=item.get("title") or "", company=item.get("organisation_name") or employer.get("name", ""),
            location=location,
            remote=bool(item.get("remote")) or item.get("workplace_type") == "remote",
            work_type=work_type_of(item.get("employment_type_name"), item.get("employment_term_name")),
            salary_min=smin if not item.get("hide_pay_rate") else None,
            salary_max=smax if not item.get("hide_pay_rate") else None,
            salary_unit=unit if smin and not item.get("hide_pay_rate") else None,
            salary_text=(f"{item.get('salary_currency', 'AUD')} {smin}-{smax} per {item.get('salary_rate_name')}"
                         if smin and not item.get("hide_pay_rate") else None),
            posted_at=iso(item.get("created_at")),
            posted_at_source="provider" if item.get("created_at") else "observed",
            description=html_to_text(item.get("description")),
            raw={k: v for k, v in item.items() if k not in ("recruitment_logo", "organisation_logo")},
        ))
    return out


def fetch_one(cfg: CollectorContext, employer: dict):
    out = []
    url = API.format(tenant=quote(employer["tenant"], safe=""))
    for page in range(1, MAX_PAGES + 1):
        payload = cfg.http.get_json(url, params={"page_index": page, "item_per_page": 50})
        out += parse(payload, employer)
        data = (payload or {}).get("data") or {}
        cfg.count_raw(len(data.get("items") or []))
        total = data.get("total_pages")
        if not data.get("items") or (isinstance(total, int) and page >= total):
            break
    return out


def collect(cfg: CollectorContext, since=None) -> list[Posting]:
    return run_per_employer(cfg, "employmenthero", fetch_one)
