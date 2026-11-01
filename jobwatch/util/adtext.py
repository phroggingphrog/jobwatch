"""The full text of a job ad, so the AI reader reads the whole ad and not a 200-character teaser.

Order of preference for one posting:
  1. a row already in `ad_text` (fetched earlier);
  2. the stored `postings.description` when it is long enough to be the real ad body (ATS feeds);
  3. one request to the posting's own public page or API (table `_FETCHERS` below, one entry per posting source):
       seek               job page, ad body in SEEK_REDUX_DATA (`jobdetails.result.job.content`)
       ats_smartrecruiters  public API  api.smartrecruiters.com/v1/companies/{co}/postings/{id}  (jobAd.sections)
       jobspy_src         LinkedIn guest page (div.show-more-less-html__markup); Indeed rows are bot-walled: no fetch
       jora               job page, div#job-description-container
       careers_vic        job page, div.field--name-description
       ats_oracle         Oracle HCM public REST  recruitingCEJobRequisitionDetails (ExternalDescriptionStr ...)
       ats_phenom, ats_workday, ats_jobs_search, jsonld_pages
                          the page's JSON-LD `JobPosting.description`, from the host already stored in the posting url
  4. nothing: the reader works from the title and teaser and marks the review `teaser`.

A stored description of COLLECTOR_CAP characters or more is the collector's cut (html_to_text limit 2000), not the
ad: it is replaced from raw_json (greenhouse, ashby, workable, workday keep the whole ad there), then from the
source's page or API (successfactors, pageup, pulse, smartrecruiters, ...); with neither the kind is `partial`
and the reader holds it like a teaser. Every failed page fetch is logged in `ad_fetch` (at most FETCH_MAX_TRIES
tries, one per FETCH_RETRY_HOURS), so a dead or walled ad is never requested again on every run.

A posting its fetcher would refuse (an Indeed row, a url off the employer's site) is known before anything is spent:
`wants_fetch` is False, so no budget slot, no pause and no ad_fetch try; it stays `partial` or `teaser`. The owner's
`review --posting ID` and `review --refetch` skip the log's wait and try cap (`force`); pipeline runs keep it.

Low volume on purpose: one request per posting (the reader sleeps between calls and keeps a cap per run), and a stop
on 403/429/5xx (PLAN D3: personal use, no login, no cookies, no proxy). The fetch only ever happens for postings that
already passed the cheap rules.

Safety of a fetch: https only, and the host must belong to the expected site for that source (redirects are followed by
hand, at most 3, and every hop is checked before it is requested); a URL found inside page content is never fetched.
A body is accepted only when it is a real ad for THIS posting (>= MIN_BODY characters and the posting id is in the
final URL, or the ad/page shares a significant word with the posting title). Challenge, cookie, login and
"not found" pages give '' and are not saved. The ad text is untrusted data: it is reduced to plain text by
`models.html_to_text` (scripts/styles dropped, paragraphs and bullets kept as line breaks) and capped at MAX_TEXT.
"""
from __future__ import annotations

import os

import contextlib
import contextvars
import ipaddress
import json
import urllib.request
import logging
import re
import sqlite3
import threading
import time
from .deadline import pause, timeout as budget_timeout
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, NamedTuple
from urllib.parse import quote, urljoin, urlsplit

from jobwatch import db as dbm
from jobwatch.models import fold, html_to_text, now_utc

log = logging.getLogger(__name__)
_FETCH_DEADLINE = contextvars.ContextVar('jobwatch_ad_fetch_deadline', default=None)

MIN_FULL = 700                 # a description at least this long is treated as the real ad body...
COLLECTOR_CAP = 1990           # ...unless it is this long: the collectors cut at 2000, so that is not the whole ad
FETCH_MAX_TRIES = 3            # failed page fetches per ad (ad_fetch), then it stays a teaser/partial
FETCH_RETRY_HOURS = 24         # and not before this long after the last try
HOST_FAIL_LIMIT = 3            # consecutive failed fetches on one host, then the reader skips that host for the run
MAX_BODY = 3 * 1024 * 1024     # bytes read from one response (after decompression)
TOTAL_DEADLINE = 30.0          # seconds for one response, headers and body together
MAX_TEXT = 20000               # chars kept per ad
MIN_BODY = 200                 # a fetched body shorter than this is not accepted as the ad
MAX_HOPS = 3                   # redirects followed by hand, each hop host-checked
SEEK_JOB = "https://www.seek.com.au/job/{id}"
_REDUX = re.compile(r"window\.SEEK_REDUX_DATA\s*=\s*(\{.*?\});\s*\n", re.S)
_BODY = re.compile(r'data-automation="jobAdDetails"[^>]*>(.*?)</div>\s*</div>', re.S)


class Blocked(RuntimeError):
    """The site refused us (403/429/5xx): stop fetching for this run."""


class FetchError(RuntimeError):
    """A response that is too big, too slow or not text."""


_NOTE = threading.local()      # what the last fetch in this thread found out (see last_status)


def _note(status: str) -> None:
    _NOTE.status = status


def last_status() -> str | None:
    """How the most recent fetch attempt in this thread ended: ok, gone, wall, empty, refused, blocked: ..., error: ..."""
    return getattr(_NOTE, "status", None)


class _WouldRequest(Exception):
    """Raised in a dry run (would_request) at the point where a fetcher is about to send its request."""


def _skip(why: str = "refused") -> str:
    """A fetcher that will not ask the site (bad host or shape): nothing requested, '' returned."""
    _note(why)
    return ""


# a login/consent/challenge page answered with 200 instead of 403/429 (small pages only: real ads are long)
_WALL = re.compile(r"<title[^>]*>\s*(just a moment|attention required|sign up|sign in|log ?in|security check|"
                   r"access denied|are you a (human|robot)|verify you are human)|challenge-platform|cf-chl-|"
                   r"verify you are human|/uas/login|authwall|px-captcha|g-recaptcha|h-captcha", re.I)
_WALL_URL = re.compile(r"/(authwall|login|signin|uas/|checkpoint)\b", re.I)
_FILLED = re.compile(r"(position|job|vacancy|role) (has|is no longer|has been)[^.<]{0,30}(filled|available|closed)|"
                     r"no longer (available|accepting)|job (is )?(expired|closed)", re.I)


def looks_like_wall(url: str, body: str) -> bool:
    if _WALL_URL.search(urlsplit(url or "").path):
        return True
    return len(body or "") < 60000 and bool(_WALL.search(body or ""))


def get_text(conn, posting_id: int) -> tuple[str, str] | None:
    row = conn.execute("SELECT text, source FROM ad_text WHERE posting_id=?", (posting_id,)).fetchone()
    return (row["text"], row["source"]) if row else None


def write_retry(conn, fn, tries: int = 4, wait: float = 5.0):
    """Run a write and commit; if another process holds the lock, wait and try again (never loses the work)."""
    for attempt in range(tries):
        try:
            fn()
            conn.commit()
            return
        except sqlite3.OperationalError as exc:
            conn.rollback()
            if "locked" not in str(exc) and "busy" not in str(exc) or attempt == tries - 1:
                raise
            pause(wait)


def save_text(conn, posting_id: int, text: str, source: str) -> None:
    write_retry(conn, lambda: _save_text(conn, posting_id, text, source))


def _save_text(conn, posting_id: int, text: str, source: str) -> None:
    conn.execute(
        "INSERT INTO ad_text(posting_id, text, source, fetched_at) VALUES(?,?,?,?) "
        "ON CONFLICT(posting_id) DO UPDATE SET text=excluded.text, source=excluded.source, "
        "fetched_at=excluded.fetched_at",
        (posting_id, text[:MAX_TEXT], source, dbm.ts()))


def parse_seek_page(page: str) -> str:
    """The ad body of a Seek job page as plain text ('' when the page has none)."""
    m = _REDUX.search(page or "")
    if m:
        try:
            content = ((json.loads(m.group(1)).get("jobdetails") or {}).get("result") or {}).get("job", {}) \
                .get("content") or ""
            if content:
                return html_to_text(content, limit=MAX_TEXT)
        except (ValueError, AttributeError):
            pass
    b = _BODY.search(page or "")
    return html_to_text(b.group(1), limit=MAX_TEXT) if b else ""


def fetch_seek(source_id: str, session=None, timeout: float = 25.0) -> str:
    """One Seek job page, through the same capped, deadline-bound reader as every other fetcher (_http_get). Raises
    Blocked on 403/429/5xx so the caller stops for this run. `session` is unused (kept for old callers)."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", source_id or ""):
        return _skip()
    # Seek 308-redirects job pages to au.seek.com (2026-10-20).
    got = _http_get(SEEK_JOB.format(id=source_id), ("seek.com.au", "seek.com"), name="seek", timeout=timeout)
    if got is None:
        return ""                                   # gone (404/410) or refused
    final, page = got
    text = parse_seek_page(page)
    if not text:
        _note("wall" if looks_like_wall(final, page) else "empty")
    return text


# Safe fetching (shared by every source)
class Ref(NamedTuple):
    """What a per-source fetcher may use about one posting. All of it comes from our own database."""
    source: str
    source_id: str
    url: str
    title: str
    raw: dict


class _Resp(NamedTuple):
    status: int
    url: str
    text: str
    location: str


_GONE = {400, 404, 410}        # the ad is gone (or the id is unusable): '' and nothing saved
_REDIRECT = {301, 302, 303, 307, 308}


_BAD_TYPE = re.compile(r"^(image|video|audio|font)/|^application/(pdf|zip|gzip|octet-stream|x-)", re.I)


def _decode(body: bytes, content_type: str) -> str:
    m = re.search(r"charset=\s*[\"']?([\w.-]+)", content_type or "", re.I)
    enc = m.group(1) if m else None
    if not enc:
        meta = re.search(rb"<meta[^>]+charset=[\"']?([\w.-]+)", body[:4096], re.I)
        enc = meta.group(1).decode("ascii", "ignore") if meta else "utf-8"
    try:
        return body.decode(enc, "replace")
    except LookupError:
        return body.decode("utf-8", "replace")


def _read_capped(chunks, headers, deadline: float) -> str:
    """Read an iterator of (already decompressed) chunks up to MAX_BODY bytes and the deadline."""
    ctype = headers.get("content-type") or ""
    if ctype and _BAD_TYPE.search(ctype.strip()):
        raise FetchError(f"not a text page ({ctype[:40]})")
    try:
        if int(headers.get("content-length") or 0) > MAX_BODY:
            raise FetchError("response too large")
    except ValueError:
        pass
    out, size = [], 0
    for chunk in chunks:
        size += len(chunk)
        if size > MAX_BODY:
            raise FetchError("response too large")
        out.append(chunk)
        if time.monotonic() > deadline:
            raise FetchError("response too slow")
    return _decode(b"".join(out), ctype)


def _within(seconds: float, fn, cancel: threading.Event):
    """fn() with a hard wall-clock limit. requests' timeout applies to each socket read, so a server that answers the
    status line and then drips header bytes would never hit it; the worker is abandoned (it is a daemon thread and
    `cancel` stops its body loop) and FetchError raised at the limit."""
    box: dict = {}

    def work():
        try:
            box["value"] = fn()
        except BaseException as exc:                    # noqa: BLE001 - re-raised in the caller's thread
            box["error"] = exc
    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        cancel.set()
        raise FetchError("response too slow")
    if "error" in box:
        raise box["error"]
    return box["value"]


def _requests_get(url: str, timeout: float, deadline: float, cancel: threading.Event) -> _Resp:
    import requests
    with requests.Session() as session:
        session.trust_env = False                       # never pick up proxy env vars
        r = session.get(url, timeout=(min(5.0, timeout), min(10.0, timeout)), allow_redirects=False, stream=True,
                        headers={"Accept": "application/json", "User-Agent": "jobwatch/0.1"})
        try:
            def chunks():
                while not cancel.is_set():
                    c = r.raw.read1(65536, decode_content=True)
                    if not c:
                        return
                    yield c
                raise FetchError("response too slow")
            text = _read_capped(chunks(), r.headers, deadline) if r.status_code == 200 else ""
            return _Resp(r.status_code, url, text, r.headers.get("location") or "")
        finally:
            r.close()


def _do_get(url: str, browser: bool, timeout: float) -> _Resp:
    """One GET, redirects NOT followed. browser=True uses curl_cffi's browser TLS fingerprint (what already works for
    Seek and Jora; plain requests gets 403 on several career sites); False is plain requests for public JSON APIs.
    The body is streamed: at most MAX_BODY bytes after decompression and TOTAL_DEADLINE seconds in all, headers
    included (a gzip bomb or a slow drip raises FetchError); only a 200 body is read."""
    seconds = budget_timeout(TOTAL_DEADLINE)
    if _FETCH_DEADLINE.get() is not None:
        seconds = min(seconds, _FETCH_DEADLINE.get()-time.time())
    if seconds <= 0:
        raise FetchError('deadline_exceeded')
    deadline = time.monotonic() + seconds
    timeout = min(timeout, seconds)
    if browser:
        from curl_cffi import requests as cr
        r = cr.get(url, impersonate="chrome", timeout=timeout, allow_redirects=False, stream=True)
        try:
            text = _read_capped(r.iter_content(), r.headers, deadline) if r.status_code == 200 else ""
            return _Resp(r.status_code, url, text, r.headers.get("location") or "")
        finally:
            r.close()
    cancel = threading.Event()
    return _within(seconds, lambda: _requests_get(url, timeout, deadline, cancel), cancel)


# --- URL safety -----------------------------------------------------------------------------------------------
_BAD_URL = re.compile(r"[\\\x00-\x20\x7f-\x9f]|\s")       # backslash, control characters, whitespace
_HOSTNAME = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+")


def _public_name(host: str) -> bool:
    """A real DNS name: plain letters, digits and hyphens with a dot; not an IP address, not localhost."""
    if not host or host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return False
    if not _HOSTNAME.fullmatch(host):
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        return True


def _host_ok(url: str, allowed: tuple[str, ...]) -> bool:
    """https, no credentials, default port, no backslash/whitespace/control character anywhere (other parsers read such
    a URL as another host than urlsplit does), and the host is (a subdomain of) one of `allowed`."""
    if not url or _BAD_URL.search(url):
        return False
    try:
        parts = urlsplit(url)
        host, port = (parts.hostname or "").lower(), parts.port
    except ValueError:
        return False
    if parts.scheme != "https" or "@" in parts.netloc or parts.username or parts.password or port not in (None, 443):
        return False
    return _public_name(host) and any(host == a or host.endswith("." + a) for a in allowed)


def _http_get(url: str, allowed: tuple[str, ...], *, name: str, browser: bool = True,
              timeout: float = 25.0) -> tuple[str, str] | None:
    """(final_url, body) for a 200, None when the ad is gone or the destination is not allowed.

    Redirects are followed by hand and every hop is host-checked BEFORE it is requested, so a redirect to another
    site is never fetched. Raises Blocked on 403/429/5xx (and on any other unexpected status)."""
    _NOTE.page = None
    for _ in range(MAX_HOPS + 1):
        if not _host_ok(url, allowed):
            log.info("adtext: %s: refusing to fetch outside %s", name, ",".join(allowed))
            _note("refused")
            return None
        if getattr(_NOTE, "dry", False):
            raise _WouldRequest()
        resp = _do_get(url, browser, timeout)
        if resp.status in _REDIRECT and resp.location:
            url = urljoin(url, resp.location)
            continue
        if resp.status in _GONE:
            _note("gone")
            return None
        if resp.status != 200:
            raise Blocked(f"{name} HTTP {resp.status}")
        _NOTE.page = (url, resp.text or "")                 # _accept looks at it when no ad can be read from it
        return url, resp.text or ""
    _note("refused")
    return None                                             # redirect loop


_SCRIPT_BLOCK = re.compile(r"<(script|style)\b.*?</\1\s*>", re.I | re.S)


def _inner_html(page: str, open_tag: re.Pattern, tag: str = "div") -> str:
    """Inner HTML of the first element whose opening tag matches `open_tag` (balanced on `tag`).
    Scripts and styles are blanked first, so markup inside a JS string can never be taken for the ad."""
    page = _SCRIPT_BLOCK.sub(" ", page or "")
    m = open_tag.search(page)
    if not m:
        return ""
    depth = 1
    for t in re.finditer(rf"<(/?){tag}\b[^>]*>", page[m.end():], re.I):
        depth += -1 if t.group(1) else 1
        if depth == 0:
            return page[m.end(): m.end() + t.start()]
    return page[m.end():]                                   # unbalanced (cut-off page): the rest


_STOP = {"with", "from", "this", "that", "full", "time", "part", "term", "casual", "permanent", "contract",
         "temporary", "position", "role", "job", "vacancy", "urgent", "wanted", "and", "the", "for"}


def _title_words(title: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", fold(title)) if len(w) >= 4 and w not in _STOP]


def _is_this_ad(title: str, text: str, *, ref_id: str, id_in: str, page_title: str = "") -> bool:
    """The fetched body is a real ad for THIS posting: long enough, and either the posting id appears in `id_in`
    (the final URL, or the id the API answered with) or the ad/page shares a significant word with the title."""
    if len(text.strip()) < MIN_BODY:
        return False
    if ref_id and re.search(rf"(?<![0-9A-Za-z]){re.escape(ref_id)}(?![0-9A-Za-z])", id_in or "", re.I):
        return True
    hay = fold(f"{page_title}\n{text}")
    return any(re.search(rf"\b{re.escape(w)}\b", hay) for w in _title_words(title))


def _accept(ref: Ref, html_body: str, *, ref_id: str, id_in: str, page_title: str = "") -> str:
    """HTML ad body -> plain text, or '' when it is not a real ad for this posting (and why, see last_status)."""
    text = html_to_text(html_body, limit=MAX_TEXT)
    if _is_this_ad(ref.title, text, ref_id=ref_id, id_in=id_in, page_title=page_title):
        return text
    url, page = getattr(_NOTE, "page", None) or ("", "")
    if page and len(page) < 60000 and _FILLED.search(page):
        _note("gone")                                       # "this position has been filled"
    else:
        _note("wall" if page and looks_like_wall(url, page) else "empty")
    return ""


def _json(body: str):
    try:
        return json.loads(body)
    except ValueError:
        return None


def _page_title(page: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", page or "", re.I | re.S)
    return html_to_text(m.group(1), limit=300) if m else ""


# --- SmartRecruiters: public posting API -----------------------------------
SR_API = "https://api.smartrecruiters.com/v1/companies/{tenant}/postings/{id}"
_SR_SECTIONS = (("jobDescription", "Job description"), ("qualifications", "Qualifications"),
                ("additionalInformation", "Additional information"), ("companyDescription", "About the company"))


def parse_smartrecruiters(body: str) -> tuple[str, str, str]:
    """(html, api id, name) from a posting JSON: job description first, company blurb last (cut first at the cap)."""
    data = _json(body)
    if not isinstance(data, dict):
        return "", "", ""
    sections = ((data.get("jobAd") or {}).get("sections") or {})
    parts = []
    for key, label in _SR_SECTIONS:
        sec = sections.get(key) or {}
        if isinstance(sec, dict) and (sec.get("text") or "").strip():
            parts.append(f"<h3>{sec.get('title') or label}</h3>{sec['text']}")
    return "".join(parts), str(data.get("id") or ""), str(data.get("name") or "")


def fetch_smartrecruiters(ref: Ref) -> str:
    m = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*):([A-Za-z0-9-]+)", ref.source_id or "")
    if not m:
        return _skip()
    tenant, pid = m.groups()
    got = _http_get(SR_API.format(tenant=quote(tenant, safe=""), id=quote(pid, safe="")),
                    ("smartrecruiters.com",), name="smartrecruiters", browser=False)
    if got is None:
        return ""
    html_body, api_id, name = parse_smartrecruiters(got[1])
    return _accept(ref, html_body, ref_id=pid, id_in=api_id, page_title=name)


# --- LinkedIn guest page (jobspy_src rows from site=linkedin) -------------
LINKEDIN_JOB = "https://www.linkedin.com/jobs/view/{id}"
_LI_BODY = re.compile(r'<div[^>]*class="[^"]*\bshow-more-less-html__markup\b[^"]*"[^>]*>', re.I)


def parse_linkedin_page(page: str) -> str:
    """The ad body of a LinkedIn guest job page as HTML ('' when the page has none: login wall, challenge)."""
    return _inner_html(page, _LI_BODY)


def linkedin_id(ref: Ref) -> str | None:
    """The LinkedIn job id of a jobspy row, or None when the row is from another site (Indeed is bot-walled).
    The row's own raw_json `site` decides; without raw_json, only a linkedin.com URL or `linkedin:` id counts."""
    site = str(ref.raw.get("site") or "").lower()
    if site and site != "linkedin":
        return None
    if not site and not (ref.source_id.startswith("linkedin:") or _host_ok(ref.url, ("linkedin.com",))):
        return None
    for cand in (str(ref.raw.get("id") or ""), ref.source_id, str(ref.raw.get("job_url") or ""), ref.url):
        m = re.search(r"(?:\bli-|/jobs/view/(?:[^/?#]*-)?)(\d{6,})", cand)
        if m:
            return m.group(1)
    return None


def fetch_linkedin(ref: Ref) -> str:
    jid = linkedin_id(ref)
    if not jid:
        return _skip()
    got = _http_get(LINKEDIN_JOB.format(id=jid), ("linkedin.com",), name="linkedin")
    if got is None:
        return ""
    final, page = got
    return _accept(ref, parse_linkedin_page(page), ref_id=jid, id_in=final, page_title=_page_title(page))


# --- Jora ------------------------------------------------------------------
_JORA_BODY = re.compile(r'<div[^>]*\bid="job-description-container"[^>]*>', re.I)
_JORA_PATH = re.compile(r"^/job/[^/?#]+$")


def parse_jora_page(page: str) -> str:
    return _inner_html(page, _JORA_BODY)


def fetch_jora(ref: Ref) -> str:
    if not _host_ok(ref.url, ("jora.com",)):
        return _skip()
    parts = urlsplit(ref.url)
    if not _JORA_PATH.match(parts.path):
        return _skip()
    url = f"https://{parts.hostname}{parts.path}"           # no search-result tracking query
    got = _http_get(url, ("jora.com",), name="jora")
    if got is None:
        return ""
    final, page = got
    return _accept(ref, parse_jora_page(page), ref_id=ref.source_id, id_in=final, page_title=_page_title(page))


# --- Careers.Vic -----------------------------------------------------------
_CV_BODY = re.compile(r'<div[^>]*class="[^"]*\bfield--name-description\b[^"]*"[^>]*>', re.I)
_CV_PATH = re.compile(r"^/job/[^/?#]+$")


def parse_careers_vic_page(page: str) -> str:
    return _inner_html(page, _CV_BODY)


def fetch_careers_vic(ref: Ref) -> str:
    if not _host_ok(ref.url, ("careers.vic.gov.au",)):
        return _skip()
    parts = urlsplit(ref.url)
    if not _CV_PATH.match(parts.path):
        return _skip()
    got = _http_get(f"https://{parts.hostname}{parts.path}", ("careers.vic.gov.au",), name="careers.vic")
    if got is None:
        return ""
    final, page = got
    return _accept(ref, parse_careers_vic_page(page), ref_id=ref.source_id, id_in=final,
                   page_title=_page_title(page))


# --- Oracle HCM candidate experience: public REST --------------------------
ORACLE_API = ("https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
              "?expand=all&onlyData=true&finder=ById%3BId%3D%22{id}%22%2CsiteNumber%3D{site}")
_ORACLE_FIELDS = (("ExternalDescriptionStr", None), ("ExternalResponsibilitiesStr", "Responsibilities"),
                  ("ExternalQualificationsStr", "Qualifications"), ("CorporateDescriptionStr", "About the company"),
                  ("OrganizationDescriptionStr", "About the organisation"))


def parse_oracle(body: str) -> tuple[str, str, str]:
    """(html, requisition Id, title) from a recruitingCEJobRequisitionDetails answer ('' when there is no item)."""
    data = _json(body)
    items = data.get("items") if isinstance(data, dict) else None
    if not items or not isinstance(items[0], dict):
        return "", "", ""
    it = items[0]
    parts = []
    for key, label in _ORACLE_FIELDS:
        val = (it.get(key) or "").strip() if isinstance(it.get(key), str) else ""
        if val:
            parts.append((f"<h3>{label}</h3>" if label else "") + val)
    if not parts and isinstance(it.get("ShortDescriptionStr"), str):
        parts.append(it["ShortDescriptionStr"])
    return "".join(parts), str(it.get("Id") or ""), str(it.get("Title") or "")


def fetch_oracle(ref: Ref) -> str:
    m = re.fullmatch(r"([a-z0-9.-]+\.oraclecloud\.com):([A-Za-z0-9_]+):(\d+)", ref.source_id or "")
    if not m:
        return _skip()
    host, site, rid = m.groups()
    got = _http_get(ORACLE_API.format(host=host, site=site, id=rid), ("oraclecloud.com",), name="oracle",
                    browser=False)
    if got is None:
        return ""
    html_body, api_id, title = parse_oracle(got[1])
    return _accept(ref, html_body, ref_id=rid, id_in=api_id, page_title=title)


# --- Any page with a JSON-LD JobPosting (Phenom, Workday, jobs.search ...) -
_LD = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)


def _ld_nodes(data):
    if isinstance(data, list):
        for x in data:
            yield from _ld_nodes(x)
    elif isinstance(data, dict):
        yield data
        yield from _ld_nodes(data.get("@graph"))


def parse_jsonld_job(page: str) -> tuple[str, str]:
    """(title, description) of the first JSON-LD JobPosting with a description ('' '' when there is none).
    The description may be HTML, escaped HTML (Phenom) or plain text; `html_to_text` copes with all three."""
    for block in _LD.findall(page or ""):
        try:
            data = json.loads(block, strict=False)
        except ValueError:
            continue
        for node in _ld_nodes(data):
            kind = node.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            desc = node.get("description")
            if "JobPosting" in kinds and isinstance(desc, str) and desc.strip():
                return str(node.get("title") or ""), desc
    return "", ""


_LEGACY_HOSTS: frozenset[str] | None = None       # careers hosts of the registry's jsonld employers (set_legacy_hosts)


def set_legacy_hosts(hosts) -> None:
    """The hosts a jsonld_pages row WITHOUT `_site_hosts` may be fetched from: the registry's own (the reader passes
    them in at the start of a run). Unset or empty, such a row is never fetched."""
    global _LEGACY_HOSTS
    _LEGACY_HOSTS = frozenset(h[4:] if h.startswith("www.") else h for h in (str(x).lower() for x in hosts or ()))


def fetch_jsonld(ref: Ref) -> str:
    """The posting's own page (the url stored when we collected it); the final host must stay on that site.
    Only the stored URL is ever requested, never a URL read out of a page. A jsonld_pages row carries the hosts of its
    employer (`_site_hosts`, written by the collector from the registry): its url must be on one of them; an older row
    without them is held to the registry hosts (set_legacy_hosts)."""
    try:
        host = (urlsplit(ref.url).hostname or "").lower()
    except ValueError:
        return _skip()
    host = host[4:] if host.startswith("www.") else host
    if not _public_name(host):
        return _skip()
    sites = ref.raw.get("_site_hosts")
    if isinstance(sites, list) and sites:
        ok = {str(h).lower()[4:] if str(h).lower().startswith("www.") else str(h).lower() for h in sites}
    elif ref.source == "jsonld_pages":                      # a row stored before _site_hosts existed
        ok = _LEGACY_HOSTS or set()
    else:
        ok = None
    if ok is not None and host not in ok:
        return _skip()
    got = _http_get(ref.url, (host,), name=host)
    if got is None:
        return ""
    final, page = got
    title, desc = parse_jsonld_job(page)
    ref_id = ref.source_id.rsplit(":", 1)[-1]
    return _accept(ref, desc, ref_id=ref_id, id_in=final, page_title=title)


# --- SAP SuccessFactors Career Site Builder job page (jobs.deloitte.com.au, careers.anz.com ...) -----------
# The collector's source_id is "<registry host>:<id>" and the url comes from the employer's own feed: the page is
# requested only when its host is that registry host. The ad body sits in <span class="jobdescription">.
_SF_BODY = re.compile(r'<span[^>]*class="[^"]*\bjobdescription\b[^"]*"[^>]*>', re.I)
_SF_PATH = re.compile(r"^(?:/[A-Za-z0-9_-]+)?/job/[^/]+/(\d+)/?$")        # an optional site code first (/PYMHWS/job/...)


def parse_successfactors_page(page: str) -> str:
    return _inner_html(page, _SF_BODY, tag="span")


def fetch_successfactors(ref: Ref) -> str:
    host = (ref.source_id or "").split(":", 1)[0].lower()
    if not _public_name(host) or not _host_ok(ref.url, (host,)):
        return _skip()
    parts = urlsplit(ref.url)
    m = _SF_PATH.match(parts.path)
    if not m:
        return _skip()
    got = _http_get(f"https://{parts.hostname}{parts.path}", (host,), name="successfactors")
    if got is None:
        return ""
    final, page = got
    return _accept(ref, parse_successfactors_page(page), ref_id=m.group(1), id_in=final, page_title=_page_title(page))


# --- PageUp job page (careers.pageuppeople.com/<client>/cw/en/job/<id>) ---------------------------------------
_PU_BODY = re.compile(r'<div[^>]*\bid="job-details"[^>]*>', re.I)
_PU_PATH = re.compile(r"^/\d+/[a-z]{2,4}/[a-z]{2}/job/(\d+)(/[^/?#]*)?$")


def parse_pageup_page(page: str) -> str:
    return _inner_html(page, _PU_BODY)


def fetch_pageup(ref: Ref) -> str:
    if not _host_ok(ref.url, ("careers.pageuppeople.com",)):
        return _skip()
    parts = urlsplit(ref.url)
    m = _PU_PATH.match(parts.path)
    if not m:
        return _skip()
    got = _http_get(f"https://{parts.hostname}{parts.path}", ("careers.pageuppeople.com",), name="pageup")
    if got is None:
        return ""
    final, page = got
    return _accept(ref, parse_pageup_page(page), ref_id=m.group(1), id_in=final, page_title=_page_title(page))


# --- Pulse Software (council portals): the public job list answers with every ad in full -----------------------
PULSE_API = ("https://{tenant}.pulsesoftware.com/WebServices/RCM/Jobs/Jobs"
             "?internalOnly=false&workArrangement=&employmentType=")


def parse_pulse(body: str, link: str) -> tuple[str, str]:
    """(html, title) of the job with this LinkId in a Pulse job list answer."""
    data = _json(body)
    for job in (data.get("Jobs") if isinstance(data, dict) else None) or []:
        if isinstance(job, dict) and str(job.get("LinkId") or "") == link:
            info = job.get("JobInfo") if isinstance(job.get("JobInfo"), dict) else {}
            return str(info.get("Description") or info.get("Summary") or ""), str(info.get("Title") or "")
    return "", ""


def fetch_pulse(ref: Ref) -> str:
    m = re.fullmatch(r"([a-z0-9][a-z0-9-]*):([A-Za-z0-9_-]+)", ref.source_id or "")
    if not m:
        return _skip()
    tenant, link = m.groups()
    got = _http_get(PULSE_API.format(tenant=tenant), ("pulsesoftware.com",), name="pulse", browser=False)
    if got is None:
        return ""
    html_body, title = parse_pulse(got[1], link)
    if not html_body:
        return _skip("gone")                                # no longer in the list: the ad is closed
    return _accept(ref, html_body, ref_id=link, id_in=link, page_title=title)


# Registry and the public contract used by reader.py
class _Fetcher(NamedTuple):
    host: str                       # the reader keeps a per-host "blocked this run" set
    label: str                      # ad_text.source of what this fetcher saves
    run: Callable[[Ref], str]
    real: Callable[[Ref], str] | None = None    # the real fetch function, run dry by would_request (None: assume yes)


_JSONLD = {"ats_phenom": "phenom", "ats_workday": "workday", "ats_jobs_search": "jobs_search",
           "jsonld_pages": "jsonld_pages"}
def _seek(ref: Ref) -> str:
    return fetch_seek(ref.source_id)


_FETCHERS: dict[str, _Fetcher] = {
    "seek": _Fetcher("seek.com.au", "seek_detail", lambda ref: fetch_seek(ref.source_id), _seek),
    "ats_smartrecruiters": _Fetcher("smartrecruiters.com", "smartrecruiters_api", fetch_smartrecruiters,
                                    fetch_smartrecruiters),
    "jobspy_src": _Fetcher("linkedin.com", "linkedin_detail", fetch_linkedin, fetch_linkedin),
    "jora": _Fetcher("jora.com", "jora_detail", fetch_jora, fetch_jora),
    "careers_vic": _Fetcher("careers.vic.gov.au", "careers_vic_detail", fetch_careers_vic, fetch_careers_vic),
    "ats_oracle": _Fetcher("oraclecloud.com", "oracle_api", fetch_oracle, fetch_oracle),
    "ats_successfactors": _Fetcher("successfactors", "successfactors_detail", fetch_successfactors,
                                   fetch_successfactors),
    "ats_pageup": _Fetcher("careers.pageuppeople.com", "pageup_detail", fetch_pageup, fetch_pageup),
    "ats_pulse": _Fetcher("pulsesoftware.com", "pulse_api", fetch_pulse, fetch_pulse),
    **{src: _Fetcher(f"jsonld:{key}", f"{key}_jsonld", fetch_jsonld, fetch_jsonld) for src, key in _JSONLD.items()},
}


def would_request(run: Callable[[Ref], str], ref: Ref) -> bool:
    """Would this fetcher send a request for this posting? Runs its own shape and host checks and stops just before
    the request, so a posting it would refuse (an Indeed row, a host not on the employer's site) is known up front and
    costs no budget slot, no pause and no fetch-log try."""
    saved = (getattr(_NOTE, "status", None), getattr(_NOTE, "page", None))
    _NOTE.dry = True
    try:
        run(ref)
    except _WouldRequest:
        return True
    except Exception:                                       # noqa: BLE001 - a fetcher bug is for the real call to report
        return True
    finally:
        _NOTE.dry = False
        _NOTE.status, _NOTE.page = saved
    return False


# The whole ad the collector already holds in raw_json (its `description` is only the first COLLECTOR_CAP characters).
# No request: this is our own stored data.
def _lever_text(raw: dict) -> str:
    """A Lever posting's whole ad: the opening, every list (responsibilities, requirements ...) and the closing."""
    parts = [raw.get("descriptionPlain")]
    for item in raw.get("lists") or []:
        if isinstance(item, dict):
            parts += [item.get("text"), item.get("content")]
    parts.append(raw.get("additionalPlain"))
    return "\n".join(p for p in parts if isinstance(p, str) and p.strip())


_RAW_TEXT: dict[str, Callable[[dict], object]] = {
    "ats_greenhouse": lambda raw: raw.get("content"),
    "ats_ashby": lambda raw: raw.get("descriptionPlain"),
    "ats_workable": lambda raw: raw.get("description"),
    "ats_workday": lambda raw: (raw.get("detail") or {}).get("jobDescription"),
    "ats_lever": lambda raw: _lever_text(raw),
}


def _raw_text(source: str, raw_json) -> str:
    pick = _RAW_TEXT.get(source)
    if not pick or not raw_json:
        return ""
    raw = raw_json if isinstance(raw_json, dict) else _json(raw_json) if isinstance(raw_json, str) else None
    if not isinstance(raw, dict):
        return ""
    try:
        value = pick(raw)
    except (AttributeError, TypeError):
        return ""
    return html_to_text(value, limit=MAX_TEXT) if isinstance(value, str) else ""


def classify(ad: str | None, description: str | None, source: str = "", raw_json=None) -> tuple[str, str]:
    """(text, kind) from what is stored, no request. The ONE rule for the reader and for rederive:
      full     a fetched ad (ad_text), the whole ad found in raw_json when it is longer than the description, or a
               description that is the whole ad (MIN_FULL <= len < COLLECTOR_CAP)
      partial  a description cut at the collector cap (len >= COLLECTOR_CAP) and no whole ad stored: NOT the full ad
      teaser   a short description."""
    if ad and ad.strip():
        return ad, "full"
    desc = (description or "").strip()
    raw = _raw_text(source, raw_json)
    if len(raw) >= MIN_FULL and len(raw) > len(desc):      # the whole ad the collector holds (Lever: lists, closing) beats its cut
        return raw, "full"
    if MIN_FULL <= len(desc) < COLLECTOR_CAP:
        return desc, "full"
    return desc, "partial" if len(desc) >= COLLECTOR_CAP else "teaser"


def _field(posting, name: str, default=None):
    """A column of a sqlite Row or a dict, whether or not the query selected it."""
    try:
        return posting[name] if name in posting.keys() else default
    except (AttributeError, TypeError, IndexError):
        return default


def _row_extras(conn, posting) -> tuple:
    """(url, raw_json) of a posting, read from the database when the row lacks them (reader.py's query need not
    select them)."""
    url, raw = _field(posting, "url"), _field(posting, "raw_json")
    if url is None or raw is None:
        row = conn.execute("SELECT url, raw_json FROM postings WHERE id=?", (posting["id"],)).fetchone()
        if row:
            url = row["url"] if url is None else url
            raw = row["raw_json"] if raw is None else raw
    return url, raw


def _ref(conn, posting) -> Ref:
    """Everything a fetcher may need. All of it comes from our own database."""
    url, raw = _row_extras(conn, posting)
    data = _json(raw) if isinstance(raw, str) and raw else None
    return Ref(posting["source"], posting["source_id"] or "", url or "", _field(posting, "title") or "",
               data if isinstance(data, dict) else {})


def local_text(conn, posting) -> tuple[str, str]:
    """(text, kind) from the database alone: ad_text, the description, raw_json. Same rule as `classify`."""
    have = get_text(conn, posting["id"])
    if have and have[0].strip():
        return have[0], "full"
    desc = _field(posting, "description")
    if desc is None:
        row = conn.execute("SELECT description FROM postings WHERE id=?", (posting["id"],)).fetchone()
        desc = row["description"] if row else ""
    raw = _field(posting, "raw_json")
    if raw is None and posting["source"] in _RAW_TEXT:
        raw = _row_extras(conn, posting)[1]
    return classify(None, desc, posting["source"], raw)


# --- the fetch log (table ad_fetch) -------------------------------------------------------------------------------
def fetch_state(conn, posting_id: int):
    return conn.execute("SELECT tries, last_try_at, last_status FROM ad_fetch WHERE posting_id=?",
                        (posting_id,)).fetchone()


def fetch_due(conn, posting_id: int, now: datetime | None = None) -> bool:
    """May this ad's page be requested now? Not after FETCH_MAX_TRIES tries, nor within FETCH_RETRY_HOURS of the last."""
    row = fetch_state(conn, posting_id)
    if row is None:
        return True
    if (row["tries"] or 0) >= FETCH_MAX_TRIES:
        return False
    try:
        last = datetime.fromisoformat(row["last_try_at"])
    except (TypeError, ValueError):
        return True
    return (now or now_utc()) - last >= timedelta(hours=FETCH_RETRY_HOURS)


def _record_fetch(conn, posting_id: int, status: str) -> None:
    def write():
        conn.execute(
            "INSERT INTO ad_fetch(posting_id, tries, last_try_at, last_status) VALUES(?,1,?,?) "
            "ON CONFLICT(posting_id) DO UPDATE SET tries=tries+1, last_try_at=excluded.last_try_at, "
            "last_status=excluded.last_status", (posting_id, dbm.ts(), status[:120]))
    try:
        write_retry(conn, write)
    except sqlite3.Error as exc:                            # the log must never hide the fetch's own outcome
        log.warning("adtext: could not log the fetch of %s: %s", posting_id, exc)


def wants_fetch(conn, posting, now: datetime | None = None, *, force: bool = False) -> bool:
    """Is a page request worth making for this posting now: it has a fetcher that would not refuse it, its stored text
    is not the whole ad and the fetch log allows another try (force: the owner asked, so the 24 h wait and the
    try cap are skipped)."""
    spec = _FETCHERS.get(posting["source"])
    if spec is None or local_text(conn, posting)[1] == "full":
        return False
    if not force and not fetch_due(conn, posting["id"], now):
        return False
    return spec.real is None or would_request(spec.real, _ref(conn, posting))


# a failed fetch that says something about the HOST (not about this ad): counted by the reader, 3 in a row stop the host
HOST_FAILURES = ("wall", "empty", "blocked", "error")


def is_host_failure(status: str | None) -> bool:
    return bool(status) and status.split(":", 1)[0] in HOST_FAILURES


# -- last-resort fetch through TinyFish -------------------------------------------------------------------------
# Used only when the direct request is refused or returns a bot wall. The key never lives in config or the repo;
# the file is read at run time. A per-process cap keeps a broken day from spending a credit budget unattended.
_TINYFISH_URL = "https://api.fetch.tinyfish.ai"
_TINYFISH_KEY = "~/.config/jobwatch/tinyfish.key"
_tinyfish_used = 0


def tinyfish_cap() -> int:
    try:
        return max(0, int(os.environ.get("JOBWATCH_TINYFISH_PER_RUN", "10")))
    except ValueError:
        return 10


def _tinyfish_key() -> str:
    try:
        return Path(_TINYFISH_KEY).expanduser().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def tinyfish_text(url: str, *, timeout: float = 25.0) -> str:
    """One page through TinyFish, or "" when it is not configured, capped, refused or empty."""
    global _tinyfish_used
    if _tinyfish_used >= tinyfish_cap():
        return ""
    key = _tinyfish_key()
    if not key:
        return ""
    body = json.dumps({"urls": [url]}).encode("utf-8")
    request = urllib.request.Request(_TINYFISH_URL, data=body, method="POST",
                                     headers={"Content-Type": "application/json", "X-API-Key": key})
    _tinyfish_used += 1
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except Exception as exc:                              # noqa: BLE001 - a fallback never fails the read
        log.warning("adtext: tinyfish failed for %s: %s", urlsplit(url).hostname, type(exc).__name__)
        return ""
    if not payload.get("results"):
        # TinyFish reports a refusal inside a 200 body: {"results":[],"errors":[{"error":"bot_blocked"}]}
        why = ((payload.get("errors") or [{}])[0] or {}).get("error") or "empty"
        log.warning("adtext: tinyfish refused %s: %s", urlsplit(url).hostname, why)
        return ""
    item = (payload.get("results") or [payload.get("result") or payload])[0]
    text = (item or {}).get("content") or (item or {}).get("markdown") or (item or {}).get("text") or ""
    return str(text).strip()

def ensure_text(conn, posting, fetcher=None, *, allow_fetch: bool = True, now: datetime | None = None,
                force: bool = False, deadline: float | None = None) -> tuple[str, str]:
    """(text, kind) for one posting row, kind = 'full' | 'partial' | 'teaser'. May fetch (one request) when allow_fetch,
    the source has a fetcher that would not refuse the posting and the fetch log allows it (force skips the log's
    wait and try cap); every attempt is logged (see last_status).

    `fetcher`, when given, is a test double `fetcher(source_id) -> text` that replaces the network call."""
    text, kind = local_text(conn, posting)
    if deadline is not None and deadline <= time.time():
        return text, kind
    spec = _FETCHERS.get(posting["source"]) if allow_fetch and kind != "full" else None
    if not spec or not (force or fetch_due(conn, posting["id"], now)):
        return text, kind
    ref = _ref(conn, posting)
    if not fetcher and spec.real and not would_request(spec.real, ref):
        return text, kind                                   # nothing to ask: no request, no logged try
    _NOTE.status, _NOTE.page = None, None
    token = _FETCH_DEADLINE.set(deadline)
    try:
        got = (fetcher(posting["source_id"]) if fetcher else spec.run(ref)) or ""
    except Blocked as exc:
        # The site said stop. One fallback request through TinyFish can still return the ad, and it is capped.
        # reader._BASE_SQL does not select p.url, so the address comes from the ref, not from the row.
        got = "" if fetcher or not ref.url else tinyfish_text(ref.url)
        if got:
            _note("fallback: tinyfish")
        else:
            _note(f"blocked: {exc}")
            _record_fetch(conn, posting["id"], last_status())
            raise
    except Exception as exc:
        _note(f"error: {type(exc).__name__}")
        _record_fetch(conn, posting["id"], f"error: {type(exc).__name__}: {str(exc)[:60]}")
        raise
    finally:
        _FETCH_DEADLINE.reset(token)
    got = got[:MAX_TEXT]
    # a page text replaces a teaser when longer, and a cut text when it is about as long or longer
    if got and len(got) >= (len(text) * 0.9 if kind == "partial" else len(text) + 1):
        save_text(conn, posting["id"], got, spec.label)
        _note("ok")
        _record_fetch(conn, posting["id"], "ok")
        return got, "full"
    if got:
        _note("empty")                                      # shorter than what we already have: not the ad
    elif last_status() is None:
        _note("empty")
    _record_fetch(conn, posting["id"], last_status() or "empty")
    return text, kind


def fetch_host(source: str) -> str | None:
    """A stable key for the site we may fetch an ad body from for this posting source (None = no fetcher)."""
    spec = _FETCHERS.get(source)
    return spec.host if spec else None


def pace(seconds: float = 2.5) -> None:
    pause(seconds)


# --- one review/recall run at a time ----------------------------------------------------------------------------
def lock_path(config) -> Path:
    """review.lock next to the database."""
    return Path(config.db_path).parent / "review.lock"


@contextlib.contextmanager
def review_lock(path):
    """Non-blocking flock: yields True when this process now holds the lock, False when another run does (the caller
    skips quietly). The lock goes when the block ends or the process dies."""
    import fcntl
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        yield False
        return
    try:
        yield True
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()
