"""Separate confirmed preferences, restrictions and legal facts without inferring consent."""
from __future__ import annotations

import re
from typing import Any

from .contracts import StrictFrozen


class IntentFact(StrictFrozen):
    section: str
    value: Any
    source_fact_id: str | None = None
    actor: str | None = None


class NormalizedIntent(StrictFrozen):
    preferences: tuple[IntentFact, ...] = ()
    constraints: tuple[IntentFact, ...] = ()
    work_rights: tuple[IntentFact, ...] = ()
    ambiguous: tuple[IntentFact, ...] = ()


def is_exclusive(value: Any) -> bool:
    if isinstance(value, dict):
        return value.get('exclusive') is True
    if not isinstance(value, str):
        return False
    if re.search(r'\bnot\s+(?:only|exclusively)\b', value, re.I):
        return False
    return bool(re.fullmatch(r'\s*(?:(?:only|exclusively)\s+[^.;!?]+|on[- ]site\s+only)[.!]?\s*', value, re.I))


def is_confirmed_constraint(section: str, value: Any) -> bool:
    if isinstance(value, str) and re.search(r'\bnot\s+(?:only|exclusively)\b', value, re.I):
        return False
    if is_exclusive(value):
        return True
    if isinstance(value, str) and re.fullmatch(r'\s*no\s+remote\s+(?:work|jobs?|roles?)\s*[.!]?\s*', value, re.I):
        return section in ('location', 'preference', 'constraint')
    if section != 'constraint':
        return False
    if isinstance(value, dict):
        return any(key in value and value[key] is not None for key in
                   ('max_commute_km', 'max_hours_per_week', 'hours_limit_per_fortnight'))
    if not isinstance(value, str):
        return False
    return bool(re.search(r'\b(?:must|cannot|can\s+not|(?:will\s+)?not\s+\w+\s+more\s+than|no\s+more\s+than|maximum|max(?:imum)?\s+of)\b', value, re.I))


def normalize_intent(facts: list[dict]) -> NormalizedIntent:
    preferences, constraints, rights, ambiguous = [], [], [], []
    for fact in facts:
        if fact.get('basis') != 'evidence' or not fact.get('value'):
            continue
        section = fact.get('section')
        if section not in ('career_focus', 'preference', 'location', 'constraint', 'exclusion', 'work_rights'):
            continue
        item = IntentFact(section=section, value=fact['value'], source_fact_id=fact.get('id'), actor=fact.get('actor'))
        if section == 'work_rights':
            rights.append(item)
        elif section == 'exclusion' or (section in ('preference', 'location', 'constraint') and is_confirmed_constraint(section, item.value)):
            constraints.append(item)
        else:
            preferences.append(item)
            if section == 'constraint':
                ambiguous.append(item)
    return NormalizedIntent(preferences=tuple(preferences), constraints=tuple(constraints),
                            work_rights=tuple(rights), ambiguous=tuple(ambiguous))
