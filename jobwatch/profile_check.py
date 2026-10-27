"""Check the person's own files for misspelled or wrong lines (owner 2026-10-20: "fix it").

Jobwatch reads the person's values from profile.yaml, interests_and_criteria.yaml and the install's settings.env, and
behaves neutrally when a value is missing. That makes a typo silent (a misspelled hours limit means no limit), so this
lists every key it does not know (with the likely intended name), every value of the wrong kind, and the main values
that are missing. It only reads; it never changes a file.
"""
from __future__ import annotations

import difflib
from pathlib import Path

import yaml

from jobwatch.notifier import legacy as _notifier_legacy

# Keys Jobwatch reads. None = any value; a type or tuple of types = the value must be that kind.
PROFILE = {
    "version": None, "updated_at": None, "source_documents": list, "candidate": dict, "skills": dict,
    "experience": list, "activities": list, "actionable_evidence": list, "certifications": list,
    "education": list, "source_conflicts": list,
}
CANDIDATE = {
    "name": str, "headline": str, "headlines": dict, "email": str, "phone": str, "location": str, "state": str,
    "timezone": str, "links": dict, "work_rights": dict, "languages": list, "summary": str, "reply_style": str,
    "education": list,
}
WORK_RIGHTS = {
    "visa": str, "work_conditions": str, "eligibility": str, "source": str, "cv_line": str,
    "hours_limit_per_fortnight": (int, float, type(None)), "full_time_programs_ok": bool,
    "statement": str, "clearances": (list, type(None)),
    **{k: (bool, type(None)) for k in ('citizen', 'permanent_resident', 'citizen_or_pr',
         'valid_work_rights', 'unrestricted_work_rights', 'requires_sponsorship')},
}
INTERESTS = {
    "target_roles": dict, "locations": dict, "compensation": dict, "culture_preferences": dict,
    "tech_preferences": dict, "constraints": list,
}
TARGET_ROLES = {
    "titles": list, "domains": list, "not_wanted": list, "programs_wanted": bool, "excluded_families": list,
}
SETTINGS = {
    "JOBWATCH_PUBLIC_HOST", "JOBWATCH_BOARD_URL", "JOBWATCH_NOTIFY_CMD", "JOBWATCH_DATA_DIR", "JOBWATCH_DB",
    "JOBWATCH_PROFILE_DIR", "JOBWATCH_CAREER_DIR", "JOBWATCH_CONFIG_DIR", "JOBWATCH_DEFAULT_USER",
    "JOBWATCH_EMPLOYERS", "JOBWATCH_LLM_BASE_URL", "JOBWATCH_LLM_MODEL", "JOBWATCH_LLM_API_KEY",
    "JOBWATCH_LLM_KEYS_FILE", "JOBWATCH_LLM_KEY_NAMES", "JOBWATCH_LLM_PI_MODELS", *_notifier_legacy.ENV_NAMES,
    # sign-in and Google (multi-person); GOOGLE_* may also sit in google.env
    "JOBWATCH_SESSION_SECRET", "JOBWATCH_INVITE_CODE", "JOBWATCH_OWNER_PASSWORD", "JOBWATCH_GOOGLE_ENV",
    "JOBWATCH_SETTINGS", "JOBWATCH_AGENT_TOKEN", "JOBWATCH_AGENT_APPROVAL_TOKEN", "JOBWATCH_AGENT_PERSON",
    "JOBWATCH_AGENT_CREDENTIALS_FILE", "JOBWATCH_LIBRECHAT_ENABLED", "JOBWATCH_AGENT_PUBLIC_URL",
    "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI",
}
WANTED = [("candidate.location", "distance and the local area are unknown"),
          ("candidate.work_rights", "work-rights checks and the CV's work-rights line are left out")]


def _suggest(key: str, known) -> str:
    near = difflib.get_close_matches(key, list(known), n=1, cutoff=0.6)
    return f' (did you mean "{near[0]}"?)' if near else ""


def _kind(t) -> str:
    names = {str: "text", int: "a number", float: "a number", bool: "true or false", list: "a list", dict: "a section",
             type(None): "empty"}
    ts = t if isinstance(t, tuple) else (t,)
    return " or ".join(dict.fromkeys(names.get(x, x.__name__) for x in ts))


def _section(data, known: dict, where: str, file: str, out: list) -> None:
    if not isinstance(data, dict):
        return
    for key, value in data.items():
        if key not in known:
            out.append(f'{file}: unknown line "{where}{key}"{_suggest(key, known)}; Jobwatch ignores it.')
            continue
        want = known[key]
        if want is not None and value is not None and not isinstance(value, want) \
                or (want in ((int, float, type(None)),) and isinstance(value, bool)):
            out.append(f'{file}: "{where}{key}" should be {_kind(want)}, not {value!r}.')


def _load(path: Path, out: list) -> dict | None:
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        out.append(f"{path.name}: cannot be read ({str(exc).splitlines()[0]}); Jobwatch treats it as empty.")
        return None
    if not isinstance(data, dict):
        out.append(f"{path.name}: should be a list of named lines, not {type(data).__name__}.")
        return None
    return data


def check(profile_dir: Path | None = None, settings_file: Path | None = None) -> list[str]:
    """Plain-words problems, most important first; [] when everything is known and well formed."""
    from jobwatch.apply.paths import profile_dir as _pd
    import os
    out: list[str] = []
    d = Path(profile_dir or _pd())
    profile = _load(d / "profile.yaml", out)
    if profile is None:
        out.append(f"profile.yaml is missing in {d}: Jobwatch has no profile for you yet.")
    else:
        _section(profile, PROFILE, "", "profile.yaml", out)
        cand = profile.get("candidate") if isinstance(profile.get("candidate"), dict) else {}
        _section(cand, CANDIDATE, "candidate.", "profile.yaml", out)
        _section(cand.get("work_rights"), WORK_RIGHTS, "candidate.work_rights.", "profile.yaml", out)
        for path, effect in WANTED:
            if not cand.get(path.split(".", 1)[1]):
                out.append(f'profile.yaml: "{path}" is empty, so {effect}.')
    interests = _load(d / "interests_and_criteria.yaml", out)
    if interests is not None:
        _section(interests, INTERESTS, "", "interests_and_criteria.yaml", out)
        _section(interests.get("target_roles"), TARGET_ROLES, "target_roles.", "interests_and_criteria.yaml", out)
    sf = Path(settings_file or os.environ.get("JOBWATCH_SETTINGS") or Path.home() / ".config/jobwatch/settings.env")
    if sf.exists() and sf.is_file():
        for n, line in enumerate(sf.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                out.append(f"settings.env line {n}: needs KEY=value.")
                continue
            key = line.split("=", 1)[0].strip()
            if key not in SETTINGS:
                out.append(f'settings.env: unknown setting "{key}"{_suggest(key, SETTINGS)}; Jobwatch ignores it.')
    return out


def _facts(profile: dict) -> set[str]:
    """Distinctive values from the person's own profile: name, headline, suburb, visa line, employers, schools."""
    cand = profile.get("candidate") or {}
    out: set[str] = set()
    for v in (cand.get("name"), cand.get("headline"), (cand.get("work_rights") or {}).get("visa"),
              str(cand.get("location") or "").split(",")[0]):
        if isinstance(v, str) and len(v.strip()) >= 5:
            out.add(v.strip())
    for section, keys in (("experience", ("employer", "company", "organisation", "organization")),
                          ("education", ("institution", "school", "university"))):
        for item in profile.get(section) or []:
            if isinstance(item, dict):
                for k in keys:
                    v = item.get(k)
                    if isinstance(v, str) and len(v.strip()) >= 4:
                        out.add(v.strip())
    return out


def check_code(root: Path | None = None, profile_dir: Path | None = None) -> list[str]:
    """Places where the person's own facts appear in Jobwatch's code or prompts (they belong in their files).
    Reads the facts from this install's profile, so no one's facts are ever written into this check."""
    from jobwatch.apply.paths import profile_dir as _pd
    root = Path(root or Path(__file__).resolve().parents[1])
    data = _load(Path(profile_dir or _pd()) / "profile.yaml", []) or {}
    facts = sorted(_facts(data), key=len, reverse=True)
    if not facts:
        return []
    out = []
    for folder in ("jobwatch", "pipeline"):
        for path in (root / folder).rglob("*"):
            if path.suffix not in (".py", ".html", ".js", ".md", ".yaml") or "/data/" in str(path) or "/static/" in str(path):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            low = text.casefold()
            for fact in facts:
                if fact.casefold() in low:
                    line = low[:low.index(fact.casefold())].count("\n") + 1
                    out.append(f"{path.relative_to(root)}:{line}: contains a value from your profile; move it to your files.")
                    break
    return out
