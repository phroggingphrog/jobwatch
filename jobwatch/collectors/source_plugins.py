"""Extensible user-defined sources, plus built-in feed and GradConnection plugins."""
from __future__ import annotations

import importlib.util
import json
import concurrent.futures
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import feedparser
import yaml
from bs4 import BeautifulSoup

from .. import users
from ..models import Posting, html_to_text, iso
from .base import CollectorContext

NAME = "source_plugins"
VERSION = "1.0"
FIELDS = ("title", "company", "location", "work_type", "posted_at", "url", "description")

class PluginError(ValueError):
    pass

class PluginHTTP:
    """Plugin-facing shared fetcher with per-source pages and cache controls."""
    def __init__(self, http, options, cache=None):
        self.http = http
        self.options = options
        self.pages = 0
        self.cache = cache if cache is not None else {}
        self.cache_enabled = bool(options.get("cache_enabled", True))
        self.cache_ttl_seconds = max(0, int(options.get("cache_ttl_seconds", 300)))
        self.lock = threading.Lock()

    def get_text(self, url):
        if urlsplit(url).scheme not in ("http", "https") or not urlsplit(url).netloc:
            raise PluginError("HTTP URL must be absolute")
        with self.lock:
            if self.cache_enabled and url in self.cache:
                cached_at, cached_text = self.cache[url]
                if time.monotonic() - cached_at <= self.cache_ttl_seconds:
                    return cached_text
            limit = max(1, min(int(self.options.get("max_pages_per_run", 5)), 100))
            if self.pages >= limit:
                raise PluginError(f"page limit reached ({limit})")
            self.pages += 1
        robots = self.options.get("respect_robots", True)
        if robots and not self.http.allowed(url):
            raise PluginError(f"robots.txt disallows {urlsplit(url).path or '/'}")
        timeout = max(0.1, min(20.0, float(self.options.get("timeout_seconds", 20))))
        text = self.http.get_text(url, robots=False, delay=max(2.0, float(self.options.get("min_interval_seconds", 2))), timeout=timeout)
        if self.cache_enabled:
            with self.lock:
                self.cache[url] = (time.monotonic(), text)
        return text

class PluginContext:
    def __init__(self, http):
        self.http = http


def _valid(postings, plugin_name):
    if not isinstance(postings, list):
        raise PluginError(f"{plugin_name}: invalid result: expected list[Posting], got {type(postings).__name__}")
    for i, p in enumerate(postings):
        if not isinstance(p, Posting):
            raise PluginError(f"{plugin_name}: invalid result at index {i}: expected Posting, got {type(p).__name__}")
        for field in ("title", "url", "source_id", "company"):
            if not str(getattr(p, field, "") or "").strip():
                raise PluginError(f"{plugin_name}: invalid result at index {i}: missing required field {field}")
        if urlsplit(p.url).scheme not in ("http", "https") or not urlsplit(p.url).netloc:
            raise PluginError(f"{plugin_name}: invalid result at index {i}: url must be HTTP(S)")
    return postings


def _entry_value(entry, key):
    value = entry
    for part in key.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit():
            value = value[int(part)] if int(part) < len(value) else None
        else:
            return None
    return value


def _parse_declarative(text, source):
    fmt, mapping = source.get("feed_type"), source.get("mapping", {})
    items = []
    if fmt in ("rss", "atom"):
        parsed = feedparser.parse(text)
        entries = parsed.entries
        aliases = {"url": "link", "posted_at": "published", "description": "summary"}
        for e in entries:
            row = {}
            for field, path in mapping.items():
                if isinstance(path, str):
                    row[field] = e.get(path, e.get(aliases.get(path, "")))
            if not mapping:
                row = {"title": e.get("title"), "url": e.get("link"), "id": e.get("id") or e.get("link"),
                       "company": e.get("author"), "location": e.get("location"),
                       "posted_at": e.get("published") or e.get("updated"),
                       "description": e.get("summary"), "work_type": e.get("work_type")}
            items.append(row)
    elif fmt == "json":
        data = json.loads(text)
        rows = _entry_value(data, source.get("items_path", "items")) or []
        if not isinstance(rows, list):
            raise PluginError("items_path must resolve to a list")
        items = [{k: _entry_value(row, path) for k, path in mapping.items()} for row in rows]
    elif fmt == "html":
        soup = BeautifulSoup(text, "html.parser")
        selector = source.get("item_selector")
        if not selector:
            raise PluginError("HTML source requires item_selector")
        for node in soup.select(selector):
            row = {}
            for field, rule in mapping.items():
                if isinstance(rule, str):
                    rule = {"selector": rule, "attribute": "text"}
                found = node.select_one(rule["selector"])
                row[field] = (found.get(rule["attribute"]) if found and rule.get("attribute") not in (None, "text")
                              else found.get_text(" ", strip=True) if found else None)
            items.append(row)
    else:
        raise PluginError(f"unsupported feed_type {fmt!r}")
    return items


def _posting(row, name, defaults):
    title = str(row.get("title") or "").strip()
    url = str(row.get("url") or row.get("link") or "").strip()
    company = str(row.get("company") or defaults.get("company") or name).strip()
    posted = row.get("posted_at") or row.get("published") or row.get("updated")
    desc = html_to_text(str(row.get("description") or row.get("summary") or ""))
    work = str(row.get("work_type") or "")
    if work:
        low = work.lower()
        work = "PT" if "part" in low else "FT" if "full" in low else "casual" if "casual" in low else work
    return Posting(source=name, source_id=str(row.get("id") or url), url=url, title=title,
                   company=company, location=str(row.get("location") or defaults.get("location") or ""),
                   work_type=work or None, posted_at=iso(posted) if posted else None,
                   posted_at_source="provider" if posted else "observed", description=desc, origin=name,
                   raw={k: v for k, v in row.items() if k in FIELDS or k in ("id", "published", "summary")})


def declarative_plugin(source, http):
    text = http.get_text(source["url"])
    rows = _parse_declarative(text, source)
    return [_posting(row, source["name"], source) for row in rows]


def rss_plugin(source, http):
    """Generic RSS/Atom mapping plugin. The configured feed URLs define its pages."""
    feeds = source.get("feeds") or [source]
    result = []
    for feed in feeds:
        text = http.get_text(feed["url"])
        config = dict(feed)
        config["feed_type"] = "rss" if config.get("feed_type") == "atom" else config.get("feed_type", "rss")
        rows = _parse_declarative(text, config)
        result.extend(_posting(row, source["name"], feed) for row in rows)
    return result


def gradconnection_plugin(source, http):
    """Read listing JSON/HTML and normalize conservatively; configured URL is the only fetch target."""
    text = http.get_text(source["url"])
    try:
        data = json.loads(text)
        rows = data if isinstance(data, list) else data.get("jobs", data.get("results", []))
        if not isinstance(rows, list):
            raise ValueError("JSON does not contain a jobs/results list")
        return [_posting({"title": r.get("title"), "company": r.get("employer") or r.get("company"),
                          "location": r.get("location"), "work_type": r.get("job_type") or r.get("type"),
                          "posted_at": r.get("posted_at") or r.get("date"), "url": r.get("url") or r.get("link"),
                          "description": r.get("description"), "id": r.get("id")}, source["name"], source) for r in rows]
    except (json.JSONDecodeError, AttributeError):
        pass
    soup = BeautifulSoup(text, "html.parser")
    selector = source.get("item_selector", "article")
    result = []
    for node in soup.select(selector):
        def val(key, default=None):
            sel = source.get("selectors", {}).get(key)
            found = node.select_one(sel) if sel else None
            if key == "url":
                return found.get("href") if found else default
            return found.get_text(" ", strip=True) if found else default
        result.append(_posting({k: val(k) for k in FIELDS}, source["name"], source))
    return result


def _plugin_dir():
    return (users.user_dir() / "config" / "sources")


def _with_timeout(call, timeout, *args):
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(call, *args)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        raise PluginError(f"plugin timed out after {timeout:g} seconds") from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _load_python(path):
    path = Path(path).expanduser().resolve()
    spec = importlib.util.spec_from_file_location(f"jobwatch_user_source_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise PluginError(f"cannot load plugin file {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for attr in ("NAME", "VERSION", "FIELDS", "collect"):
        if not hasattr(module, attr):
            raise PluginError(f"plugin {path.name} missing {attr}")
    return module


def collect(cfg: CollectorContext, since=None):
    folder = _plugin_dir()
    config_path = folder / "sources.yaml"
    if not config_path.is_file():
        return []
    with config_path.open() as f:
        doc = yaml.safe_load(f) or {}
    sources = doc.get("sources", []) if isinstance(doc, dict) else []
    out = []
    run_cache = {}
    for source in sources:
        if not isinstance(source, dict) or source.get("enabled", True) is False:
            continue
        name = str(source.get("name") or "unnamed")
        try:
            if source.get("kind") == "declarative":
                opts = source
                http = PluginHTTP(cfg.http, opts, cache=run_cache)
                postings = declarative_plugin(source, http)
            elif source.get("kind") == "python":
                plugin_path = (folder / source["file"]).resolve()
                if folder.resolve() not in plugin_path.parents:
                    raise PluginError("plugin file must stay inside the user source folder")
                module = _load_python(plugin_path)
                if source.get("respect_robots", True) is False and source.get("allow_robots_override") is not True:
                    raise PluginError("respect_robots=false requires allow_robots_override=true")
                http = PluginHTTP(cfg.http, source, cache=run_cache)
                context = PluginContext(http)
                timeout = min(60.0, max(0.1, float(source.get("timeout_seconds", 20))))
                postings = _with_timeout(module.collect, timeout, context, source.get("options", {}))
            elif source.get("kind") == "builtin" and source.get("plugin") == "gradconnection":
                http = PluginHTTP(cfg.http, source, cache=run_cache)
                postings = gradconnection_plugin(source, http)
            elif source.get("kind") == "builtin" and source.get("plugin") == "rss":
                http = PluginHTTP(cfg.http, source, cache=run_cache)
                postings = rss_plugin(source, http)
            elif source.get("kind") == "builtin" and source.get("plugin") in ("atom", "json", "html"):
                http = PluginHTTP(cfg.http, source, cache=run_cache)
                declarative_source = dict(source)
                declarative_source["feed_type"] = source["plugin"]
                postings = declarative_plugin(declarative_source, http)
            else:
                raise PluginError(f"unknown source kind {source.get('kind')!r}")
            postings = _valid(postings, name)
            out.extend(postings)
            cfg.count_raw(len(postings))
            cfg.origins.add(name)
        except Exception as exc:
            cfg.error(name, f"{type(exc).__name__}: {exc}")
    return out[:cfg.limit] if cfg.limit else out
