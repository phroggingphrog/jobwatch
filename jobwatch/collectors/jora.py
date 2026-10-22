"""Jora AU search pages (HTML, no login): https://au.jora.com/j?q=<kw>&l=<location>&sp=recent&a=24h

Jora sits behind a bot wall that refuses plain HTTP clients (403), and its robots.txt
disallows all generic agents. The owner asked for Jora (2026-10-06); like Seek, this is
personal low-volume use: one page per keyword, rotated, slow tier, with a browser TLS
fingerprint (curl_cffi, already installed with JobSpy). Set jora.enabled: false in
searches.yaml to stop it.
"""
from __future__ import annotations

from jobwatch.place import location_text

import hashlib
import html
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from ..models import Posting, salary_from_text, work_type_of
from .base import CollectorContext, rotate

NAME = "jora"
BASE = "https://au.jora.com"

_CARD = re.compile(r'data-job-card="true"')
_TITLE = re.compile(r'class="job-link[^"]*-desktop-only[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_COMPANY = re.compile(r'class="job-company">(.*?)<', re.S)
_LOCATION = re.compile(r'class="[^"]*job-location[^"]*"[^>]*>(.*?)</', re.S)
_DATE = re.compile(r'class="job-listed-date">(.*?)</div>', re.S)
_ABSTRACT = re.compile(r'class="job-abstract">(.*?)</div>', re.S)
_BADGE = re.compile(r'class="badge[^"]*"><div class="content">(.*?)<', re.S)
_JOBID = re.compile(r'/job/[^?"]*-([0-9a-f]{32})')
_AGO = re.compile(r'(\d+)\s*(m|h|d|mo|y)\b')


def _text(m) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).strip() if m else ""


def posted_from(label: str, now: datetime | None = None) -> str | None:
    """'Posted 4h ago' -> ISO timestamp (approximate)."""
    m = _AGO.search(label or "")
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    delta = {"m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n),
             "mo": timedelta(days=30 * n), "y": timedelta(days=365 * n)}[unit]
    return ((now or datetime.now(timezone.utc)) - delta).isoformat(timespec="seconds")


def parse(page: str, keyword: str = "") -> list[Posting]:
    out = []
    for card in _CARD.split(page)[1:]:
        t = _TITLE.search(card)
        if not t:
            continue
        href = html.unescape(t.group(1))
        jid = _JOBID.search(href)
        source_id = jid.group(1) if jid else hashlib.sha1(href.encode()).hexdigest()
        badges = [html.unescape(b).strip() for b in _BADGE.findall(card)]
        salary = next((b for b in badges if "$" in b), None)
        smin, smax, unit = salary_from_text(salary)
        out.append(Posting(
            source=NAME, source_id=source_id,
            url=f"{BASE}{href.split('?')[0]}" if href.startswith("/") else href.split("?")[0],
            title=html.unescape(re.sub(r"<[^>]+>", "", t.group(2))).strip(),
            company=_text(_COMPANY.search(card)),
            location=_text(_LOCATION.search(card)),
            work_type=work_type_of(*badges),
            salary_text=salary, salary_min=smin, salary_max=smax, salary_unit=unit,
            posted_at=posted_from(_text(_DATE.search(card))),
            posted_at_source="provider" if _DATE.search(card) else "observed",
            description=_text(_ABSTRACT.search(card)),
            raw={"badges": badges, "href": href}, origin=f"jora:{keyword}",
        ))
    return out


def collect(cfg: CollectorContext, since=None) -> list[Posting]:
    conf = cfg.config.searches.get("jora") or {}
    if conf.get("enabled") is False:
        return []
    from curl_cffi import requests as cffi    # browser TLS fingerprint (see module doc)
    items = conf['searches'] if 'searches' in conf else list(conf.get('keywords') or [''])
    keywords = rotate(cfg, "jora", items, conf.get("searches_per_run", 4))
    results: list[Posting] = []
    seen: set[str] = set()
    for i, keyword in enumerate(keywords):
        if cfg.full(results):
            break
        if i:
            time.sleep(float(conf.get("delay_s", 4)))
        where = conf.get('where') or location_text() or 'All Australia'
        if isinstance(keyword, dict):
            where = keyword.get('location') or 'All Australia'
            keyword = keyword['term']
        url = f"{BASE}/j?" + urlencode({"q": keyword, "l": where,
                                         "sp": "recent", "a": conf.get("age", "24h")})
        try:
            r = cffi.get(url, impersonate="chrome", timeout=30)
        except Exception as exc:                  # network error: back off for this run
            cfg.error(f"jora '{keyword}'", exc)
            break
        if r.status_code != 200:
            cfg.error(f"jora '{keyword}'", f"HTTP {r.status_code}")
            if r.status_code in (403, 429) or r.status_code >= 500:
                break
            continue
        rows = parse(r.text, keyword)
        cfg.count_raw(len(rows))
        for p in rows:
            if p.source_id not in seen:
                seen.add(p.source_id)
                results.append(p)
        cfg.origins.add(f"jora:{keyword}")
    return results[: cfg.limit] if cfg.limit else results
