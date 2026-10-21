"""Jev on application forms, labels only (owner, 2026-10-12: "go 1 2 and 3", pattern from browser-use/jev-ultrafast).

Jev sees form-field labels, option labels, button labels and the NAMES of the owner's answers. It never sees an
answer value: Jobwatch's own code types the value. Fields Jev cannot match confidently fall through to the
existing answer agent (OmniRoute), so nothing is guessed. Every failure returns "no match".
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import yaml

from jobwatch.openrouter_extras import _post, extras_settings

MATCH_AT = 0.8
TEXT_TYPES = {"text", "email", "tel", "url", "textarea", "search", "number", "date", ""}
CONTACT = {"contact.full_name": "Full name", "contact.first_name": "First name / given name",
           "contact.last_name": "Last name / surname / family name", "contact.email": "Email address",
           "contact.phone": "Phone / mobile number", "contact.linkedin": "LinkedIn profile URL",
           "contact.suburb": "Suburb / city / location"}


def past_employers(profile_root: Path) -> list[str]:
    """Employers named in the owner's master resume ("### Role, Employer" lines under Professional experience)."""
    try:
        text = (Path(profile_root) / "master_resume.md").read_text(encoding="utf-8")
    except OSError:
        return []
    block = re.search(r"## Professional experience(.*?)(?=\n## )", text, re.S)
    return [m.group(1).strip() for m in re.finditer(r"^### .*?,\s*(.+)$", block.group(1) if block else "", re.M)]


def job_answers(profile_root: Path, job: dict | None) -> dict[str, tuple[str, str]]:
    """Answers worked out from the job itself, never asked (owner 2026-10-19: "this one should use reasoning")."""
    job = job or {}
    out: dict[str, tuple[str, str]] = {}
    company = " ".join(re.sub(r"[^a-z0-9 ]", " ", str(job.get("company") or "").lower()).split())
    if company:
        padded = f" {company} "                         # whole words only: "anz" is not in "manzanita", "cole" not in "coles"
        worked = any(e and (f" {e} " in padded or padded in f" {e} ")
                     for e in (" ".join(re.sub(r"[^a-z0-9 ]", " ", x.lower()).split()) for x in past_employers(profile_root)))
        out["background.previously_worked_for_employer"] = ("Have you worked for this employer before?", "yes" if worked else "no")
    src = str(job.get("source") or "").lower()
    host = (urlparse(str(job.get("url") or "")).hostname or "").lower()
    if "seek" in src or "seek." in host:
        how = "Seek"
    elif "linkedin" in src or "linkedin." in host:
        how = "LinkedIn"
    elif "indeed" in src or "indeed." in host:
        how = "Indeed"
    elif src or host:
        how = "Employer careers site"
    else:
        how = ""
    if how:
        out["misc.how_did_you_hear"] = ("How did you hear about this job?", how)
    return out


def answer_catalog(profile_root: Path, job: dict | None = None) -> dict[str, tuple[str, str]]:
    """{answer_key: (plain label, value)} for every answer the owner has filled in. Values stay in this process."""
    from jobwatch.web.answers_routes import PLAIN
    root = Path(profile_root)
    out: dict[str, tuple[str, str]] = {}
    try:
        cand = (yaml.safe_load((root / "profile.yaml").read_text(encoding="utf-8")) or {}).get("candidate") or {}
    except (OSError, yaml.YAMLError):
        cand = {}
    name = " ".join(str(cand.get("name") or "").split())
    # Owner 2026-10-12: "my first name is two words" -> first name is everything before the surname.
    values = {"contact.full_name": name, "contact.first_name": name.rsplit(" ", 1)[0] if " " in name else name,
              "contact.last_name": name.split(" ")[-1] if " " in name else "",
              "contact.email": str(cand.get("email") or ""), "contact.phone": str(cand.get("phone") or ""),
              "contact.linkedin": str((cand.get("links") or {}).get("linkedin") or ""),
              "contact.suburb": str(cand.get("location") or "")}
    out.update({k: (CONTACT[k], v.strip()) for k, v in values.items() if v.strip()})
    try:
        answers = yaml.safe_load((root / "answers.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        answers = {}
    for section, group in answers.items() if isinstance(answers, dict) else ():
        if not isinstance(group, dict):
            continue  # referees (a list) stay with the answer agent
        for key, value in group.items():
            if isinstance(value, str) and value.strip():
                out[f"{section}.{key}"] = (PLAIN.get(key) or key.replace("_", " ").capitalize(), value.strip())
    out.update(job_answers(root, job))
    return out


def _field_text(field: dict) -> str:
    options = [str(o.get("label") or "")[:60] for o in field.get("options") or []][:12]
    return (f"Form field: {str(field.get('question') or '')[:200]!r} (input type {field.get('type') or 'text'}"
            + (f"; options: {', '.join(options)}" if options else "") + ")")


def jev_match(fields: list[dict], labels: dict[str, str], config=None) -> dict[str, str]:
    """{field_key: answer_key} for fields Jev matches with >= MATCH_AT confidence. Sends labels only."""
    cfg = extras_settings(config)
    criteria = {**{k: v for k, v in labels.items()}, "none": "none of these answers fits; needs a written or other answer"}
    matches: dict[str, str] = {}
    for start in range(0, len(fields), 20):
        chunk = fields[start:start + 20]
        questions = {f"f{i}": {"type": "choice", "criteria": criteria,
                               "instructions": "Which of the applicant's saved answers belongs in this job application "
                                               "form field? " + _field_text(field)}
                     for i, field in enumerate(chunk)}
        out = _post(cfg, "systemone", {"model": cfg["jev_model"], "state": {"form": "job application"},
                                       "questions": questions})
        for i, field in enumerate(chunk):
            try:
                answer = out["answers"][f"f{i}"]
                choice, confidence = answer["choice"], float(answer["confidence"])
            except (TypeError, KeyError, ValueError):
                continue
            if choice in labels and confidence >= MATCH_AT:
                matches[field["key"]] = choice
    return matches


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).casefold()).strip()


def records_for(fields: list[dict], matches: dict[str, str], catalog: dict[str, tuple[str, str]]) -> dict[str, dict]:
    """Owner-verified fill records, typed by code. Choice controls need an option whose label equals the value."""
    records = {}
    for field in fields:
        answer_key = matches.get(field["key"])
        if answer_key not in catalog:
            continue
        value = catalog[answer_key][1]
        options = field.get("options") or []
        if options:
            hits = [o for o in options if _norm(o.get("label") or "") == _norm(value)
                    or _norm(o.get("value") or "") == _norm(value)]
            if len(hits) != 1 or field.get("multiple"):
                continue
            value = str(hits[0].get("value") or hits[0].get("label"))
        elif (field.get("type") or "") not in TEXT_TYPES:
            continue
        maxlength = field.get("maxlength")
        if isinstance(maxlength, int) and len(value) > maxlength:
            continue
        records[field["key"]] = {"value": value, "owner_verified": True, "source": "owner_answer_jev_matched",
                                 "answer_key": answer_key}
    return records


def jev_prefill(fields: list[dict], profile_root: Path, config=None, job: dict | None = None) -> dict[str, dict]:
    catalog = answer_catalog(profile_root, job)
    if not fields or not catalog:
        return {}
    return records_for(fields, jev_match(fields, {k: v[0] for k, v in catalog.items()}, config), catalog)


FINAL_LABEL = re.compile(r"(?i)\b(submit|send|apply|finish|complete|confirm)\b")


def jev_next_button(buttons: list[dict], config=None) -> dict | None:
    """The one button that moves a multi-step application to its next page, by label; never a Submit-like one.
    prepare_next_navigation and _allowed_click still refuse anything that would submit."""
    candidates = [b for b in buttons if b.get("non_submit", True) and b.get("label", "").strip()
                  and not FINAL_LABEL.search(b["label"])]
    if not candidates:
        return None
    cfg = extras_settings(config)
    criteria = {f"b{i}": b["label"].strip()[:80] for i, b in enumerate(candidates)}
    criteria["none"] = "none of these goes to the next page of the application"
    out = _post(cfg, "systemone", {"model": cfg["jev_model"], "state": {"page": "job application form, one step of several"},
                                   "questions": {"next": {"type": "choice", "criteria": criteria,
                                                          "instructions": "Which button moves this job application to "
                                                                          "its next page without submitting it?"}}})
    try:
        choice, confidence = out["answers"]["next"]["choice"], float(out["answers"]["next"]["confidence"])
    except (TypeError, KeyError, ValueError):
        return None
    if choice == "none" or confidence < MATCH_AT:
        return None
    return candidates[int(choice[1:])]
