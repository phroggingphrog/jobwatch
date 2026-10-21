"""Reddit subreddit RSS (no login, no API key, no .json path).

Two streams (PLAN D8):
  hiring  - hiring-post wording + the person's state/remote-AU -> returned as Postings (filters/alerts)
  chatter - job-search/callback/interview/rejection/graduate/salary talk -> reddit_posts table
Reddit throttles anonymous RSS hard (x-ratelimit-remaining often hits 0 after one call), so
each run fetches at most `requests_per_run` feeds (rotating), >= min_interval_seconds apart,
and stops early when the rate-limit headers say the window is spent.
"""
from __future__ import annotations

import re
import time
from urllib.parse import quote_plus

import feedparser

from jobwatch.place import area_pattern, location_text
from ..http import HttpError
from ..models import Posting, html_to_text, iso
from .base import CollectorContext, rotate

NAME = "reddit"
DEFAULT_UA = "linux:jobwatch:0.1 (personal job-alert reader; low-volume RSS polling)"
_TAG = re.compile(r"^\s*[\[(](hiring|job|jobs|vacancy|now hiring)[\])]\s*[-:|]?\s*", re.I)


def feed_url(entry: dict) -> str:
    sub = entry["sub"]
    if entry.get("q"):
        return (f"https://www.reddit.com/r/{sub}/search.rss?q={quote_plus(entry['q'])}"
                f"&restrict_sr=1&sort=new")
    return f"https://www.reddit.com/r/{sub}/new/.rss"


def _compile(values) -> list[re.Pattern]:
    return [re.compile(v, re.I) for v in values or []]


def classify(title: str, text: str, conf: dict, local: bool = False) -> tuple[str | None, list[str]]:
    blob = f"{title}\n{text}"
    hiring = _compile(conf.get("hiring_keywords"))
    where = _compile(conf.get("hiring_location"))
    not_hiring = _compile(conf.get("not_hiring"))
    if any(p.search(title) or p.search(text[:400]) for p in hiring) and (local or any(p.search(blob) for p in where)) \
            and not any(p.search(title) for p in not_hiring):
        return "hiring", []
    themes = [name for name, words in (conf.get("chatter_themes") or {}).items()
              if any(p.search(blob) for p in _compile(words))]
    return ("chatter", themes) if themes else (None, [])


def parse(text: str, entry: dict, conf: dict) -> tuple[list[Posting], list[dict]]:
    parsed = feedparser.parse(text)
    postings, rows = [], []
    for e in parsed.entries:
        title = e.get("title") or ""
        body = html_to_text((e.get("content") or [{}])[0].get("value") or e.get("summary"))
        body = re.sub(r"submitted by\s+/u/\S+.*$", "", body, flags=re.S).strip()   # drop usernames
        kind, themes = classify(title, body, conf, local=bool(entry.get("location")))
        if kind is None:
            continue
        sub = (e.get("tags") or [{}])[0].get("term") or entry["sub"]
        rid = (e.get("id") or e.get("link") or "").split("/")[-1] or e.get("link")
        published = iso(e.get("published") or e.get("updated"))
        rows.append({"id": rid, "subreddit": sub, "stream": kind, "title": title[:300],
                     "url": e.get("link"), "summary": body[:1000], "themes": themes,
                     "score": None, "comments": None, "published_at": published})
        if kind == "hiring":
            low = f"{title} {body}".lower()
            area = area_pattern()
            if area and area.search(low):
                location = location_text()
            else:
                location = entry.get("location") or "Remote, Australia"
            postings.append(Posting(
                source=NAME, source_id=rid, url=e.get("link") or "", title=_TAG.sub("", title),
                company=f"r/{sub}", location=location,
                remote=location.startswith("Remote") or "remote" in low,
                posted_at=published, posted_at_source="provider" if published else "observed",
                description=body, raw={"subreddit": sub, "id": rid, "title": title},
                flags=["reddit"], origin=f"reddit:{sub}",
            ))
    return postings, rows


def collect(cfg: CollectorContext, since=None, sleep=time.sleep) -> list[Posting]:
    conf = cfg.config.feeds.get("reddit") or {}
    if conf.get("enabled") is False:
        return []
    feeds = [f for f in conf.get("feeds") or [] if isinstance(f, dict) and f.get("enabled", True)]
    feeds = rotate(cfg, "reddit", feeds, int(conf.get("requests_per_run", 4)))
    ua = conf.get("user_agent") or DEFAULT_UA
    interval = max(2.0, float(conf.get("min_interval_seconds", 3)))
    results: list[Posting] = []
    for entry in feeds:
        if cfg.full(results):
            break
        url = feed_url(entry)
        try:
            resp = cfg.http.request("GET", url, delay=interval, headers={"User-Agent": ua})
        except HttpError as exc:
            cfg.error(f"r/{entry['sub']}", exc)
            break                           # 429/403: stop this run, try again next run
        cfg.count_raw(resp.text.count("<entry>"))
        postings, rows = parse(resp.text, entry, conf)
        results += postings
        cfg.reddit_posts.extend(rows)
        cfg.origins.add(f"reddit:{entry['sub']}")
        try:
            remaining = float(resp.headers.get("x-ratelimit-remaining", "1"))
            reset = float(resp.headers.get("x-ratelimit-reset", "0"))
        except ValueError:
            remaining, reset = 1.0, 0.0
        if remaining < 1:
            if reset > float(conf.get("max_wait_seconds", 65)):
                break                       # window spent: leave the rest for the next run
            sleep(reset + 1)
    return results
