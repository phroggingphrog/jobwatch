"""Approved exact-date tenure only; occupation labels never establish qualification."""
from __future__ import annotations
from datetime import date, datetime
import re
from jobwatch.candidate.contracts import canonicalize_family


def _exact_date(value):
    if type(value) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def candidate_years(approved, *, family=None, as_of=None):
    """Union exact approved role intervals; Present ends at confirmation, never today.

    Profile facts may contain start_date/end_date dictionaries or verbatim ISO date
    ranges. Any relevant role with inexact dates makes total tenure unknown. A scoped request
    accepts only an explicit matching role_family, never a guessed title mapping.
    This describes observed tenure, not proof of years in a specialist requirement.
    """
    if not isinstance(approved, dict):
        return None
    confirmed = approved.get('confirmed_at')
    try:
        pinned = datetime.fromisoformat(confirmed.replace('Z', '+00:00')).date() if type(confirmed) is str else None
    except ValueError:
        pinned = None
    # An explicit as_of is permitted only when identical to the approved date.
    if as_of is not None and as_of != pinned:
        return None
    spans = []
    for fact in approved.get('facts', []):
        if not isinstance(fact, dict) or fact.get('section') != 'experience' or fact.get('basis') != 'evidence':
            continue
        value = fact.get('value')
        if isinstance(value, dict):
            scope = value.get('role_family')
            if family is not None and (not isinstance(scope, str) or canonicalize_family(scope) != canonicalize_family(family)):
                continue
            start, end = value.get('start_date'), value.get('end_date')
        elif type(value) is str and family is None:
            match = re.search(r'(?<![\d-])(\d{4}-\d{2}-\d{2})\s*(?:–|—|\s-\s|\bto\b)\s*(\d{4}-\d{2}-\d{2}|Present|current|ongoing|now)(?![\w-])', value, re.I)
            if not match:
                return None
            start, end = match.groups()
        else:
            return None
        start = _exact_date(start)
        end = pinned if isinstance(end, str) and end.casefold() in ('present', 'current', 'ongoing', 'now') else _exact_date(end)
        if start is None or end is None or start >= end or (pinned is not None and end > pinned):
            return None
        spans.append((start, end))
    if not spans:
        return None
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return round(sum((end-start).days for start, end in merged)/365.2425, 4)
