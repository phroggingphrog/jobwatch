"""Hosted careers sites with a /jobs/search card list (registry provider: jobs-search).

Used by Kingston (careers.kingston.vic.gov.au), Mitchell (careers.mitchellshire.vic.gov.au) and Glen Eira
(careers.gleneira.vic.gov.au). Server-rendered HTML, robots.txt respected (Fetcher checks it). Each job is an
`article.job-search-results-card-col` with: the job link (h3 a, /jobs/{slug}), `li.job-component-location`
(one or more), category, employment type and a one-line summary. No posted date in the list, so postings are
observed-dated and the first read seeds. The footer says "Displaying all N entries"; if N is larger than the
cards parsed (a paged list, not seen yet at 8-13 jobs) an error is recorded rather than silently dropping jobs.
Registry fields: careers_url (https://{host}/jobs/search), state.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from ..models import Posting, clean_text, html_to_text, work_type_of
from .base import CollectorContext, run_per_employer
from .jsonld_pages import _plain_host, same_site

NAME = "ats_jobs_search"
_CARD = re.compile(r'<article class="[^"]*job-search-results-card-col[^"]*"[^>]*>(.*?)</article>', re.S)
_LINK = re.compile(r'<h3[^>]*>\s*<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_COMPONENT = r'<li class="[^"]*\bjob-component-{kind}(?=[\s"])[^"]*">.*?<span[^>]*>(.*?)</span>'
_SUMMARY = re.compile(r'<p class="[^"]*job-search-results-summary[^"]*"[^>]*>(.*?)</p>', re.S)
_TOTAL = re.compile(r"Displaying\s*(?:<b>)?\s*(?:all)?(?:&nbsp;|\s)*(\d+)\s*(?:</b>)?\s*entries", re.I)


def _all(kind: str, block: str) -> list[str]:
    return [clean_text(html_to_text(v)) for v in re.findall(_COMPONENT.format(kind=kind), block, re.S)]


def parse_list(page: str, employer: dict) -> tuple[list[Posting], int | None]:
    base = employer["careers_url"]
    host = urlsplit(base).hostname
    out, seen = [], set()
    for block in _CARD.findall(page):
        m = _LINK.search(block)
        if not m:
            continue
        try:
            url = urljoin(base, m.group(1).strip())
        except ValueError:                      # a hostile link ('https://x[::1]') loses itself, not the employer
            continue
        link_host = same_site(_plain_host(url))                                 # backslash-safe; www. is the same site
        if not link_host or link_host != same_site(host) or url in seen:
            continue
        seen.add(url)
        slug = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
        locations = [x for x in _all("location", block) if x]
        etype = " ".join(_all("employment-type", block))
        summary = _SUMMARY.search(block)
        out.append(Posting(
            source=NAME, source_id=f"{host}:{slug}", url=url, title=clean_text(re.sub(r"<[^>]+>", " ", m.group(2))),
            company=employer.get("name", ""), location=", ".join(dict.fromkeys(locations)),
            state=employer.get("state") or None, work_type=work_type_of(etype),
            description=clean_text(html_to_text(summary.group(1))) if summary else "",
            raw={"slug": slug, "locations": locations, "category": _all("category", block),
                 "employment_type": etype},
        ))
    total = _TOTAL.search(page)
    return out, int(total.group(1)) if total else None


def fetch_one(cfg: CollectorContext, employer: dict):
    page = cfg.http.get_text(employer["careers_url"], robots=True)
    jobs, total = parse_list(page, employer)
    cfg.count_raw(len(jobs))
    if total is not None and total > len(jobs):
        cfg.error(employer.get("name", "?"), f"list shows {total} entries but {len(jobs)} parsed (paged list?)")
    return jobs


def collect(cfg: CollectorContext, since=None) -> list[Posting]:
    return run_per_employer(cfg, "jobs-search", fetch_one)
