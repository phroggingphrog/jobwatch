"""Read settings from the server-bound person's approved version.

A person without approval has no settings. Invalid approved files raise an integrity error.
"""
from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)


def _yaml(name: str) -> dict:
    from jobwatch import users
    from . import intake
    from .approved import settings
    # Vocabulary imports can run before onboarding. Assessment still requires approved evidence.
    if intake.current_version(users.current()) is None:
        return {}
    return settings(users.current(), name)

def work_rights() -> dict:
    """profile.yaml candidate.work_rights, always a dict; a legacy string (old onboarding) is a statement with no limits."""
    v = (_yaml("profile.yaml").get("candidate") or {}).get("work_rights") or {}
    if isinstance(v, str):
        return {"statement": v.strip()} if v.strip() else {}
    return v if isinstance(v, dict) else {}


def hours_limit_per_fortnight() -> float | None:
    """candidate.work_rights.hours_limit_per_fortnight; None = no limit."""
    v = work_rights().get("hours_limit_per_fortnight")
    if isinstance(v, str):            # "48" quoted in the YAML is still the person's limit
        try:
            v = float(v.strip())
        except ValueError:
            return None
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None


def full_time_programs_ok() -> bool:
    """candidate.work_rights.full_time_programs_ok: graduate/vacation programs are exempt from the hours limit."""
    return work_rights().get("full_time_programs_ok") is True


def target_roles() -> dict[str, Any]:
    """interests_and_criteria.yaml target_roles."""
    return _yaml("interests_and_criteria.yaml").get("target_roles") or {}


def excluded_families() -> tuple[str, ...]:
    """target_roles.excluded_families: role families the scoring policy never allows (lower case, underscores).
    Separate from target_roles.not_wanted, the plain-words list the AI reader is told; mixing them made the reader
    reject families kept here only so stored run keys stay stable (2026-10-20)."""
    raw = target_roles().get("excluded_families") or []
    if not isinstance(raw, (list, tuple)):
        return ()
    out = []
    for f in raw:
        if isinstance(f, str) and f.strip():
            s = re.sub(r"[\s\-_]+", "_", f.casefold()).strip("_")
            if s and s not in out:
                out.append(s)
    return tuple(out)


def field_phrase() -> str:
    """The person's field for prompts: their target domains, else target titles, else a neutral phrase."""
    t = target_roles()
    for key in ("domains", "titles"):
        v = t.get(key)
        if isinstance(v, (list, tuple)) and v:
            return ", ".join(str(x) for x in v[:4])
    return "chosen field"
