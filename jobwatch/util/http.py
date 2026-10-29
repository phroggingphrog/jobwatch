"""Polite HTTP: one session, per-host delay, 20 s timeout, robots.txt for pages, back-off.

No proxies, no stealth. A 403/429/5xx marks the host blocked for the rest of the run,
so a collector stops hitting it and records the error instead of retrying.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

from .deadline import Budget

log = logging.getLogger(__name__)

BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0.0.0 Safari/537.36"
)
ROBOTS_AGENT = "jobwatch"


class HttpError(RuntimeError):
    def __init__(self, url: str, status: int, message: str = ""):
        host = urlsplit(url).hostname or url
        super().__init__(message or f"HTTP {status} from {host}")
        self.url, self.status = url, status


class Blocked(HttpError):
    """Host answered 403/429/5xx earlier in this run, or robots.txt disallows the URL."""


class Fetcher:
    def __init__(self, user_agent: str = BROWSER_UA, timeout: float = 20.0,
                 min_delay: float = 1.5, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic, deadline: float | None = None):
        self.session = requests.Session()
        self.session.trust_env = False          # never pick up proxy env vars
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept-Language": "en-AU,en;q=0.9",
        })
        self.timeout = min(float(timeout), 20.0)
        self.min_delay = max(1.0, min(float(min_delay), 2.0))
        self.sleep, self.clock = sleep, clock
        self._last: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self.blocked: dict[str, str] = {}
        self.requests_made = 0
        self.deadline = deadline
        self.budget = Budget(deadline, clock, sleep) if deadline is not None else None

    def _remaining_timeout(self, url: str) -> float:
        return self.timeout if self.budget is None else min(self.timeout, self.budget.remaining())

    # -- pacing -----------------------------------------------------------
    def _pace(self, url: str, delay: float | None = None) -> None:
        host = urlsplit(url).hostname or ""
        if host in self.blocked:
            raise Blocked(url, 0, f"{host} backed off this run ({self.blocked[host]})")
        wait = (delay or self.min_delay) - (self.clock() - self._last.get(host, -1e9))
        if wait > 0:
            self.sleep(min(wait, self._remaining_timeout(url)))
        self._remaining_timeout(url)
        self._last[host] = self.clock()

    def _check(self, url: str, response: requests.Response) -> requests.Response:
        status = response.status_code
        if status in (403, 429) or status >= 500:
            host = urlsplit(url).hostname or ""
            self.blocked[host] = f"HTTP {status}"
            raise HttpError(url, status)
        if status >= 400:
            raise HttpError(url, status)
        return response

    def request(self, method: str, url: str, *, delay: float | None = None,
                headers: dict | None = None, **kwargs: Any) -> requests.Response:
        self._pace(url, delay)
        self.requests_made += 1
        try:
            response = self.session.request(method, url, timeout=self._remaining_timeout(url),
                                            headers=headers, **kwargs)
        except requests.RequestException as exc:
            self._remaining_timeout(url)
            raise HttpError(url, 0, f"{type(exc).__name__} for {urlsplit(url).hostname}") from exc
        self._remaining_timeout(url)
        return self._check(url, response)

    # -- helpers used by collectors -----------------------------------------
    def get_json(self, url: str, params: dict | None = None, **kw: Any) -> Any:
        r = self.request("GET", url, params=params, headers={"Accept": "application/json"}, **kw)
        try:
            return r.json()
        except ValueError as exc:
            raise HttpError(url, r.status_code, "response was not JSON") from exc

    def post_json(self, url: str, body: dict, **kw: Any) -> Any:
        r = self.request("POST", url, json=body,
                         headers={"Accept": "application/json", "Content-Type": "application/json"}, **kw)
        try:
            return r.json()
        except ValueError as exc:
            raise HttpError(url, r.status_code, "response was not JSON") from exc

    def get_text(self, url: str, params: dict | None = None, *, robots: bool = False,
                 headers: dict | None = None, **kw: Any) -> str:
        """GET text. robots=True enforces robots.txt (used for HTML page fetches)."""
        if robots and not self.allowed(url):
            raise Blocked(url, 0, f"robots.txt disallows {urlsplit(url).path or '/'}")
        r = self.request("GET", url, params=params, headers=headers, **kw)
        return r.text

    def get_response(self, url: str, **kw: Any) -> requests.Response:
        return self.request("GET", url, **kw)

    # -- robots ---------------------------------------------------------------
    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser: RobotFileParser | None = RobotFileParser()
            try:
                self._pace(origin + "/robots.txt")
                self.requests_made += 1
                r = self.session.get(origin + "/robots.txt", timeout=self._remaining_timeout(url))
                if r.status_code in (401, 403) or r.status_code >= 500:
                    parser.disallow_all = True              # denial = full disallow
                elif r.status_code >= 400:
                    parser.allow_all = True                 # no robots.txt = allowed
                else:
                    parser.parse(r.text.splitlines())
            except (requests.RequestException, Blocked):
                parser.disallow_all = True
            self._robots[origin] = parser
        parser = self._robots[origin]
        return parser.can_fetch(ROBOTS_AGENT, url) if parser else True
