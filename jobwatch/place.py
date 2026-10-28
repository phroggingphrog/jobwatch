"""Where the person is: state, city and timezone, read from their profile (profile.yaml `candidate`).

The app is Australia-only for now, but nothing here assumes Melbourne or Victoria.
  candidate.location  free text, e.g. "Fitzroy, VIC"
  candidate.state     optional, e.g. "VIC" (else taken from candidate.location when it holds a state code or name)
  candidate.timezone  optional, e.g. "Australia/Melbourne" (else the install default `timezone` in config/jobwatch.yaml)
No state known = no area filter (all Australia).
"""
from __future__ import annotations

import re
from zoneinfo import ZoneInfo

STATES = {"VIC": "Victoria", "NSW": "New South Wales", "QLD": "Queensland", "WA": "Western Australia",
          "SA": "South Australia", "TAS": "Tasmania", "ACT": "Australian Capital Territory",
          "NT": "Northern Territory"}
# Last resort only, when neither the profile nor config/jobwatch.yaml names a timezone.
FALLBACK_TIMEZONE = "Australia/Sydney"


def _candidate() -> dict:
    from .apply.render import _candidate as read
    return read()


def location_text() -> str:
    return str(_candidate().get("location") or "").strip()


def person_state() -> str | None:
    cand = _candidate()
    code = str(cand.get("state") or "").strip().upper()
    if code in STATES:
        return code
    text = str(cand.get("location") or "")
    for code, name in STATES.items():
        if re.search(rf"\b{code}\b", text) or re.search(rf"\b{name}\b", text, re.I):
            return code
    return None


def person_city() -> str:
    return location_text().split(",")[0].strip()


def area_pattern() -> re.Pattern | None:
    """Words that mean 'the person's state' (code, name, city); None when the state is unknown."""
    state = person_state()
    if not state:
        return None
    words = [state, STATES[state], person_city()]
    return re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words if w) + r")\b", re.I)


def person_timezone() -> ZoneInfo:
    name = str(_candidate().get("timezone") or "").strip()
    if not name:
        from .config import load_config
        name = str(load_config().settings.get("timezone") or "")
    try:
        return ZoneInfo(name or FALLBACK_TIMEZONE)
    except Exception:  # noqa: BLE001 - bad name in the profile
        return ZoneInfo(FALLBACK_TIMEZONE)
