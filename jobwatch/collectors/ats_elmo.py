"""ELMO Talent career sites (https://{tenant}.elmotalent.com.au/careers/{slug}/jobs), used by Stonnington (cos / cosjobs)
and Surf Coast (surfcoast / surfcoast).

Server-rendered `li.list-group-item` rows: job link (/careers/{slug}/job/view/{id}), a one-line summary, the
location, the employment type and the closing date (dd/mm/yyyy; this is NOT a posted date, so postings are
observed-dated and the first read seeds). Only the list page is fetched, never the job detail pages.

robots.txt on these hosts is "Allow: /careers/*/jobs ... Disallow: /careers/* ... Disallow: /". The Fetcher's
stdlib parser has no wildcard support and would block the allowed list page, so this collector reads robots.txt
itself and applies the standard longest-match rule with `*` wildcards (Allow wins a tie).
Registry fields: careers_url (the /jobs list page), state.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from ..http import HttpError
from ..models import Posting, clean_text, html_to_text, iso, work_type_of
from .base import CollectorContext, run_per_employer

NAME = "ats_elmo"
_ROW = re.compile(r'<li class="list-group-item">(.*?)</li>', re.S)
_LINK = re.compile(r'<a [^>]*href="(/careers/([^/"]+)/job/view/(\d+))"[^>]*>(.*?)</a>', re.S)
_SUMMARY = re.compile(r"</p>\s*<p>(.*?)</div>", re.S)
_ICON = r'glyphicon-{icon}"></div></strong></div>\s*<div[^>]*>(.*?)</div>'
_AGENTS = ("jobwatch", "*")


def robots_allows(robots_text: str, path: str) -> bool:
    """Longest-match robots rule with `*` / `$` wildcards for the first matching user-agent group."""
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []
    last_was_agent = False
    for line in robots_text.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (x.strip() for x in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if not last_was_agent and (agents or rules):
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
            last_was_agent = True
        elif key in ("allow", "disallow"):
            rules.append((key, value))
            last_was_agent = False
    if agents or rules:
        groups.append((agents, rules))
    chosen = None
    for wanted in _AGENTS:
        chosen = next((r for a, r in groups if wanted in a), None)
        if chosen is not None:
            break
    best_len, allowed = -1, True
    for kind, pattern in chosen or []:
        if not pattern:
            continue
        regex = re.escape(pattern).replace(r"\*", ".*")
        if regex.endswith(r"\$"):
            regex = regex[:-2] + "$"
        if re.match(regex, path):
            length = len(pattern.replace("*", ""))
            if length > best_len or (length == best_len and kind == "allow"):
                best_len, allowed = length, kind == "allow"
    return allowed


def check_robots(cfg: CollectorContext, url: str) -> None:
    parts = urlsplit(url)
    try:
        text = cfg.http.get_text(f"{parts.scheme}://{parts.netloc}/robots.txt")
    except HttpError as exc:
        if exc.status in (404, 410):
            return                                           # no robots.txt = allowed
        raise
    if not robots_allows(text, parts.path or "/"):
        raise HttpError(url, 0, f"robots.txt disallows {parts.path}")


def parse_list(page: str, employer: dict) -> list[Posting]:
    base = employer["careers_url"]
    out, seen = [], set()
    for row in _ROW.findall(page):
        m = _LINK.search(row)
        if not m or m.group(3) in seen:
            continue
        path, slug, job_id = m.group(1), m.group(2), m.group(3)
        seen.add(job_id)

        def icon(name: str) -> str:
            hit = re.search(_ICON.format(icon=name), row, re.S)
            return clean_text(html_to_text(hit.group(1))) if hit else ""
        summary = _SUMMARY.search(row)
        closing = icon("calendar")
        d = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", closing)
        out.append(Posting(
            source=NAME, source_id=f"{slug}:{job_id}", url=urljoin(base, path),
            title=clean_text(re.sub(r"<[^>]+>", " ", m.group(4))), company=employer.get("name", ""),
            location=icon("map-marker"), state=employer.get("state") or None,
            work_type=work_type_of(icon("pencil")),
            description=clean_text(html_to_text(summary.group(1))) if summary else "",
            raw={"id": job_id, "employment_type": icon("pencil"),
                 "closing": iso(f"{d.group(3)}-{int(d.group(2)):02d}-{int(d.group(1)):02d}") if d else closing},
        ))
    return out


def fetch_one(cfg: CollectorContext, employer: dict):
    check_robots(cfg, employer["careers_url"])
    jobs = parse_list(cfg.http.get_text(employer["careers_url"]), employer)
    cfg.count_raw(len(jobs))
    return jobs


def collect(cfg: CollectorContext, since=None) -> list[Posting]:
    return run_per_employer(cfg, "elmo", fetch_one)
