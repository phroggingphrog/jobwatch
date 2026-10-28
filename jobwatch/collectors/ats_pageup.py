"""PageUp RSS: https://careers.pageuppeople.com/{client}/cw/en/rss (registry field feed_url).

Items carry job:location, job:workType, job:closingDate, job:refNo, job:description in the
http://pageuppeople.com/ namespace. Parsed with ElementTree (no feedparser quirks).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ..models import Posting, html_to_text, is_australian, iso, state_of, work_type_of
from .base import CollectorContext, run_per_employer

NAME = "ats_pageup"
NS = {"job": "http://pageuppeople.com/", "a10": "http://www.w3.org/2005/Atom"}


def parse_feed(xml_text: str, company: str, source: str = NAME, assume_au: bool = False,
               id_prefix: str = "") -> list[Posting]:
    root = ET.fromstring(xml_text.encode() if isinstance(xml_text, str) else xml_text)
    out = []
    for item in root.iter("item"):
        def t(tag: str) -> str:
            el = item.find(tag, NS)
            return (el.text or "").strip() if el is not None and el.text else ""
        link = t("link") or t("guid")
        location = t("job:location")
        if not (assume_au or is_australian(None, location) or state_of(location)):
            continue
        posted = t("pubDate") or t("a10:updated")
        ref = t("job:refNo") or link
        out.append(Posting(
            source=source, source_id=f"{id_prefix}{ref}", url=link, title=t("title"),
            company=company, location=location, remote="remote" in location.lower(),
            work_type=work_type_of(t("job:workType")),
            posted_at=iso(posted), posted_at_source="provider" if posted else "observed",
            description=html_to_text(t("job:description") or t("description")),
            raw={"title": t("title"), "link": link, "location": location,
                 "workType": t("job:workType"), "category": t("job:category"),
                 "closingDate": t("job:closingDate"), "refNo": t("job:refNo"),
                 "summary": t("description")},
        ))
    return out


def fetch_one(cfg: CollectorContext, employer: dict):
    url = employer.get("feed_url") or f"https://careers.pageuppeople.com/{employer['tenant']}/cw/en/rss"
    text = cfg.http.get_text(url)
    cfg.count_raw(text.count("<item>"))
    # Employer registry entries are Australian employers; an empty location is still AU.
    return parse_feed(text, employer.get("name", ""), assume_au=bool(employer.get("au_only", True)),
                      id_prefix=f"{employer.get('tenant') or employer.get('name')}:")


def collect(cfg: CollectorContext, since=None) -> list[Posting]:
    return run_per_employer(cfg, "pageup", fetch_one)
