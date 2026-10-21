"""The person's own settings, read from their profile dir (profile.yaml, interests_and_criteria.yaml).

Nothing here knows any one person: a missing file or key means neutral behaviour (no hours limit, nothing excluded).
"""
from __future__ import annotations

import re
from typing import Any


def _yaml(name: str) -> dict:
    try:
        import yaml
        from jobwatch.apply.paths import profile_dir
        data = yaml.safe_load((profile_dir() / name).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - no profile yet: neutral behaviour
        return {}


def work_rights() -> dict:
    """profile.yaml candidate.work_rights."""
    return (_yaml("profile.yaml").get("candidate") or {}).get("work_rights") or {}


def hours_limit_per_fortnight() -> float | None:
    """candidate.work_rights.hours_limit_per_fortnight; None = no limit."""
    v = work_rights().get("hours_limit_per_fortnight")
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
