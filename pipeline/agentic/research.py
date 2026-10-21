"""Narrow public-job research adapter with immutable facts and fail-closed fetching."""
from __future__ import annotations

import ipaddress
import socket
import ssl
import threading
import time
import http.client
import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from html.parser import HTMLParser
import re
from typing import Callable
from urllib.parse import urlsplit


class ResearchUnavailable(RuntimeError):
    """Public fixed-code failure; never includes URL, DNS, or remote text."""
    def __init__(self): super().__init__("research_unavailable")


class PublicHTTPStatus(ResearchUnavailable):
    """Observed HTTP status, without URL, headers or response content."""
    def __init__(self,status,location=None):
        super().__init__()
        self.status=status
        self.location=location   # a redirect's Location header, so a caller can decide whether to follow it


class ResearchIntent(str, Enum):
    EMPLOYER_IDENTITY = "employer_identity"
    ROLE_CONTEXT = "role_context"
    DESIRED_SKILLS = "desired_skills"
    COMPENSATION = "compensation"
    INTERVIEW_PROCESS = "interview_process"
    INTERVIEW_QUESTIONS = "interview_questions"


@dataclass(frozen=True)
class PublicSnapshot:
    employer: str
    title: str
    posting_url: str

    def __post_init__(self):
        if not all(type(v) is str and v.strip() and len(v) <= 300 for v in (self.employer, self.title)):
            raise ValueError("invalid_public_snapshot")
        parsed = urlsplit(self.posting_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("invalid_public_snapshot")


@dataclass(frozen=True)
class ResearchResult:
    result_id: str
    title: str
    url: str


@dataclass(frozen=True)
class ResearchPage:
    result_id: str
    text: str


class LocalSearxSearch:
    """Use the owner's existing search service; the model cannot choose its URL."""
    def __init__(self, session_factory=None, clock=time.time):
        if session_factory is None:
            import requests
            session_factory = requests.Session
        self.session_factory = session_factory
        self.clock = clock
        self._cache = {}

    def search(self, query: str, *, deadline: float):
        try:
            started = self.clock()
            remaining = min(5.0, deadline - started)
            request_deadline = started + remaining
            if remaining <= 0 or type(query) is not str or not query or len(query) > 650:
                raise ValueError
            cached = self._cache.get(query)
            if cached and self.clock() - cached[0] < 300:
                return [dict(item) for item in cached[1]]
            with self.session_factory() as session:
                session.trust_env = False
                with session.get('http://127.0.0.1:8888/search',
                                 params={'q': query, 'format': 'json'},
                                 timeout=min(5.0, remaining), stream=True,
                                 allow_redirects=False) as response:
                    if response.status_code != 200:
                        raise ValueError
                    payload = bytearray()
                    for chunk in response.iter_content(chunk_size=16_384):
                        payload.extend(chunk)
                        if len(payload) > 1_000_000 or self.clock() >= request_deadline:
                            raise ValueError
            data = json.loads(payload)
            if type(data) is not dict or type(data.get('results')) is not list:
                raise ValueError
            results = []
            for item in data['results']:
                if type(item) is not dict:
                    continue
                url, title = item.get('url'), item.get('title')
                if type(url) is not str or type(title) is not str or len(url) > 4096:
                    continue
                parsed = urlsplit(url)
                if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                    continue
                results.append({'result_id': hashlib.sha256(url.encode()).hexdigest(),
                                'title': title[:500], 'url': url})
                if len(results) == 3:
                    break
            if len(self._cache) >= 16:
                self._cache.clear()
            self._cache[query] = (self.clock(), results)
            return [dict(item) for item in results]
        except Exception:
            raise ResearchUnavailable() from None


@dataclass(frozen=True)
class PublicDocument:
    body: bytes
    content_type: str


def _pinned_https_fetch(url: str, *, addresses: tuple[str, ...], server_hostname: str,
                       timeout: float, allow_redirects: bool, trust_env: bool, max_bytes: int, with_metadata: bool = False) -> bytes | PublicDocument:
    """Connect to a validated literal IP while authenticating TLS against the URL host."""
    if allow_redirects or trust_env or not addresses:
        raise ResearchUnavailable()
    parsed = urlsplit(url)
    deadline = time.monotonic() + timeout

    def remaining():
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError()
        return value

    for address in addresses:
        conn = None
        try:
            # Passing a literal IP prevents a second DNS lookup; set SNI and certificate
            # verification to the original public hostname explicitly.
            conn = http.client.HTTPConnection(address, parsed.port or 443, timeout=remaining())
            conn.connect()
            conn.sock.settimeout(remaining())
            conn.sock = ssl.create_default_context().wrap_socket(conn.sock, server_hostname=server_hostname)
            active_socket = conn.sock
            active_socket.settimeout(remaining())
            path = parsed.path or "/"
            if parsed.query: path += "?" + parsed.query
            conn.request("GET", path, headers={"Host": parsed.netloc, "Connection": "close",
                                                   "User-Agent": "Jobwatch/1.0 (public vacancy verification)"})
            active_socket.settimeout(remaining())
            response = conn.getresponse()
            if response.status != 200:
                raise PublicHTTPStatus(response.status, response.getheader('Location') if 300 <= response.status < 400 else None)
            data = bytearray()
            while True:
                active_socket.settimeout(remaining())
                chunk = response.read1(min(16_384, max_bytes + 1 - len(data)))
                remaining()
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > max_bytes:
                    raise ValueError("too large")
                if response.isclosed():
                    break
            if response.length not in (None, 0):
                raise ValueError("incomplete_response")
            if with_metadata:
                if response.getheader('Content-Encoding','identity').lower()!='identity':raise ValueError('encoding')
                return PublicDocument(bytes(data),response.getheader('Content-Type','application/octet-stream'))
            return bytes(data)
        except PublicHTTPStatus:
            raise
        except Exception:
            if time.monotonic() >= deadline:
                break
        finally:
            if conn is not None: conn.close()
    raise ResearchUnavailable() from None


def _readable_public_text(html: str, limit: int = 16_000) -> str:
    """Bound useful public context; scripts/styles are not employer evidence."""
    class Text(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.skip, self.parts = 0, []

        def handle_starttag(self, tag, attrs):
            if tag in {'script', 'style', 'noscript', 'svg'}:
                self.skip += 1
            elif tag in {'p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'tr'} and not self.skip:
                self.parts.append('\n')

        def handle_endtag(self, tag):
            if tag in {'script', 'style', 'noscript', 'svg'} and self.skip:
                self.skip -= 1
            elif tag in {'p', 'div', 'li', 'h1', 'h2', 'h3', 'tr'} and not self.skip:
                self.parts.append('\n')

        def handle_data(self, data):
            if not self.skip:
                self.parts.append(data)

    parser = Text()
    parser.feed(html)
    parser.close()
    text = '\n'.join(line.strip() for line in re.sub(r'[ \t\r\f\v]+', ' ', ''.join(parser.parts)).splitlines()
                     if line.strip())
    if len(text) > limit:
        return text[:limit].rstrip() + '\n[Public page text truncated at 16000 characters.]'
    return text


class SafeFetcher:
    """HTTPS fetcher requiring public DNS answers and an injected IP-pinning connector."""
    def __init__(self, resolver: Callable[[str], list[str]] | None = None,
                 connector: Callable[..., bytes] | None = None, max_bytes: int = 1_000_000,
                 timeout: float = 5.0):
        self.resolver = resolver or self._resolve
        self.connector = connector or _pinned_https_fetch
        self.max_bytes = max_bytes
        self.timeout = timeout

    @staticmethod
    def _resolve(host: str) -> list[str]:
        return list({item[4][0] for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)})

    def fetch(self, url: str, *, deadline: float | None = None) -> str:
        return _readable_public_text(self.fetch_bytes(url, deadline=deadline).decode("utf-8", errors="replace"))

    def fetch_bytes(self, url: str, *, deadline: float | None = None) -> bytes:
        """Bounded complete document for structured parsers; never silently truncate.

        Public research still uses fetch() and its readable-text cap. Whole-JD
        consumers must validate document identity/content before accepting bytes.
        """
        return self._fetch(url,deadline=deadline,with_metadata=False)

    def fetch_document(self, url: str, *, deadline: float | None = None) -> PublicDocument:
        """Preserve upstream content type/charset for an isolated browser renderer."""
        return self._fetch(url,deadline=deadline,with_metadata=True)

    def _fetch(self,url,*,deadline,with_metadata):
        try:
            if type(url) is not str or len(url) > 8192 or any(ord(c) < 32 or ord(c) == 127 for c in url):
                raise ValueError
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or self.connector is None:
                raise ValueError
            if deadline is not None and time.monotonic() >= deadline: raise TimeoutError
            addresses = self.resolver(parsed.hostname)
            if not addresses: raise ValueError
            ips = [ipaddress.ip_address(a) for a in addresses]
            if any(not ip.is_global for ip in ips): raise ValueError
            if deadline is not None and time.monotonic() >= deadline: raise TimeoutError
            extra={"with_metadata":True} if with_metadata else {}
            payload = self.connector(url, addresses=tuple(str(ip) for ip in ips),
                                     server_hostname=parsed.hostname,
                                     timeout=min(self.timeout, max(0.001, deadline-time.monotonic()) if deadline is not None else self.timeout),
                                     allow_redirects=False, trust_env=False, max_bytes=self.max_bytes, **extra)
            body=payload.body if with_metadata and isinstance(payload,PublicDocument) else payload
            if type(body) is not bytes or len(body) > self.max_bytes: raise ValueError
            if with_metadata and (not isinstance(payload,PublicDocument) or not isinstance(payload.content_type,str)
                    or len(payload.content_type)>500 or any(ord(c)<32 for c in payload.content_type)):raise ValueError
            if deadline is not None and time.monotonic() >= deadline: raise TimeoutError
            return payload
        except PublicHTTPStatus:
            raise
        except Exception:
            raise ResearchUnavailable() from None


class ResearchCapability:
    def __init__(self, snapshot: PublicSnapshot, *, search_provider=None, fetcher=None,
                 budget=None, clock: Callable[[], float] = time.time, deadline: float | None = None):
        self.snapshot = snapshot
        self.search_provider = search_provider
        self.fetcher = fetcher
        self.budget = budget
        self.clock = clock
        self.deadline = deadline
        self._results: dict[str, ResearchResult] = {}
        self._lock = threading.RLock()

    def _live(self):
        if self.deadline is not None and self.clock() >= self.deadline: raise ResearchUnavailable()
        if self.budget is not None: self.budget.ensure_live()

    def search(self, intent: ResearchIntent) -> tuple[ResearchResult, ...]:
        if type(intent) is not ResearchIntent: raise ResearchUnavailable() from None
        with self._lock:
            self._live()
            if self.budget is not None: self.budget.research("query")
            if self.search_provider is None: raise ResearchUnavailable()
            label = {ResearchIntent.EMPLOYER_IDENTITY: "employer identity",
                     ResearchIntent.ROLE_CONTEXT: "role context",
                     ResearchIntent.DESIRED_SKILLS: "skills qualifications responsibilities careers",
                     ResearchIntent.COMPENSATION: "compensation",
                     ResearchIntent.INTERVIEW_PROCESS: "interview process recruiter hiring manager",
                     ResearchIntent.INTERVIEW_QUESTIONS: "reported interview questions"}[intent]
            query = f"{self.snapshot.employer} {self.snapshot.title} {label}"
            if (intent is ResearchIntent.EMPLOYER_IDENTITY
                    and self.snapshot.employer.strip().casefold() not in {"private advertiser", "confidential", "unknown"}):
                query = f"{self.snapshot.employer} official website"
            try:
                raw = self.search_provider.search(query, deadline=self.deadline or self.clock()+5)
                if len(raw) > 3: raw = raw[:3]
                results = []
                for item in raw:
                    rid, title, url = item.get("result_id"), item.get("title"), item.get("url")
                    parsed = urlsplit(url or "")
                    if (type(rid) is not str or not rid or len(rid) > 128 or type(title) is not str
                            or len(title) > 500 or parsed.scheme != "https" or not parsed.hostname
                            or parsed.username or parsed.password):
                        continue
                    result = ResearchResult(rid, title, url)
                    self._results[rid] = result
                    results.append(result)
                return tuple(results)
            except Exception:
                raise ResearchUnavailable() from None

    def fetch(self, result_id: str) -> ResearchPage:
        with self._lock:
            self._live()
            if type(result_id) is not str or result_id not in self._results or self.fetcher is None:
                raise ResearchUnavailable() from None
            if self.budget is not None: self.budget.research("page")
            result = self._results[result_id]
            try:
                remaining = min(5.0, self.deadline - self.clock()) if self.deadline is not None else 5.0
                if remaining <= 0:
                    raise ResearchUnavailable()
                text = self.fetcher.fetch(result.url, deadline=time.monotonic() + remaining)
                if type(text) is not str or len(text.encode("utf-8")) > 1_000_000: raise ValueError
                return ResearchPage(result_id, text)
            except Exception:
                raise ResearchUnavailable() from None
