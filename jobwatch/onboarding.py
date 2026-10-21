"""Onboarding: turn a person's uploaded documents into their profile files (TASK-111 child 3 / 111.2).

wrangle(docs, user) takes CV, cover-letter and supporting-evidence documents and writes, only inside
that person's own folder: profile.yaml + master_resume.md + cv.md, evidence.yaml (items in the legacy
schema apply/evidence.py reads) and style/examples/ (their own letter samples).

build_profile(cv_text, user) asks the reader model (JOBWATCH_LLM_MODEL, via jobwatch.llm) to
extract a structured profile, writes profile.yaml + master_resume.md + cv.md into that
person's profile dir, and returns (profile dict, open questions as plain strings).
"""
from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

from . import users
from .apply.evidence import build_evidence, check_evidence, norm
from .llm import LLM
from .model_choice import get_model


PROMPT = """You read a CV and extract a job-search profile. Use only what the CV says; never invent.
Return JSON with exactly these keys:
name, headline, email, phone, location (city, state/country), level (one of: student, graduate,
entry, mid, senior), education (list of strings), roles (list of past job titles), skills (list of
strings), work_rights (string, or "" if the CV does not say), target_titles (8-15 job titles this person
should search for, matching their field and level), avoid_titles (job titles in other fields or above
their level that should never match), questions (short plain questions about things the CV did not
say that job applications will need, e.g. work rights, salary, notice period, willingness to relocate;
at most 8)."""


def write_profile_file(user: str, name: str, text: str) -> Path:
    """Write one file into <user>'s profile dir. The only code path that writes profile/ for a
    new person; refuses a name with a path part and any user but the current one."""
    if user != users.current():
        raise PermissionError("profile files can only be written for the current user")
    if name != Path(name).name or name.startswith("."):
        raise ValueError(f"bad profile file name: {name!r}")
    return write_user_file(user, "profile", name, text)


EVIDENCE_PROMPT = """You read a supporting document a job seeker uploaded (diploma, course list,
certificate, project list). Copy out the individual facts a job application could cite. Each fact must be
a short span copied character-for-character from the document; never reword, merge or invent.
Return JSON: {"certifications": [diplomas, degrees, certificates, licences, individual courses or units],
"projects": [projects, achievements, responsibilities]}."""


def write_user_file(user: str, sub: str, name: str, text: str) -> Path:
    """Write one file into <user>/<sub>/ (profile, style/examples). Current user only, plain file names."""
    if user != users.current():
        raise PermissionError("files can only be written for the current user")
    if name != Path(name).name or name.startswith("."):
        raise ValueError(f"bad file name: {name!r}")
    d = users.user_dir(user) / sub
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(tmp, 0o600)
    os.replace(tmp, d / name)
    return d / name


def style_examples(user: str | None = None) -> list[str]:
    """The only place letter samples are read from: the current person's own style/examples/."""
    user = user or users.current()
    if user != users.current():
        raise PermissionError("letter samples are per person")
    d = users.user_dir(user) / "style" / "examples"
    return [p.read_text(encoding="utf-8") for p in sorted(d.glob("*.md"))] if d.is_dir() else []


def wrangle(docs: list[tuple[str, str, str]], user: str, llm: LLM | None = None) -> tuple[dict, list[str]]:
    """docs = [(kind, filename, text)], kind one of cv | letter | evidence."""
    llm = llm or LLM()
    cvs = [t for k, _, t in docs if k == "cv"]
    if not cvs:
        raise ValueError("Please upload at least one CV.")
    if user == users.DEFAULT_USER and (users.user_dir(user) / "profile" / "profile.yaml").exists():
        raise PermissionError("the owner's profile already exists and is not rebuilt from onboarding")
    profile, questions = build_profile("\n\n".join(cvs), user, llm)
    certs: list[str] = []
    projects: list[str] = []
    for kind, _, text in docs:
        if kind != "evidence":
            continue
        res = llm.chat(get_model("reader"), [{"role": "system", "content": EVIDENCE_PROMPT},
                                             {"role": "user", "content": text[:30000]}], json_mode=True)
        data = res.data if isinstance(res.data, dict) else {}
        for key, out in (("certifications", certs), ("projects", projects)):
            for s in data.get(key) or []:
                s = str(s).strip()
                if len(s) >= 2 and norm(s) in norm(text) and s not in out:  # verbatim only
                    out.append(s)
    profile["certifications"], profile["actionable_evidence"] = certs, projects
    write_profile_file(user, "profile.yaml", yaml.safe_dump(profile, sort_keys=False, allow_unicode=True, width=10**6))
    pdir = users.user_dir(user) / "profile"
    items = build_evidence(pdir)
    if check_evidence(pdir, items):
        raise ValueError("evidence check failed: an item is not verbatim in its source file")
    write_profile_file(user, "evidence.yaml", yaml.safe_dump(
        {"version": 1, "generated_at": datetime.now().isoformat(timespec="seconds"),
         "generator": "jobwatch.onboarding.wrangle", "items": items},
        sort_keys=False, allow_unicode=True, width=10**6))
    n = 0
    for kind, filename, text in docs:
        if kind == "letter":
            n += 1
            slug = re.sub(r"[^a-z0-9]+", "-", Path(filename).stem.lower()).strip("-") or "letter"
            write_user_file(user, "style/examples", f"{n:02d}-{slug}.md", text)
    return profile, questions


def build_profile(cv_text: str, user: str, llm: LLM | None = None) -> tuple[dict, list[str]]:
    llm = llm or LLM()
    res = llm.chat(get_model("reader"), [{"role": "system", "content": PROMPT},
                           {"role": "user", "content": cv_text[:30000]}], json_mode=True)
    data = res.data if isinstance(res.data, dict) else {}
    questions = [str(q) for q in (data.pop("questions", None) or []) if str(q).strip()]
    rights = str(data.get("work_rights") or "").strip()    # structured, so work_rights() never meets a bare string
    profile = {"version": 1, "candidate": {k: data.get(k, "") for k in
                                           ("name", "headline", "email", "phone", "location")}
                         | {"work_rights": {"statement": rights} if rights else {}},
               "level": data.get("level") or "entry",
               "education": data.get("education") or [], "roles": data.get("roles") or [],
               "skills": data.get("skills") or [],
               "target_titles": data.get("target_titles") or [],
               "avoid_titles": data.get("avoid_titles") or []}
    write_profile_file(user, "profile.yaml", yaml.safe_dump(profile, sort_keys=False, allow_unicode=True))
    write_profile_file(user, "master_resume.md", cv_text)
    write_profile_file(user, "cv.md", cv_text)
    return profile, questions
