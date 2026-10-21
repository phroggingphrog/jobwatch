"""Approved profile -> the files the existing readers consume (profile.yaml, master_resume.md, interests_and_criteria.yaml).

Pure: approved dict in, {file name: text} out. Only confirmed facts with basis 'evidence' (a document quote or the
person's own statement) are written. Inference and unknown facts stay in approved.json: none of these files has a way
to mark a line as inferred, and a reader would take it for the person's word.
"""
from __future__ import annotations

import re

import yaml

from .contracts import KNOWN_FAMILIES, canonicalize_family

_HOURS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\s*(?:per|a|/|each)\s*(?:fortnight|2 weeks|two weeks)", re.I)
_RIGHTS_TEXT = ("visa", "work_conditions", "eligibility", "cv_line")      # candidate.work_rights keys the readers know


def _facts(approved: dict, *sections: str) -> list[dict]:
    return [f for f in approved.get("facts", ()) if f.get("section") in sections and f.get("basis") == "evidence"
            and f.get("value")]


def _text(value) -> str:
    if isinstance(value, dict):
        value = ", ".join(str(v).strip() for v in value.values() if isinstance(v, (str, int, float)) and str(v).strip())
    return " ".join(str(value).split())


def _uniq(items) -> list[str]:
    return list(dict.fromkeys(i for i in items if i))


def _number(v) -> float | int | None:
    if isinstance(v, str):
        try:
            v = float(v.strip())
        except ValueError:
            return None
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None


def _work_rights(approved: dict) -> dict:
    out: dict = {}
    statements = []
    for f in _facts(approved, "work_rights"):
        v = f["value"]
        if isinstance(v, dict):
            for k in _RIGHTS_TEXT:
                if isinstance(v.get(k), str) and v[k].strip():
                    out.setdefault(k, v[k].strip())
            if isinstance(v.get("full_time_programs_ok"), bool):
                out["full_time_programs_ok"] = v["full_time_programs_ok"]
            if _number(v.get("hours_limit_per_fortnight")) is not None:
                out["hours_limit_per_fortnight"] = _number(v["hours_limit_per_fortnight"])
        else:
            statements.append(_text(v))
            m = _HOURS.search(statements[-1])
            if m and _number(m.group(1)) is not None:
                out.setdefault("hours_limit_per_fortnight", _number(m.group(1)))
    if statements:
        out["statement"] = "; ".join(statements)
    return out


def _line(quote: str) -> str:
    """One resume line that extract_cv reads as plain text: no heading, comment or rule syntax from a quote."""
    s = " ".join(quote.split()).lstrip("#>").strip()
    return "" if s.startswith(("<!--", "---")) else s


def _quotes(fact: dict) -> list[str]:
    # parser facts are written as the document's own words, never the model's paraphrase; a person's own fact is theirs
    got = [_line(s["quote"]) for s in fact.get("sources", ())] if fact.get("sources") else [_line(_text(fact["value"]))]
    return _uniq(got)


def _resume(approved: dict) -> str:
    out = ["# Profile", ""]
    for title, sections, grouped in (("Experience", ("experience",), True), ("Education", ("education",), True),
                                     ("Skills", ("skill", "transferable_skill"), False)):
        body: list[str] = []
        seen: set[str] = set()
        for f in _facts(approved, *sections):
            lines = [q for q in _quotes(f) if q not in seen]
            seen.update(lines)
            if not lines:
                continue
            if grouped:
                body += [f"### {lines[0]}", *[f"- {q}" for q in lines[1:]], ""]
            else:
                body += [f"- {q}" for q in lines]
        if body:
            out += [f"## {title}", "", *body, ""]
    return "\n".join(out).rstrip() + "\n"


def _dump(data: dict) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False, width=10**6)


def project(approved: dict) -> dict[str, str]:
    """File name -> text for an approved profile (see module docstring for what is left out)."""
    rights = _work_rights(approved)
    profile: dict = {"version": 1, "candidate": {"work_rights": rights} if rights else {}}
    exclusions = _uniq(_text(f["value"]) for f in _facts(approved, "exclusion"))
    families = _uniq(canonicalize_family(e) for e in exclusions if canonicalize_family(e) in KNOWN_FAMILIES)
    target = {"titles": _uniq(_text(f["value"]) for f in _facts(approved, "career_focus")),
              "not_wanted": exclusions, "excluded_families": families}
    interests: dict = {"target_roles": target}
    if places := _uniq(_text(f["value"]) for f in _facts(approved, "location")):
        interests["locations"] = {"preferred": places}
    if prefs := _uniq(_text(f["value"]) for f in _facts(approved, "preference")):
        interests["culture_preferences"] = {"stated": prefs}
    limits = _uniq([_text(f["value"]) for f in _facts(approved, "constraint")] +
                   ["Availability: " + _text(f["value"]) for f in _facts(approved, "availability")])
    if limits:
        interests["constraints"] = limits
    return {"profile.yaml": _dump(profile), "master_resume.md": _resume(approved),
            "interests_and_criteria.yaml": _dump(interests)}
