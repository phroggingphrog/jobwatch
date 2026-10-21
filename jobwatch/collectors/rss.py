"""Generic RSS/Atom job feeds from feeds.yaml (feeds: [...]).

Entry fields: name, url, enabled, company, au (feed is Australia-only), default_location,
format (rss | pageup | successfactors). PageUp-format feeds reuse the PageUp parser.
SuccessFactors Career Site Builder feeds (`googlefeed.xml`) put the location at the end of
the title, "(City, STATE, AU, 3000)"; `parse_successfactors` splits it off. Registry entries
with provider: successfactors are read by the ats_successfactors collector (slow tier) with
the same parser.
"""
from __future__ import annotations

import re

import feedparser

from ..models import Posting, html_to_text, is_australian, iso
from . import ats_pageup
from .base import SOURCE_ERRORS, CollectorContext

NAME = "rss"


def parse_generic(text: str, feed: dict) -> list[Posting]:
    parsed = feedparser.parse(text)
    out = []
    for e in parsed.entries:
        location = e.get("location") or e.get("job_location") or feed.get("default_location") or ""
        summary = html_to_text(e.get("summary") or (e.get("content") or [{}])[0].get("value"))
        if not (feed.get("au") or is_australian(None, location, e.get("title"), summary[:300])):
            continue
        posted = e.get("published") or e.get("updated")
        out.append(Posting(
            source=NAME, source_id=f"{feed['name']}:{e.get('id') or e.get('link')}",
            url=e.get("link") or "", title=e.get("title") or "",
            company=feed.get("company") or e.get("author") or "", location=location,
            remote="remote" in f"{location} {e.get('title', '')}".lower(),
            posted_at=iso(posted), posted_at_source="provider" if posted else "observed",
            description=summary, raw={k: str(v)[:2000] for k, v in e.items() if k in
                                      ("id", "title", "link", "published", "updated", "tags", "author")},
            origin=feed["name"],
        ))
    return out


_SUFFIX = re.compile(r"\s*\(([^()]*)\)\s*$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")


def split_title_location(title: str) -> tuple[str, str, str | None]:
    """'Store Manager (Chadstone, VIC, AU, 3148)' -> ('Store Manager', 'Chadstone, VIC, 3148', 'AU').
    Returns (title, location, country code or None). Titles without a location suffix pass through."""
    title = (title or "").strip()
    m = _SUFFIX.search(title)
    if not m:
        return title, "", None
    parts = [p.strip() for p in m.group(1).split(",") if p.strip()]
    countries = [p for p in parts if _COUNTRY.match(p) and p in ("AU", "NZ", "SG", "US", "GB", "UK", "IN",
                                                                  "PH", "HK", "CN", "JP", "MY", "FJ", "PG")]
    if not countries:
        return title, "", None                       # a bracket that is not a location, e.g. "(Casual)"
    country = countries[-1]
    location = ", ".join(p for p in parts if p != country)
    return title[: m.start()].strip(), location, country


def parse_successfactors(text: str, employer: dict, source: str = NAME) -> list[Posting]:
    """SuccessFactors googlefeed.xml / RSS: title suffix (or g:location) gives the location."""
    parsed = feedparser.parse(text)
    name = employer.get("name") or employer.get("host") or "?"
    out = []
    for e in parsed.entries:
        title, location, country = split_title_location(e.get("title") or "")
        g_loc = e.get("g_location") or ""
        if not location and g_loc:
            parts = [p.strip() for p in g_loc.split(",") if p.strip()]
            if parts and _COUNTRY.match(parts[-1]):
                country = parts[-1]
                parts = parts[:-1]
            location = ", ".join(parts)
        if country and country != "AU":
            continue
        if not country and location and not is_australian(None, location):
            continue
        if country == "AU" and location and "australia" not in location.lower() and \
                not is_australian(None, location):
            location = f"{location}, Australia"
        ident = e.get("g_id") or e.get("id") or e.get("link")
        posted = e.get("published") or e.get("updated")
        out.append(Posting(
            source=source, source_id=f"{employer.get('tenant') or employer.get('host') or name}:{ident}",
            url=e.get("link") or "", title=title,
            company=employer.get("company") or name, location=location,
            remote="remote" in f"{location} {title}".lower(),
            posted_at=iso(posted), posted_at_source="provider" if posted else "observed",
            description=html_to_text(e.get("summary")),
            raw={"title": e.get("title"), "link": e.get("link"), "id": ident, "g_location": g_loc,
                 "expires": e.get("g_expiration_date"), "employer": e.get("g_employer")},
            origin=name,
        ))
    return out


def fetch_conditional(cfg: CollectorContext, url: str, **kw) -> str | None:
    """GET with If-None-Match / If-Modified-Since when the server gave validators last time.
    Returns None on 304 Not Modified. (SuccessFactors sent none on 2026-10-06; harmless.)"""
    key = f"http_cache:{url}"
    cached = cfg.state_get(key, None) or {}
    headers = {}
    if cached.get("etag"):
        headers["If-None-Match"] = cached["etag"]
    if cached.get("last_modified"):
        headers["If-Modified-Since"] = cached["last_modified"]
    response = cfg.http.request("GET", url, headers=headers or None, **kw)
    if response.status_code == 304:
        return None
    validators = {"etag": response.headers.get("ETag"), "last_modified": response.headers.get("Last-Modified")}
    if any(validators.values()) or cached:
        cfg.state_set(key, {k: v for k, v in validators.items() if v})
    return response.text


def collect(cfg: CollectorContext, since=None) -> list[Posting]:
    results: list[Posting] = []
    for feed in cfg.config.feeds.get("feeds") or []:
        if not isinstance(feed, dict) or feed.get("enabled") is False or not feed.get("url"):
            continue
        if cfg.full(results):
            break
        try:
            text = cfg.http.get_text(feed["url"])
            cfg.count_raw(text.count("<item>") + text.count("<item ") + text.count("<entry>") + text.count("<entry "))
            if feed.get("format") == "successfactors":
                items = parse_successfactors(text, {"name": feed["name"], "company": feed.get("company")})
            elif feed.get("format") == "pageup":
                items = ats_pageup.parse_feed(text, feed.get("company", ""), source=NAME,
                                              assume_au=bool(feed.get("au", True)),
                                              id_prefix=f"{feed['name']}:")
                for p in items:
                    p.origin = feed["name"]
            else:
                items = parse_generic(text, feed)
            results += items
            cfg.origins.add(f"rss:{feed['name']}")
        except SOURCE_ERRORS as exc:
            cfg.error(feed.get("name", feed["url"]), exc)
    return results[: cfg.limit] if cfg.limit else results
