"""Scout Talent (applynow.net.au) tenant index page, robots.txt respected.

The tenant index renders one `div.jobblock` per job with data-* attributes (title, url,
location, address_state, country, published_at/created_at). Verified 2026-10-06. Some
tenant roots redirect to the network-wide listing (React props); only rows whose URL is on
the tenant's own host are kept, so other employers' jobs never leak in.
Some tenants (Baw Baw, `bbsc-external`) link their jobs on the shared host applynow.net.au/jobs/BAW634-...;
for those the registry sets `ref_prefix: BAW` and only rows whose reference starts with it are kept.
"""
from __future__ import annotations

import html as htmllib
import json
import re
from urllib.parse import urlsplit

from ..models import Posting, is_australian, iso
from .base import CollectorContext, run_per_employer

NAME = "ats_scouttalent"
_BLOCK = re.compile(r"<div\b([^>]*\bclass=\"[^\"]*\bjobblock\b[^\"]*\"[^>]*)>", re.I)
_ATTR = re.compile(r'data-([a-z_]+)="([^"]*)"', re.I)
_PROPS = re.compile(r'data-react-props="([^"]*)"')


def parse_index(page: str, employer: dict) -> list[Posting]:
    tenant = employer["tenant"]
    host = f"{tenant}.applynow.net.au".lower()
    prefix = str(employer.get("ref_prefix") or "")
    out, seen = [], set()

    def own(url: str, reference: str) -> bool:
        h = urlsplit(url).hostname
        return h == host or bool(prefix and h == "applynow.net.au" and str(reference or "").startswith(prefix))

    for m in _BLOCK.finditer(page):
        attrs = {k.lower(): htmllib.unescape(v) for k, v in _ATTR.findall(m.group(1))}
        url = attrs.get("url", "")
        if not url or not own(url, attrs.get("reference", "")) or url in seen:
            continue
        seen.add(url)
        location = ", ".join(x for x in (attrs.get("location"), attrs.get("address_state")) if x)
        if not is_australian(attrs.get("country") or None, location):
            continue
        posted = iso(attrs.get("created_at"))
        out.append(Posting(
            source=NAME, source_id=f"{tenant}:{attrs.get('reference') or attrs.get('id')}",
            url=url, title=attrs.get("title", ""), company=employer.get("name", ""),
            location=location, posted_at=posted,
            posted_at_source="provider" if posted else "observed",
            description=attrs.get("summary", ""), raw=attrs,
        ))
    if out:
        return out
    # Fallback: React listing props, tenant-host rows only.
    pm = _PROPS.search(page)
    if pm:
        try:
            props = json.loads(htmllib.unescape(pm.group(1)))
        except ValueError:
            props = {}
        for job in props.get("jobs") or []:
            url = job.get("url", "")
            if not own(url, job.get("reference", "")) or url in seen:
                continue
            seen.add(url)
            out.append(Posting(
                source=NAME, source_id=f"{tenant}:{job.get('reference') or job.get('id')}", url=url,
                title=job.get("title", ""), company=employer.get("name", ""),
                location=job.get("location", ""), raw=job,
            ))
    return out


def fetch_one(cfg: CollectorContext, employer: dict):
    page = cfg.http.get_text(f"https://{employer['tenant']}.applynow.net.au/", robots=True)
    cfg.count_raw(len(_BLOCK.findall(page)))
    return parse_index(page, employer)


def collect(cfg: CollectorContext, since=None) -> list[Posting]:
    return run_per_employer(cfg, "scouttalent", fetch_one)
