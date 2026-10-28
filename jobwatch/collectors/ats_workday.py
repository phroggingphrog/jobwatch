"""Workday CXS: POST https://{host}/wday/cxs/{tenant}/{site}/jobs {searchText, appliedFacets, limit, offset}

Registry fields: host (e.g. nab.wd3.myworkdayjobs.com), tenant, site, optional search_text
(string or list), applied_facets (dict), max_pages (default 3 x 20 rows), detail_cap (10).
Titles prioritize a bounded, rotating detail queue. Ambiguous listings remain
available for full-ad retrieval even when their turn does not fit this run's cap.
"""
from __future__ import annotations

from jobwatch.util.http import HttpError
from ..models import Posting, html_to_text, is_australian, iso, relative_posted, work_type_of
from .base import CollectorContext, rotate, run_per_employer

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
        country = info.get("country") or {}
        code = (country.get('alpha2Code') or country.get('code') or country.get('name') or country.get('descriptor')) \
            if isinstance(country, dict) else country
        if code and not (is_australian(country) or any(is_australian(None, x) for x in extra)):
            return None
    if location and location[0].isdigit() and "location" in location.lower():
        # "2 Locations" and an opaque URL segment are not geographic evidence.
        candidate = _path_words(path)
        location = candidate if is_australian(None, candidate) else ''
    if extra:
        location = ' | '.join(dict.fromkeys([location, *(str(x) for x in extra)]))
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
    cap = max(0, int(employer.get("detail_cap", 10)))
    seen, out, listings = set(), [], []
    non_au_key = f"workday_non_au:{tenant}"
    non_au = set(cfg.state_get(non_au_key, []) or [])
    detailed_key = f'workday_detailed:{tenant}:{site}'
    detailed = set(cfg.state_get(detailed_key, []) or [])
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
                source_id = f"{tenant}:{(row.get('bulletFields') or [path])[0]}"
                if source_id not in non_au:
                    listings.append((row, source_id))
            if len(rows) < PAGE or (page + 1) * PAGE >= int(data.get("total") or 0):
                break
    candidates = sorted((item for item in listings if not (item[1] in detailed and cfg.is_known(NAME, item[1]))),
                        key=lambda item: not cfg.title_relevant(item[0].get('title') or ''))
    # Relevance determines the initial order, never membership. Persisted rotation
    # ensures ambiguous titles eventually receive detail calls under the same cap.
    chosen = {sid for _, sid in rotate(cfg, f'workday_detail:{tenant}:{site}', candidates, cap)} if cap else set()
    for row, source_id in listings:
        posting = row_to_posting(row, employer)
        if source_id in chosen:
            try:
                posting = row_to_posting(row, employer, cfg.http.get_json(f"{api}{row['externalPath']}"))
                if posting is None:
                    non_au.add(source_id)
                elif posting.description:
                    detailed.add(source_id)
            except HttpError as exc:
                cfg.error(f"{employer.get('name')} detail", exc)
        if posting is not None:
            out.append(posting)
    cfg.state_set(non_au_key, sorted(non_au)[-2000:])
    cfg.state_set(detailed_key, sorted(detailed)[-2000:])
    return out


def collect(cfg: CollectorContext, since=None) -> list[Posting]:
    return run_per_employer(cfg, "workday", fetch_one)
