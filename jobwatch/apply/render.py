"""Draft -> markdown -> HTML -> PDF (chain step f).

Renderer: WeasyPrint (+ python-markdown). Deterministic, offline, uses the system Pango already
on the host, and handles both the CV and the cover letter from the same markdown. rendercv was
considered: its base install has no PDF engine (needs the typst extra) and it has no cover
letter, so it would need a second renderer anyway; reportlab would need a hand-written layout.

Headings for roles/education come from evidence text (never model text). The contact header
is copied verbatim from the profile CV; it is never sent to a model.
Ligatures are disabled so the pdftotext layer stays searchable.
"""
from __future__ import annotations

import re
from datetime import datetime

from .verify import CLAIM_LISTS

SECTION_TITLES = {"summary": "Professional Profile", "skills": "Core Capabilities",
                  "experience": "Professional Experience", "education": "Education & Qualifications",
                  "certifications": "Certifications", "additional": "Additional Information"}
# GENERATOR-CONTRACT §6 pairs: consult (default), compact (1 page), graduate (data / graduate / intern)
CV_ORDERS = {"cv_consult_default": ("summary", "skills", "experience", "education", "certifications", "additional"),
             "cv_compact_1page": ("summary", "experience", "education", "skills", "certifications", "additional"),
             "cv_graduate_2page": ("summary", "education", "skills", "experience", "certifications", "additional")}
CV_PAGES = {"cv_consult_default": 2, "cv_compact_1page": 1, "cv_graduate_2page": 2}
def _candidate() -> dict:
    """The person's own profile (profile.yaml `candidate`): headline and work rights come from there, never from code
    (owner 2026-10-20: the app is per person; another user must not get the owner's visa or headline)."""
    try:
        import yaml
        from .paths import profile_dir
        return (yaml.safe_load((profile_dir() / "profile.yaml").read_text(encoding="utf-8")) or {}).get("candidate") or {}
    except Exception:  # noqa: BLE001 - no profile yet: the CV simply leaves these lines out
        return {}


def headline(cv_tpl: str) -> str:
    """candidate.headlines[<template>] when the person set one for that template, else candidate.headline."""
    cand = _candidate()
    return str(((cand.get("headlines") or {}).get(cv_tpl)) or cand.get("headline") or "").strip()


def work_rights() -> str:
    """candidate.work_rights.cv_line, else visa + work_conditions, as the person wrote them."""
    rights = _candidate().get("work_rights") or {}
    if rights.get("cv_line"):
        return str(rights["cv_line"]).strip()
    parts = [str(rights.get(k) or "").strip().rstrip(".") for k in ("visa", "work_conditions")]
    return ": ".join(p for p in parts if p) + "." if any(parts) else ""


REFEREES = "Professional referees are available upon request."
FONT_STEPS = (10.5, 10.0, 9.5, 9.0)


def pick_templates(posting: dict, reading: dict | None = None) -> tuple[str, str]:
    """Use the person's confirmed template choice; job titles never imply a preference."""
    from pipeline.agentic.writing_guide import templates_for
    return templates_for()



CSS = """
@page {{ size: A4; margin: 15mm 17mm 15mm 17mm; }}
.bar {{ position: fixed; left: -17mm; width: 210mm; height: 4mm; background: #323E4F; }}
.bar.t {{ top: -15mm; }}
.bar.b {{ bottom: -15mm; }}
html {{ font-family: "Carlito", "Calibri", "Liberation Sans Narrow", "Liberation Sans", Arial, sans-serif;
        font-size: {size}pt; line-height: 1.28; color: #111; font-variant-ligatures: none;
        font-feature-settings: "liga" 0, "clig" 0, "dlig" 0; }}
h1 {{ font-family: "Liberation Serif", "Times New Roman", serif; font-size: 19pt; text-align: center;
      text-transform: uppercase; letter-spacing: 0.02em; color: #323E4F; margin: 0 0 3px 0; }}
h1 + p {{ font-family: "URW Gothic", "Century Gothic", sans-serif; text-align: center; text-transform: uppercase;
          letter-spacing: 0.02em; font-size: 0.82em; color: #212121; margin: 0 0 5px 0; }}
h1 + p + p {{ text-align: center; font-size: 0.9em; margin: 0 0 7px 0; padding: 4px 0;
              border-top: 1px solid #C9D1E0; border-bottom: 1px solid #C9D1E0; }}
h2 {{ font-family: "URW Gothic", "Century Gothic", sans-serif; font-size: 0.95em; font-weight: normal;
      text-align: center; background: #E8ECF3; color: #1F3864; margin: 12px 0 6px 0;
      padding: 3px 0; text-transform: uppercase; letter-spacing: 0.02em; }}
h3 {{ font-size: 1.0em; margin: 8px 0 0 0; text-transform: uppercase; }}
h3 + p {{ margin: 0 0 2px 0; text-align: right; font-size: 0.95em; }}
p {{ margin: 2px 0 5px 0; }}
ul {{ margin: 2px 0 4px 0; padding-left: 15px; }}
h2 + ul {{ column-count: 2; column-gap: 24px; }}
li {{ margin: 0 0 1px 0; }}
em {{ font-style: normal; color: #222; }}
.letter {{ font-family: "URW Gothic", "Century Gothic", sans-serif; font-size: 10.5pt; line-height: 1.45; }}
.letter p {{ margin: 0 0 10px 0; }}
.letter h1 + p + p {{ margin-bottom: 14px; }}
"""


def _md_escape(text: str) -> str:
    return text.replace("\n", " ").strip()


def _header_md(profile, cv_tpl: str = "cv_consult_default") -> str:
    """Name, template headline (never Customer Service first), contact line copied verbatim from the profile CV."""
    return "\n\n".join([f"# {profile.name}"] + ([f"**{headline(cv_tpl)}**"] if headline(cv_tpl) else [])
                       + [profile.header_lines[-1]])


def _claim_text(c: dict, tagged: bool) -> str:
    t = _md_escape(c["text"])
    return f"[{c['id']}] {t}" if tagged else t


_WORK_RIGHTS_TEXT = re.compile(r"\b(visa|work rights|subclass 500)\b", re.I)
_DAY = re.compile(r"\b\d{1,2}\s+(?=(January|February|March|April|May|June|July|August|September|October|November|December)\b)")
_SIGN_OFF = re.compile(r"^\s*(dear\b|kind regards|regards|yours (sincerely|faithfully)|sincerely)", re.I)


def _role_lines(ids: list, ev: dict) -> tuple[str, str] | None:
    """'TITLE | Company' and 'Location | Month Year – Month Year' like the owner's original CV."""
    first = ids[0] if ids else ""
    if not first.startswith("pf.experience."):
        return None
    group = first.rsplit(".", 1)[0]
    text = lambda field: (ev.get(f"{group}.{field}") or {}).get("text", "").strip()
    title, company = text("title"), text("company")
    if not title:
        return None
    period = _DAY.sub("", text("period"))
    return (f"{title} | {company}" if company else title,
            " | ".join(part for part in (text("location"), period) if part))


def cv_markdown(draft: dict, profile, tagged: bool = False, cv_tpl: str = "cv_consult_default") -> str:
    cv = draft.get("cv") or {}
    ev = profile.by_id
    out: list[str] = [] if tagged else [_header_md(profile, cv_tpl), ""]
    for sec in CV_ORDERS[cv_tpl]:
        if sec in CLAIM_LISTS:
            items = cv.get(sec) or []
            if not items:
                continue
            out.append(f"## {SECTION_TITLES[sec]}")
            out.append("")
            if sec == "additional" and not tagged:
                # the fixed work-rights section below prints the contract's cv_line; never twice
                items = [c for c in items if not _WORK_RIGHTS_TEXT.search(_claim_text(c, False))]
                if not items:
                    out = out[:-2]
                    continue
            if sec == "summary":
                out.append(" ".join(_claim_text(c, tagged) for c in items))
            else:
                out += [f"- {_claim_text(c, tagged)}" for c in items]
            out.append("")
        else:
            blocks = cv.get(sec) or []
            if not blocks:
                continue
            out.append(f"## {SECTION_TITLES[sec]}")
            out.append("")
            key = "role_ids" if sec == "experience" else "entry_ids"
            for b in blocks:
                ids = b.get(key) or []
                role = _role_lines(ids, ev) if sec == "experience" else None
                if role:
                    out.append(f"### {_md_escape(role[0])}")
                    if role[1]:
                        out.append(_md_escape(role[1]))
                else:
                    out.append(f"### {_md_escape(ev[ids[0]]['text'])}")
                    if len(ids) > 1:
                        out.append(f"*{_md_escape(ev[ids[1]]['text'])}*")
                out.append("")
                out += [f"- {_claim_text(c, tagged)}" for c in b.get("bullets") or []]
                out.append("")
    if not tagged:
        if work_rights():
            out += ["## Availability & Work Rights", "", work_rights(), ""]
        out += ["## Referees", "", REFEREES, ""]
    return "\n".join(out).strip() + "\n"


def letter_markdown(draft: dict, profile, posting: dict, tagged: bool = False,
                    today: datetime | None = None, cv_tpl: str = "cv_consult_default") -> str:
    paras = (draft.get("letter") or {}).get("paragraphs") or []
    if not tagged:  # the page prints the greeting and sign-off; drop the writer's own copies
        paras = [[c for c in p if not _SIGN_OFF.match(_claim_text(c, False))] for p in paras]
    body = ["\n" + " ".join(_claim_text(c, tagged) for c in p) for p in paras if p]
    if tagged:
        return "\n".join(body).strip() + "\n"
    from jobwatch.util.place import person_timezone          # the person's own zone (profile, else install default), not always Melbourne
    day = (today or datetime.now(person_timezone())).strftime("%-d/%-m/%Y")
    header = [_header_md(profile, cv_tpl)]
    company = (posting.get("company") or "").strip()
    title = (posting.get("title") or "").strip()
    lines = header + ["", day, "", "Hiring Manager" + (f"  \n{company}" if company else ""), "",
                      f"**Re: Application for {title}**" if title else "", "", f"Dear {company} Hiring Team," if company else "Dear Hiring Manager,"]
    lines += body
    lines += ["", "Kind regards,", "", profile.name]
    return "\n".join(lines).strip() + "\n"


def to_html(md_text: str, size: float, letter: bool = False) -> str:
    import markdown
    body = markdown.markdown(md_text.replace("<", "&lt;"), extensions=["sane_lists"])
    cls = ' class="letter"' if letter else ""
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS.format(size=size)}</style>"
            f"</head><body{cls}><div class='bar t'></div><div class='bar b'></div>{body}</body></html>")


def render_pdf(md_text: str, max_pages: int, letter: bool = False) -> tuple[bytes, dict]:
    """Render, stepping the font size down (layout only, never content) to fit max_pages."""
    from weasyprint import HTML
    info = {}
    pdf = b""
    for size in FONT_STEPS:
        doc = HTML(string=to_html(md_text, size, letter)).render()
        pages = len(doc.pages)
        pdf = doc.write_pdf()
        info = {"font_pt": size, "pages_rendered": pages}
        if pages <= max_pages:
            break
    return pdf, info
