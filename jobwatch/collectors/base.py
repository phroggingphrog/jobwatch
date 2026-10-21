"""Shared collector context and helpers."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable
from xml.etree.ElementTree import ParseError

from ..config import Config
from ..http import Fetcher, HttpError
from ..models import Posting

log = logging.getLogger("jobwatch.collectors")

# One employer/feed failing (HTTP, bad payload shape, malformed XML) must not lose the others.
SOURCE_ERRORS = (HttpError, ValueError, KeyError, TypeError, AttributeError, IndexError, ParseError)


@dataclass
class CollectorContext:
    config: Config
    http: Fetcher
    limit: int | None = None                     # max postings per collector this run
    tier: str = "fast"                           # fast | slow | all (deep collectors read more on slow/all)
    errors: list[str] = field(default_factory=list)
    title_relevant: Callable[[str], bool] = lambda title: True
    is_known: Callable[[str, str], bool] = lambda source, source_id: False
    state_get: Callable[[str, Any], Any] = lambda key, default=None: default
    state_set: Callable[[str, Any], None] = lambda key, value: None
    reddit_posts: list[dict] = field(default_factory=list)   # filled by the reddit collector
    origins: set[str] = field(default_factory=set)           # employers/feeds actually fetched
    raw_count: int = 0                                       # rows seen before the AU gate

    def count_raw(self, n: int) -> None:
        self.raw_count += int(n or 0)

    @property
    def employers(self) -> list[dict]:
        return self.config.employers

    def employers_for(self, provider: str) -> list[dict]:
        return self.config.employers_for(provider)

    @property
    def deep(self) -> bool:
        """True on slow/all runs: collectors that page newest-first may read further back."""
        return self.tier in ("slow", "all")

    def full(self, results: list) -> bool:
        return self.limit is not None and len(results) >= self.limit

    def error(self, where: str, exc: Exception | str) -> None:
        msg = f"{where}: {exc}"
        log.warning(msg)
        self.errors.append(msg[:300])


def run_per_employer(cfg: CollectorContext, provider: str,
                     fetch_one: Callable[[CollectorContext, dict], Iterable[Posting]]) -> list[Posting]:
    """Iterate the enabled employers for one provider; one failure never stops the rest."""
    results: list[Posting] = []
    for employer in cfg.employers_for(provider):
        if cfg.full(results):
            break
        name = employer.get("name") or employer.get("tenant") or "?"
        try:
            for posting in fetch_one(cfg, employer):
                posting.origin = posting.origin or name
                results.append(posting)
                if cfg.full(results):
                    break
            cfg.origins.add(f"{provider}:{name}")
        except SOURCE_ERRORS as exc:
            cfg.error(name, exc)
    return results


def rotate(cfg: CollectorContext, key: str, items: list, per_run: int | None) -> list:
    """Take `per_run` items starting at a stored cursor, so every item gets its turn."""
    if not items or not per_run or per_run >= len(items):
        return list(items)
    start = int(cfg.state_get(f"cursor:{key}", 0) or 0) % len(items)
    chosen = [items[(start + i) % len(items)] for i in range(per_run)]
    cfg.state_set(f"cursor:{key}", (start + per_run) % len(items))
    return chosen


def first(*values):
    for v in values:
        if v not in (None, "", [], {}):
            return v
    return None
