"""Careers.Vic (Victorian Government jobs board): server-rendered HTML job list.

https://www.careers.vic.gov.au/jobs?keywords=&page=N lists 15 jobs per page, newest first.
robots.txt allows /jobs and /job/ (re-checked 2026-10-06; the Fetcher checks it every run).
Switched on by an enabled registry entry with provider: careers_vic (optional fast_pages /
deep_pages). Fast runs read pages 1-2, slow/all runs up to 10 pages; both stop after the first page that
holds an already-seen job id. Each result block gives title, department/agency, work type,
salary, grade (VPS classification), occupation, location and closing date. The board is VIC
only, so postings get state VIC. Grades feed the seniority rules (VPS 5+ excluded, VPS 1-3
flagged entry level). No posted date in the list: observed-dated, the first read seeds.
"""
from __future__ import annotations

import html
import re

from ..models import Posting, clean_text, html_to_text, salary_from_text, work_type_of
from .base import CollectorContext

NAME = "careers_vic"
BASE = "https://www.careers.vic.gov.au"
LIST_URL = f"{BASE}/jobs"
FAST_PAGES, DEEP_PAGES = 2, 10

_BLOCK = '<rpl-content class="job-searchResult">'
_LINK = re.compile(r'<a[^>]+href="(/job/[^"]+)"[^>]*>\s*<h3>(.*?)</h3>', re.S)
_DEPT = re.compile(r'</a>\s*<p[^>]*>(.*?)</p>', re.S)
_DETAIL = re.compile(r'<p><strong>(.*?)</strong></p>\s*<p>(.*?)</p>', re.S)
_DESC = re.compile(r'class="job-searchResult-description">(.*?)</rpl-content>', re.S)
_ID = re.compile(r"-(\d+)/?$")
_OTHER_STATE = re.compile(r"\b(interstate|overseas|NSW|QLD|ACT|Sydney|Canberra|Brisbane)\b", re.I)
_VPS = re.compile(r"\bVPS\s*(?:grade\s*)?(\d)(?:\.\d)?\b", re.I)


def normalise_grade(grade: str) -> str | None:
    """'VPS Grade 3.2' -> 'VPS 3'; 'Grade not specified' -> None; others pass through."""
    grade = clean_text(grade)
    if not grade or "not specified" in grade.lower():
        return None
    m = _VPS.search(grade)
    return f"VPS {m.group(1)}" if m else grade


def parse_page(text: str) -> list[Posting]:
    out = []
    for block in text.split(_BLOCK)[1:]:
        link = _LINK.search(block)
        if not link:
            continue
        path = link.group(1)
        m = _ID.search(path)
        job_id = m.group(1) if m else path
        dept = _DEPT.search(block[link.end():])
        details = {clean_text(k).rstrip(":").lower(): clean_text(html_to_text(v))
                   for k, v in _DETAIL.findall(block)}
        location = details.get("location", "")
        state = None if _OTHER_STATE.search(location) else "VIC"
        if state and location and "vic" not in location.lower():
            location = f"{location}, VIC"
        salary = details.get("salary", "")
        smin, smax, unit = salary_from_text(salary) if "$" in salary else (None, None, None)
        desc = _DESC.search(block)
        out.append(Posting(
            source=NAME, source_id=job_id, url=f"{BASE}{path}",
            title=html.unescape(re.sub(r"<[^>]+>", " ", link.group(2))),
            company=html_to_text(dept.group(1)) if dept else "Victorian Government",
            location=location, state=state,
            work_type=work_type_of(details.get("work type")),
            salary_text=salary if smin else None, salary_min=smin, salary_max=smax, salary_unit=unit,
            classification=normalise_grade(details.get("grade", "")),
            description=html_to_text(desc.group(1)) if desc else "",
            raw={"id": job_id, "path": path, **details},
            origin="Careers.Vic",
        ))
    return out


def collect(cfg: CollectorContext, since=None) -> list[Posting]:
    entries = cfg.employers_for("careers_vic")          # registry entry switches it on/off
    if not entries:
        return []
    entry = entries[0]
    pages = int(entry.get("deep_pages" if cfg.deep else "fast_pages", DEEP_PAGES if cfg.deep else FAST_PAGES))
    results: list[Posting] = []
    for page in range(pages):
        try:
            text = cfg.http.get_text(LIST_URL, params={"keywords": "", "page": page}, robots=True)
        except Exception as exc:   # HttpError / Blocked: record and stop paging
            cfg.error(f"Careers.Vic page {page + 1}", exc)
            break
        found = parse_page(text)
        cfg.count_raw(len(found))
        cfg.origins.add(f"careers_vic:{entry.get('name', 'Careers.Vic')}")
        known = any(cfg.is_known(NAME, p.source_id) for p in found)
        results += found
        if cfg.full(results) or known or len(found) < 15:
            break
    return results[: cfg.limit] if cfg.limit else results
