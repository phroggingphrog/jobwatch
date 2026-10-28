"""Employer career pages: schema.org JobPosting JSON-LD, robots.txt respected.

Registry entries with provider: jsonld and careers_url (string or list). The collector reads
JSON-LD on the careers page itself, then follows same-site job-detail links (anchor text
that looks like a target role first) up to `detail_cap` (default and max 30) per employer
per run, skipping postings already in the DB. `follow_links: false` reads the listing only.

Quirks handled: a capitalised `Title` key (Jobs at TAFE portal), and listing pages whose
JobPosting objects have no `url`: set `url_pattern` (a regex run over the URL-decoded page) and
each posting is paired with the matching job link whose last path segment is the title slug.
"""
from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit

from ..http import HttpError
from ..models import (Posting, html_to_text, is_australian, iso, salary_from_text, work_type_of)
from .base import CollectorContext, run_per_employer

NAME = "jsonld_pages"
MAX_DETAILS = 30
DEFAULT_LINK = re.compile(r"/(jobs?|careers?|positions?|vacanc|opportunit|opening|requisition|"
                          r"listing|apply|role)s?[/\-_=?]", re.I)


class _Page(HTMLParser):
    def __init__(self, text: str):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.blocks: list[str] = []
        self._ld = False
        self._buf: list[str] = []
        self._href: str | None = None
        self._anchor: list[str] = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and (a.get("type") or "").lower().strip() == "application/ld+json":
            self._ld, self._buf = True, []
        if tag == "a" and a.get("href"):
            self._href, self._anchor = a["href"], []

    def handle_data(self, data):
        if self._ld:
            self._buf.append(data)
        if self._href is not None:
            self._anchor.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._ld:
            self.blocks.append("".join(self._buf))
            self._ld = False
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._anchor).split())))
            self._href = None


def job_postings(page: str) -> list[dict]:
    """Every JobPosting object in the page's JSON-LD blocks (incl. @graph / lists)."""
    out: list[dict] = []

    def walk(node):
        if isinstance(node, list):
            for x in node:
                walk(x)
        elif isinstance(node, dict):
            t = node.get("@type")
            if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                out.append(node)
            else:
                for v in node.values():
                    if isinstance(v, (dict, list)):
                        walk(v)

    for block in _Page(page).blocks:
        try:
            walk(json.loads(block.strip()))
        except ValueError:
            continue
    return out


def _addresses(job: dict) -> list[dict]:
    locs = job.get("jobLocation") or []
    locs = locs if isinstance(locs, list) else [locs]
    out = []
    for loc in locs:
        if isinstance(loc, dict):
            addr = loc.get("address", loc)
            if isinstance(addr, str):
                addr = {"addressLocality": addr}
            if isinstance(addr, dict):
                out.append(addr)
    return out


def _title(job: dict) -> str:
    return job.get("title") or job.get("Title") or job.get("name") or job.get("Name") or ""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def page_job_urls(page: str, base: str, pattern: str) -> dict[str, list[str]]:
    """{title-slug: [job URLs in page order]} for links matching `pattern` in the decoded page."""
    out: dict[str, list[str]] = {}
    for url in dict.fromkeys(re.findall(pattern, unquote(page))):
        try:
            url = urljoin(base, url)
            slug = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1].lower()
        except ValueError:                      # a hostile link ('https://x[::1]') loses itself, not the employer
            continue
        out.setdefault(slug, []).append(url)
    return out


_BAD_CHARS = re.compile(r"[\\\x00-\x1f\x7f-\x9f]")      # backslash and control characters, anywhere in a URL


def _plain_host(url: str) -> str | None:
    """The lower-case host of a URL that every parser reads the same way, else None. A backslash, a control character
    or whitespace in the host part is refused: urllib3 and urlsplit disagree on such a URL, so a check on one would
    pass a link the other connects to elsewhere."""
    if not url or _BAD_CHARS.search(url):
        return None
    try:
        parts = urlsplit(url)
        host = parts.hostname
        parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or "@" in parts.netloc or re.search(r"\s", parts.netloc) or not host:
        return None
    return host.lower()


def same_site(host: str | None) -> str | None:
    """A host as compared between a careers page and its job links: `www.example.com` and `example.com` are one site."""
    return host[4:] if host and host.startswith("www.") else host


def site_hosts(employer: dict, page_url: str = "") -> set[str]:
    """Hosts of this employer's own site (no leading www.): its careers_url(s), `allowed_hosts` and the page being read."""
    urls = employer.get("careers_url") or []
    urls = urls if isinstance(urls, list) else [urls]
    hosts = {same_site(_plain_host(str(u))) for u in [*urls, page_url]} | {same_site(str(h).lower())
                                                                         for h in employer.get("allowed_hosts") or []}
    return {h for h in hosts if h}


def to_posting(job: dict, page_url: str, employer: dict, shared_page: bool = False) -> Posting | None:
    """shared_page: page_url is a listing holding several postings, so it is no per-job URL."""
    addrs = _addresses(job)
    def country(a):
        c = a.get("addressCountry")
        return (c.get("name") or c.get("identifier")) if isinstance(c, dict) else c
    remote = str(job.get("jobLocationType", "")).upper() == "TELECOMMUTE"
    req = job.get("applicantLocationRequirements") or {}
    req_name = req.get("name") if isinstance(req, dict) else str(req)
    au = any(is_australian(country(a)) if country(a) else
             is_australian(None, a.get("addressLocality"), a.get("addressRegion")) for a in addrs)
    if not au and not (remote and is_australian(None, req_name)):
        if addrs or not employer.get("au_only", True):
            return None
    first = addrs[0] if addrs else {}
    location = ", ".join(str(x) for x in (first.get("addressLocality"), first.get("addressRegion"))
                         if x) or (req_name or "")
    org = job.get("hiringOrganization")
    company = org.get("name") if isinstance(org, dict) else (org or employer.get("name", ""))
    salary = job.get("baseSalary") or {}
    smin = smax = unit = None
    salary_text = None
    if isinstance(salary, dict):
        val = salary.get("value") or {}
        if isinstance(val, dict):
            smin = val.get("minValue") or val.get("value")
            smax = val.get("maxValue") or val.get("value")
            unit = str(val.get("unitText") or "").lower() or None
        elif isinstance(val, (int, float, str)):
            smin, smax, unit = salary_from_text(f"${val}")
        if smin:
            salary_text = f"{salary.get('currency', 'AUD')} {smin}-{smax} {unit or ''}".strip()
    ident = job.get("identifier")
    ident = ident.get("value") if isinstance(ident, dict) else ident
    hosts = site_hosts(employer, page_url)
    # a url the page names for itself is only kept on the employer's own site
    own = [u for u in (job.get("url"), job.get("_page_job_url")) if isinstance(u, str) and same_site(_plain_host(u)) in hosts]
    url = own[0] if own else ("" if shared_page else page_url)
    if not url:
        # No per-job URL on a listing page: a stable synthetic id and no URL (the shared page URL
        # would make every posting on the page one job to the URL-hash dedupe).
        key = "|".join(str(x) for x in (_title(job), company, location, job.get("datePosted")))
        ident = ident or hashlib.sha1(key.encode()).hexdigest()[:16]
    etype = job.get("employmentType")
    etype = " ".join(etype) if isinstance(etype, list) else etype
    return Posting(
        source=NAME, source_id=f"{employer.get('name')}:{ident or url}", url=url,
        title=_title(job), company=company or employer.get("name", ""),
        location=location, remote=remote, work_type=work_type_of(etype),
        salary_text=salary_text, salary_min=smin, salary_max=smax, salary_unit=unit,
        posted_at=iso(job.get("datePosted")),
        posted_at_source="provider" if job.get("datePosted") else "observed",
        description=html_to_text(job.get("description")),
        raw={**{k: v for k, v in job.items() if k not in ("description", "_page_job_url", "_site_hosts")},
             "_site_hosts": sorted(hosts)},       # adtext.fetch_jsonld requests the stored url only on these hosts
    )


def detail_links(page: str, base: str, employer: dict, relevant) -> list[str]:
    pattern = re.compile(employer["link_pattern"], re.I) if employer.get("link_pattern") else DEFAULT_LINK
    allowed = ({same_site(_plain_host(base))} | {same_site(str(h).lower()) for h in employer.get("allowed_hosts") or []}) - {None}
    base_parts = urlsplit(base)
    default_port = {"http": 80, "https": 443}
    scored = []
    for href, text in _Page(page).links:
        href = href.strip()
        if _BAD_CHARS.search(href):             # urljoin would silently drop a tab or newline: refuse the link
            continue
        try:
            url = urljoin(base, href).split("#")[0]
        except ValueError:                      # 'https://x[::1]': skip this link, keep the employer
            continue
        if same_site(_plain_host(url)) not in allowed:
            continue
        parts = urlsplit(url)
        if parts.scheme != base_parts.scheme or (parts.port or default_port.get(parts.scheme)) != (
                base_parts.port or default_port.get(base_parts.scheme)):
            continue                            # same scheme and port as the page the link was found on
        if url.rstrip("/") == base.rstrip("/") or not pattern.search(parts.path + "?" + parts.query):
            continue
        scored.append((0 if relevant(text) else 1, url))
    seen, out = set(), []
    for _, url in sorted(scored, key=lambda x: x[0]):
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def fetch_one(cfg: CollectorContext, employer: dict):
    urls = employer.get("careers_url") or []
    urls = urls if isinstance(urls, list) else [urls]
    cap = min(int(employer.get("detail_cap", MAX_DETAILS)), MAX_DETAILS)
    out: list[Posting] = []
    seen_urls: set[str] = set()
    for base in urls:
        page = cfg.http.get_text(base, robots=True)
        jobs = job_postings(page)
        cfg.count_raw(len(jobs))
        if employer.get("url_pattern"):
            by_slug = page_job_urls(page, base, employer["url_pattern"])
            for job in jobs:
                if not job.get("url"):
                    urls = by_slug.get(_slug(_title(job))) or []
                    if urls:
                        job["_page_job_url"] = urls.pop(0)
        for job in jobs:
            p = to_posting(job, base, employer, shared_page=len(jobs) > 1)
            if p:
                out.append(p)
                seen_urls.add(p.url)
        if employer.get("follow_links", True):
            for link in detail_links(page, base, employer, cfg.title_relevant):
                if cap <= 0 or cfg.full(out):
                    break
                if link in seen_urls or cfg.is_known(NAME, link):
                    continue
                cap -= 1
                try:
                    detail = cfg.http.get_text(link, robots=True)
                except HttpError as exc:
                    cfg.error(f"{employer.get('name')} {urlsplit(link).path}", exc)
                    if exc.status in (403, 429) or exc.status >= 500:
                        break
                    continue
                found = job_postings(detail)
                cfg.count_raw(len(found))
                for job in found:
                    p = to_posting(job, link, employer)
                    if p and p.url not in seen_urls:
                        seen_urls.add(p.url)
                        out.append(p)
    return out


def collect(cfg: CollectorContext, since=None) -> list[Posting]:
    return run_per_employer(cfg, "jsonld", fetch_one)
