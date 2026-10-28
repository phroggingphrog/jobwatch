"""Deterministic evidence extraction (no LLM) and the read-only profile loader.

Evidence item: {id, kind, text, source_file, line[, group]}
  kind  role | education | skill | achievement | cert
  text  a verbatim span of `source_file` (line = 1-based line where it starts)
  group items that belong together (one job: title line + dates line + bullets)

Sources: master_resume.md (cv), profile.yaml (pf), transferable_skills_taxonomy.yaml (tx).
career_ops_profile.md and interests_and_criteria.yaml are framing/preferences, not evidence.
Contact details (name, email, phone, links) are never evidence items.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .paths import profile_dir

CV_FILE = "master_resume.md"
PROFILE_FILE = "profile.yaml"
TAXONOMY_FILE = "transferable_skills_taxonomy.yaml"
KINDS = ("role", "education", "skill", "achievement", "cert")


def norm(text: str) -> str:
    """Whitespace/case/quote/dash-normalised text for verbatim comparisons."""
    t = (text or "").lower()
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = re.sub(r"[‐-―−]", "-", t)
    t = t.replace(" ", " ")
    t = re.sub(r"[*_`]+", "", t)           # markdown emphasis
    return re.sub(r"\s+", " ", t).strip()


def _section_kind(heading: str) -> str:
    h = heading.lower()
    if any(w in h for w in ("experience", "employment", "work history", "career history")):
        return "experience"
    if "education" in h or "qualification" in h:
        return "education"
    if "cert" in h or "licen" in h:
        return "cert"
    if any(w in h for w in ("skill", "capabilit", "tool", "technical", "software", "language")):
        return "skill"
    if any(w in h for w in ("summary", "profile", "about", "objective")):
        return "summary"
    return "other"


def _strip_md(s: str) -> str:
    s = s.strip()
    if s.startswith("- ") or s.startswith("* "):
        s = s[2:]
    return s.strip().strip("*_").strip()


def _sentences(line: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", line.strip())
    return [p.strip() for p in parts if len(p.strip()) >= 3]


def extract_cv(text: str, source_file: str = CV_FILE) -> list[dict]:
    items: list[dict] = []
    lines = text.splitlines()
    section, kind_of_section, group, role_n = None, "header", None, 0
    pending_meta = False

    def add(kind, txt, line_no, grp=None, suffix=""):
        txt = txt.strip()
        if not txt or not re.search(r"[A-Za-z0-9]", txt):
            return
        if txt not in lines[line_no - 1]:
            return  # not verbatim -> never an evidence item
        item = {"id": f"cv.L{line_no}{suffix}", "kind": kind, "text": txt,
                "source_file": source_file, "line": line_no}
        if grp:
            item["group"] = grp
        items.append(item)

    for i, raw in enumerate(lines, 1):
        s = raw.strip()
        if s.startswith("## "):
            section = s[3:].strip()
            kind_of_section, group, pending_meta = _section_kind(section), None, False
            continue
        if kind_of_section == "header" or not s or s == "---" or s.startswith("<!--"):
            continue
        if s.startswith("### "):
            role_n += 1
            group = f"cv.{kind_of_section}.{role_n}"
            k = {"experience": "role", "education": "education", "cert": "cert"}.get(kind_of_section, "achievement")
            add(k, s[4:], i, group)
            pending_meta = True
            continue
        if pending_meta and s.startswith("*") and s.endswith("*") and len(s) > 2:
            k = {"experience": "role", "education": "education", "cert": "cert"}.get(kind_of_section, "achievement")
            add(k, s.strip("*").strip(), i, group)
            pending_meta = False
            continue
        pending_meta = False
        body = _strip_md(s)
        if kind_of_section == "experience":
            add("achievement" if s.startswith(("- ", "* ")) else "role", body, i, group)
        elif kind_of_section == "education":
            add("education", body, i, group)
        elif kind_of_section == "skill":
            add("skill", body, i)
        elif kind_of_section == "cert":
            for n, part in enumerate([p for p in re.split(r";\s*", body) if p.strip()]):
                add("cert", part, i, None, f".{n}" if ";" in body else "")
        elif kind_of_section == "summary":
            sents = _sentences(body)
            for n, sent in enumerate(sents):
                add("achievement", sent, i, None, f".{n}" if len(sents) > 1 else "")
        else:
            parts = [p for p in re.split(r";\s*", body) if p.strip()]
            for n, part in enumerate(parts):
                add("achievement", part, i, None, f".{n}" if len(parts) > 1 else "")
    return items


# -- YAML sources -------------------------------------------------------------
def _yaml_scalars(text: str):
    """Yield (path tuple, value str, start line 1-based, source slice) for every scalar."""
    root = yaml.compose(text)

    def walk(node, path):
        if isinstance(node, yaml.MappingNode):
            for k, v in node.value:
                yield from walk(v, path + (str(k.value),))
        elif isinstance(node, yaml.SequenceNode):
            for idx, v in enumerate(node.value):
                yield from walk(v, path + (idx,))
        elif isinstance(node, yaml.ScalarNode):
            yield path, str(node.value), node.start_mark.line + 1, \
                text[node.start_mark.index:node.end_mark.index]
    if root is not None:
        yield from walk(root, ())


def _verbatim_ok(value: str, src_slice: str) -> bool:
    return bool(value.strip()) and norm(value) in norm(src_slice.replace('\\"', '"'))


PF_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^experience\.\d+\.(title|company|period|location|employment_type)$"), "role"),
    (re.compile(r"^experience\.\d+\.highlights\.\d+$"), "achievement"),
    (re.compile(r"^activities\.\d+\.(role|organization|period)$"), "role"),
    (re.compile(r"^activities\.\d+\.(highlights|details)\.\d+$"), "achievement"),
    (re.compile(r"^actionable_evidence\.\d+(\.[a-z_]+)?$"), "achievement"),
    (re.compile(r"^certifications\.\d+(\.(name|title|issuer|date|status))?$"), "cert"),
    (re.compile(r"^education\.\d+\.(institution|degree|field_of_study|status|location|study_period)$"), "education"),
    (re.compile(r"^education\.\d+\.current_units\.\d+\.(title|course_code)$"), "education"),
    (re.compile(r"^education\.\d+\.relevant_studies\.\d+(\.[a-z_]+)?$"), "education"),
    (re.compile(r"^skills\.[a-z_]+\.\d+$"), "skill"),
    (re.compile(r"^candidate\.languages\.\d+$"), "skill"),
    (re.compile(r"^candidate\.work_rights\.(visa|work_conditions|eligibility)$"), "cert"),  # owner's VEVO check
]


def extract_profile_yaml(text: str, source_file: str = PROFILE_FILE) -> list[dict]:
    items = []
    for path, value, line, src in _yaml_scalars(text):
        dotted = ".".join(str(p) for p in path)
        kind = next((k for rx, k in PF_RULES if rx.match(dotted)), None)
        if not kind or not _verbatim_ok(value, src) or len(value.strip()) < 2:
            continue
        item = {"id": f"pf.{dotted}", "kind": kind, "text": value.strip(),
                "source_file": source_file, "line": line}
        if path and path[0] in ("experience", "activities", "education", "certifications") \
                and len(path) > 1 and isinstance(path[1], int):
            item["group"] = f"pf.{path[0]}.{path[1]}"
        items.append(item)
    return items


def extract_taxonomy(text: str, source_file: str = TAXONOMY_FILE) -> list[dict]:
    items = []
    doc = yaml.safe_load(text) or {}
    by_path = {path: (value, line, src) for path, value, line, src in _yaml_scalars(text)}
    for top, kind in (("academic_evidence", "skill"), ("industry_and_transferable_evidence", "achievement")):
        for area, entries in (doc.get(top) or {}).items():
            for idx, entry in enumerate(entries or []):
                if not isinstance(entry, dict) or "verbatim_fact" not in entry:
                    continue
                hit = by_path.get((top, area, idx, "verbatim_fact"))
                if not hit or not _verbatim_ok(hit[0], hit[2]):
                    continue
                ident = str(entry.get("id") or f"{area}.{idx}")
                items.append({"id": f"tx.{ident}", "kind": kind, "text": hit[0].strip(),
                              "source_file": source_file, "line": hit[1]})
    return items


def build_evidence(pdir: Path) -> list[dict]:
    items: list[dict] = []
    if (pdir / CV_FILE).is_file():
        items += extract_cv((pdir / CV_FILE).read_text(encoding="utf-8"))
    if (pdir / PROFILE_FILE).is_file():
        items += extract_profile_yaml((pdir / PROFILE_FILE).read_text(encoding="utf-8"))
    if (pdir / TAXONOMY_FILE).is_file():
        items += extract_taxonomy((pdir / TAXONOMY_FILE).read_text(encoding="utf-8"))
    seen, out = set(), []
    for it in items:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        out.append(it)
    return out


def check_evidence(pdir: Path, items: list[dict]) -> list[str]:
    """Every item's text must appear verbatim (normalised) in its source file at/after `line`."""
    problems, cache = [], {}
    for it in items:
        src = cache.setdefault(it["source_file"],
                               (pdir / it["source_file"]).read_text(encoding="utf-8").splitlines())
        tail = "\n".join(src[it["line"] - 1: it["line"] + 30])
        if norm(it["text"]) not in norm(tail) or it["kind"] not in KINDS:
            problems.append(it["id"])
    return problems


# -- read-only loader -----------------------------------------------------------
@dataclass
class Profile:
    dir: Path
    header_lines: list[str]          # CV lines before the first "## " (name, headline, contact)
    name: str
    cv_body: str                     # CV from the first "## " on (no contact details)
    evidence: list[dict]
    by_id: dict = field(default_factory=dict)

    def __post_init__(self):
        self.by_id = {e["id"]: e for e in self.evidence}


def load_profile(pdir: Path | None = None) -> Profile:
    pdir = Path(pdir or profile_dir())
    cv_path = pdir / "cv.md" if (pdir / "cv.md").exists() else pdir / CV_FILE
    cv = cv_path.read_text(encoding="utf-8").splitlines()
    first = next((i for i, l in enumerate(cv) if l.startswith("## ")), len(cv))
    header = [l for l in cv[:first] if l.strip() and l.strip() != "---"]
    name = next((l[2:].strip() for l in header if l.startswith("# ")), "")
    ev_path = pdir / "evidence.yaml"
    evidence = (yaml.safe_load(ev_path.read_text(encoding="utf-8")) or {}).get("items", []) \
        if ev_path.exists() else build_evidence(pdir)
    return Profile(dir=pdir, header_lines=header, name=name, cv_body="\n".join(cv[first:]),
                   evidence=evidence)
