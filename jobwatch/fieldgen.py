"""Generate a person's own searches.yaml + rules.yaml from their profile (TASK-111 child 3).

Same schema as config/searches.yaml and config/rules.yaml; written under users.config_dir().
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from . import users

_ENTRY = ['\\bgraduate\\b', '\\bjunior\\b', '\\btrainee\\b', '\\bentry[- ]level\\b', '\\bintern(ship)?\\b',
          '\\bcadet(ship)?\\b']
# "National" as a location word ("National", "Australia - National"), not a title word ("National Payroll Officer").
# filters.location_rule joins location and title with " | ", which this needs to see where the location ends.
# config/rules.yaml carries the same pattern.
NATIONAL = r"(?:^|[-/,|(]\s*)national(?=\s*(?:$|[-/,|)]))"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _loc(profile: dict) -> str:
    c = profile.get("candidate") or {}
    return str(c.get("location") or profile.get("location") or "").strip()


def generate_config(profile: dict, user: str) -> Path:
    titles = [str(t).strip() for t in profile.get("target_titles") or [] if str(t).strip()]
    avoid = [str(t).strip() for t in profile.get("avoid_titles") or [] if str(t).strip()]
    if not titles:
        raise ValueError("profile has no target_titles")
    loc = _loc(profile)
    city = loc.split(",")[0].strip()
    with users.use(user):
        cdir = users.user_dir() / "config"
    cdir.mkdir(parents=True, exist_ok=True, mode=0o700)

    searches = {
        "location": loc,
        "seek": {"enabled": True, "where": city or "All Australia", "date_range": 2, "max_pages": 2,
                 "page_size": 22, "searches_per_run": 8, "respect_robots": False, "keywords": titles},
        "jobspy": {"enabled": True, "sites": ["linkedin", "indeed", "google"], "location": loc,
                   "hours_old": 6, "results_wanted": 20, "searches_per_run": 4, "pause_seconds": 2,
                   "searches": [{"term": t} for t in titles]},
        "jora": {"enabled": True, "where": city, "age": "24h", "searches_per_run": 4, "delay_s": 4,
                 "keywords": titles},
    }
    arms = [{"id": _slug(t), "anzsco": "", "tier": "core", "keywords": [t.lower()]} for t in titles]
    rules = {
        "arms": arms,
        "location": {
            "vic_patterns": [rf"\b{re.escape(city.lower())}\b"] if city else [],
            "remote_patterns": ["\\bremote\\b", "work from home", "\\bwfh\\b", "anywhere in australia",
                                "australia[- ]wide", NATIONAL] if profile.get("remote_ok") is True else [],
            "allow_unknown_from_vic_employer": False, "other_state_patterns": [],
        },
        "seniority": {
            "exclude_title": [],
            "exclude_title_global": [rf"\b{re.escape(t.lower())}\b" for t in avoid],
            "exempt_phrases": [],
            "exclude_classification": [],
            "exclude_min_years": None,
        },
        "flags": {"experience_flag_min_years": None, "entry_level": _ENTRY, "entry_classification": []},
    }
    for name, doc in (("searches.yaml", searches), ("rules.yaml", rules)):
        (cdir / name).write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return cdir
