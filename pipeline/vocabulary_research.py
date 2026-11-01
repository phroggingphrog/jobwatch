"""Bounded public-page vocabulary research for a person's confirmed goals.

Only configured public sources and enabled collectors participate. Source text
is untrusted vocabulary, never policy or executable instructions.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from html.parser import HTMLParser
import ipaddress
import socket
from urllib.parse import urlsplit, quote_plus

from . import discovery_vocabulary as store


class _Titles(HTMLParser):
    def __init__(self):
        super().__init__(); self.depth = 0; self.current = []; self.items = []
    def handle_starttag(self, tag, attrs):
        if tag in ('a', 'h1', 'h2', 'h3', 'h4'):
            if self.depth: self.depth += 1
            else: self.depth = 1; self.current = []
        elif self.depth: self.depth += 1
    def handle_endtag(self, tag):
        if self.depth:
            self.depth -= 1
            if not self.depth:
                text = ' '.join(' '.join(self.current).split())
                if text: self.items.append(text)
    def handle_data(self, text):
        if self.depth: self.current.append(text)


def public_url(url, *, resolve=socket.getaddrinfo):
    """Reject local, metadata, credential and rebinding destinations before fetch."""
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('research_source_must_be_public_https')
    addresses = resolve(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('research_source_not_public')
    return url


def page_titles(html):
    parser = _Titles(); parser.feed(html[:250_000])
    return tuple(dict.fromkeys(text for text in parser.items if 1 <= len(text.split()) <= 8 and len(text) <= 160))


def refresh(conn, person, goals, research, fetch_page):
    """Refresh once per goal/source configuration. Failures preserve active data."""
    import hashlib, json
    goal = '\n'.join(goals)
    # Source edits must invalidate the cache as well as goal edits.
    signature = goal + '\n' + hashlib.sha256(json.dumps(research, sort_keys=True).encode()).hexdigest()
    version = store.set_goal(conn, person, signature)
    status = store.status(conn, person)
    if status['active_goal_version'] == version:
        return status
    try:
        suggestions = []
        pages = {}
        for source in research.get('sources', [])[:8]:
            source_id = source['source']
            if source['url'] not in pages: pages[source['url']] = fetch_page(source['url'])
            html = pages[source['url']]
            # User-authored aliases can connect broad goals to terminology from
            # the website; research can never generate negative restrictions.
            words = {word.casefold() for text in [*goals, *source.get('goal_terms', [])] for word in text.split() if len(word) > 2}
            for title in page_titles(html):
                if not words.intersection(title.casefold().split()): continue
                suggestions.append(dict(term=title, source=source_id, url=source['url'],
                    retrieved_at=datetime.now(UTC), goal_version=version))
                if len(suggestions) >= 96: break
        store.activate(conn, person, version, suggestions)
    except Exception as exc:
        store.record_error(conn, person, version, type(exc).__name__ + ': ' + str(exc)[:200])
    return store.status(conn, person)


def overlay(conn, person, config):
    """Append positive terms to enabled sources only; preserve configured queries."""
    searches = deepcopy(config.searches)
    mapping = {'seek': 'keywords', 'jora': 'keywords', 'jobspy': 'searches'}
    for source, key in mapping.items():
        section = searches.get(source)
        if not isinstance(section, dict) or section.get('enabled') is not True: continue
        extra = store.queries(conn, person, source)
        if source == 'jobspy' or 'searches' in section:
            existing = list(section.get('searches', []))
            known = {item.get('term', '').casefold() for item in existing}
            section['searches'] = existing + [dict(term=term) for term in extra if term.casefold() not in known]
        else:
            section[key] = list(dict.fromkeys([*section.get(key, []), *extra]))
    settings = deepcopy(config.settings)
    research = (settings.get('pipeline') or {}).get('discovery_research') or {}
    categories = (((settings.get('pipeline') or {}).get('screened') or {}).get('category_snapshot') or {}).get('categories', [])
    for source in research.get('sources', []):
        # Only a user-selected admitting category can receive researched terms.
        # Research cannot create a new restrictive category or hours exception.
        for category in categories:
            if category['id'] == source.get('category_id') and category['action'] == 'admit':
                category['phrases'] = list(dict.fromkeys([*category.get('phrases', []), *store.queries(conn, person, source['source'])]))
    return replace(config, searches=searches, settings=settings)


def prepare(conn, config, person, goals, *, fetch_page=None):
    research = deepcopy((config.settings.get('pipeline') or {}).get('discovery_research') or {})
    if research.get('enabled') is False or not goals: return config
    if not research.get('sources'):
        # A fixed search service is infrastructure, not fixed career vocabulary.
        # Goals supply the query; existing enabled adapters supply destinations.
        query = quote_plus(' '.join(goals)[:500] + ' job titles careers')
        research['sources'] = [dict(source=source, url='https://html.duckduckgo.com/html/?q='+query)
            for source in ('seek', 'jora', 'jobspy') if config.searches.get(source, {}).get('enabled') is True]
    if fetch_page is None: fetch_page = fetch_public_page
    refresh(conn, person, goals, research, fetch_page)
    return overlay(conn, person, config)


def fetch_public_page(url):
    """Reuse the existing pinned-IP public transport and its TLS verification."""
    from pipeline.agentic.research import SafeFetcher
    return SafeFetcher(max_bytes=250_000, timeout=5).fetch_bytes(url).decode('utf-8', errors='replace')
