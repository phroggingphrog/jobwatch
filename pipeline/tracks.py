"""Title tracks for the screened mode: which kind of job a posting is, from its title alone, before any fetch.

    undergraduate  graduate, internship, vacation, cadet, undergraduate programs: full-time is fine, hours never hide them
    primary        the person's career targets
    secondary      side jobs for income: listed, never scored as a career fit, never promoted to the agent
    drop           clearly unrelated: archived with no fetch and no model
    None           unclear: read once by the model like before

The phrase lists are personal and live in the person's private config (pipeline.screened.tracks). Only the generic
program words below ship with the code. Undergraduate is checked first, so "Graduate Chef" is a program, not a side job.
"""
from __future__ import annotations

import re

ORDER = ("undergraduate", "primary", "secondary", "drop")
PROGRAM_WORDS = ("graduate", "grad program", "internship", "intern", "vacation", "summer clerk", "cadet", "cadetship",
                 "undergraduate", "undergrad", "student", "trainee", "traineeship")
# hold/exclude reasons that come from hours; a program job is shown with a note instead of being hidden
HOURS_REASONS = frozenset({"hours_exceeded", "advertised_hours", "full_time_only"})


def settings(config) -> dict[str, tuple[str, ...]]:
    own = ((((config.settings or {}).get("pipeline") or {}).get("screened") or {}).get("tracks") or {}) if config else {}
    out = {k: tuple(str(x).casefold().strip() for x in (own.get(k) or ()) if str(x).strip()) for k in ORDER}
    out["undergraduate"] = tuple(dict.fromkeys(PROGRAM_WORDS + out["undergraduate"]))
    return out


def _hit(title: str, phrases) -> bool:
    return any(re.search(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", title) for p in phrases)


def classify(title: str, tracks: dict) -> str | None:
    t = (title or "").casefold()
    for name in ORDER:
        if _hit(t, tracks.get(name, ())):
            return name
    return None
