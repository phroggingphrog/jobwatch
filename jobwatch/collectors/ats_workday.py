"""Workday CXS: POST https://{host}/wday/cxs/{tenant}/{site}/jobs {searchText, appliedFacets, limit, offset}

Registry fields: host (e.g. nab.wd3.myworkdayjobs.com), tenant, site, optional search_text
(string or list), applied_facets (dict), max_pages (default 3 x 20 rows), detail_cap (10).
Rows whose listing location is ambiguous ("2 Locations") get one detail call, but only
when the title passes the target-arm pre-check.
"""
from __future__ import annotations

from ..http import HttpError
from ..models import Posting, html_to_text, is_australian, iso, relative_posted, work_type_of
from .base import CollectorContext, run_per_employer

NAME = "ats_workday"
PAGE = 20


def _path_words(path: str) -> str:
    # /job/Melbourne-VIC/Graduate-Analyst_R123 -> "Melbourne VIC"
    parts = [p for p in (path or "").split("/") if p]
    return parts[1].replace("-", " ") if len(parts) > 2 else ""


def row_to_posting(row: dict, employer: dict, detail: dict | None = None) -> Posting | None:
    info = (detail or {}).get("jobPostingInfo") or {}
    host, site = employer["host"], employer["site"]
    path = row.get("externalPath") or ""
    location = info.get("location") or row.get("locationsText") or ""
    extra = info.get("additionalLocations") or []
    if info:
        country = (info.get("country") or {})
        if not (is_australian(country) or any(is_australian(None, x) for x in extra)):
            return None
    elif not is_australian(None, row.get("locationsText"), _path_words(path)):
        return None
    if location and location[0].isdigit() and "location" in location.lower():
        location = _path_words(path) or location
    posted = iso(info.get("startDate")) if info.get("startDate") else None
    if not posted:
        rel = relative_posted(row.get("postedOn") or "")
        posted = rel.isoformat(timespec="seconds") if rel else None
    bullet = row.get("bulletFields") or []
    return Posting(
        source=NAME, source_id=f"{employer['tenant']}:{bullet[0] if bullet else path}",
        url=f"https://{host}/{site}{path}", title=row.get("title") or info.get("title") or "",
        company=employer.get("name", ""), location=location,
        remote=any(w in (location + " " + row.get("remoteType", "")).lower() for w in ("remote", "flexible")),
        work_type=work_type_of(info.get("timeType")),
        posted_at=posted, posted_at_source="provider" if posted else "observed",
        description=html_to_text(info.get("jobDescription")), raw={"row": row, "detail": info or None},
    )


def fetch_one(cfg: CollectorContext, employer: dict):
    host, tenant, site = employer["host"], employer["tenant"], employer["site"]
    api = f"https://{host}/wday/cxs/{tenant}/{site}"
    texts = employer.get("search_text", "")
    texts = texts if isinstance(texts, list) else [texts]
    max_pages = int(employer.get("max_pages", 3))
    cap = int(employer.get("detail_cap", 10))
    seen, out = set(), []
    non_au_key = f"workday_non_au:{tenant}"
    non_au = set(cfg.state_get(non_au_key, []) or [])
    for text in texts:
        for page in range(max_pages):
            body = {"appliedFacets": employer.get("applied_facets") or {}, "limit": PAGE,
                    "offset": page * PAGE, "searchText": text or ""}
            data = cfg.http.post_json(f"{api}/jobs", body)
            rows = data.get("jobPostings") or []
            cfg.count_raw(len(rows))
            for row in rows:
                path = row.get("externalPath")
                if not path or path in seen:
                    continue
                seen.add(path)
                posting = row_to_posting(row, employer)
                source_id = f"{tenant}:{(row.get('bulletFields') or [path])[0]}"
                # Listing location not clearly AU ("2 Locations", "Telstra Store X"), or AU
                # but no description yet: one detail call for target-looking titles only.
                wants_detail = cap > 0 and source_id not in non_au \
                    and cfg.title_relevant(row.get("title") or "") and not cfg.is_known(NAME, source_id)
                if wants_detail:
                    cap -= 1
                    try:
                        posting = row_to_posting(row, employer, cfg.http.get_json(f"{api}{path}"))
                        if posting is None:
                            non_au.add(source_id)
                    except HttpError as exc:
                        cfg.error(f"{employer.get('name')} detail", exc)
                if posting is not None:
                    out.append(posting)
            if len(rows) < PAGE or (page + 1) * PAGE >= int(data.get("total") or 0):
                break
    cfg.state_set(non_au_key, sorted(non_au)[-2000:])
    return out


def collect(cfg: CollectorContext, since=None) -> list[Posting]:
    return run_per_employer(cfg, "workday", fetch_one)
