"""CV PDF from career-ops' ATS template (copied, MIT) in the owner's consultancy look.

Port of career-ops build-cv-html.mjs (parsePartial / fillEntry / empty-section stripping) and the
print step of generate-pdf.mjs (headless Chromium, printBackground, preferCSSPageSize), plus a Python
version of career-ops' verify-ats.mjs structural checks. Content comes from a verified draft only.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from .render import CV_ORDERS, CV_PAGES, headline, work_rights

TEMPLATES = Path(__file__).resolve().parent / "careerops_templates"
_BLOCK = re.compile(r"<!--([A-Z][A-Z0-9_]+)-->([\s\S]*?)<!--/\1-->")
_DAY = re.compile(r"\b\d{1,2}\s+(?=(January|February|March|April|May|June|July|August|September|October|November|"
                  r"December)\b)")
_WORK_RIGHTS_TEXT = re.compile(r"\b(visa|work rights|subclass 500)\b", re.I)

# Owner picked career-ops' plain ATS template as-is (2026-10-12, "ATS"). Only the two labels
# this repo adds to the experience partial (Role Overview, Key Achievements) need a style.
EXTRA_CSS = """
  .job-label { font-weight: 600; margin: 4px 0 1px 0; }
  .job-overview { line-height: 1.5; }
"""


def _esc(text) -> str:
    return html.escape(str(text or ""), quote=True)


def parse_partial(source: str) -> tuple[str, dict]:
    """career-ops parsePartial: the ENTRY zone minus its conditional-block definitions."""
    zone = re.search(r"<!--ENTRY-->([\s\S]*?)<!--/ENTRY-->", source)
    if not zone:
        raise ValueError("partial without ENTRY zone")
    entry, blocks = zone.group(1), {}
    for m in _BLOCK.finditer(zone.group(1)):
        name, content = m.group(1), m.group(2)
        entry = entry.replace(m.group(0), "")
        if name.endswith("_EMPTY"):
            stem = name[:-6]
            base = f"{stem}_BLOCK" if f"<!--{stem}_BLOCK-->" in source else stem
            blocks.setdefault(base, {"present": "", "absent": ""})["absent"] = content
        else:
            blocks.setdefault(name, {"present": "", "absent": ""})["present"] = content
    return entry.strip(), blocks


def fill_entry(entry: str, blocks: dict, fields: dict, block_values: dict | None = None) -> str:
    """career-ops fillEntry: resolve conditional blocks, then scalar placeholders (values pre-escaped)."""
    out = entry
    for name, (value, present) in (block_values or {}).items():
        block = blocks.get(name)
        if block is None:
            continue
        scalar = name[:-6] if name.endswith("_BLOCK") else name
        markup = (re.sub(r"\{\{(" + name + "|" + scalar + r")\}\}", lambda _: value, block["present"])
                  if present else block["absent"])
        out = re.sub(r"\{\{" + name + r"\}\}", lambda _: markup, out)
    for key, value in fields.items():
        out = re.sub(r"\{\{" + key + r"\}\}", lambda _, v=value: v, out)
    return out


def _partial(name: str) -> tuple[str, dict]:
    return parse_partial((TEMPLATES / "sections" / f"{name}.html").read_text(encoding="utf-8"))


def _text(claims) -> list[str]:
    return [c.get("text", "").strip() for c in claims or [] if isinstance(c, dict) and c.get("text", "").strip()]


def _lis(items: list[str]) -> str:
    return "".join(f"<li>{_esc(i)}</li>" for i in items)


def _role(ids: list, ev: dict) -> dict:
    first = ids[0] if ids else ""
    if first.startswith("pf.experience."):
        group = first.rsplit(".", 1)[0]
        get = lambda field: (ev.get(f"{group}.{field}") or {}).get("text", "").strip()
        return {"role": get("title"), "company": get("company"), "location": get("location"),
                "period": _DAY.sub("", get("period"))}
    texts = [(ev.get(i) or {}).get("text", "").strip() for i in ids]
    head = texts[0] if texts else ""
    title, _, company = head.rpartition(", ") if ", " in head else (head, "", "")  # CV line "TITLE, Company"
    meta = [part.strip() for part in (texts[1] if len(texts) > 1 else "").split("|")]
    period = next((m for m in meta if re.search(r"\d{4}", m)), "")
    location = next((m for m in meta if m and m != period), "")
    return {"role": title, "company": company, "location": location, "period": _DAY.sub("", period)}


def _experience(blocks: list, ev: dict) -> list[dict]:
    """One entry per employer, like the consultancy CV (e.g. two seasonal contracts: one entry, both periods)."""
    merged: list[dict] = []
    for block in blocks or []:
        role = _role(block.get("role_ids") or [], ev)
        entry = {**role, "overview": _text(block.get("overview")), "bullets": _text(block.get("bullets")),
                 "achievements": _text(block.get("achievements"))}
        last = merged[-1] if merged else None
        if last and role["company"] and last["company"] == role["company"]:
            if role["role"] and role["role"] not in last["role"].split(" / "):
                last["role"] = f"{last['role']} / {role['role']}"
            if role["period"] and role["period"] not in last["period"]:
                last["period"] = f"{last['period']} | {role['period']}"
            for part in ("overview", "bullets", "achievements"):
                last[part] += [t for t in entry[part] if t not in last[part]]
        else:
            merged.append(entry)
    return merged


def _education(blocks: list, ev: dict) -> list[dict]:
    out = []
    for block in blocks or []:
        ids = block.get("entry_ids") or []
        first = ids[0] if ids else ""
        group = first.rsplit(".", 1)[0] if first.startswith("pf.education.") else ""
        get = lambda field: (ev.get(f"{group}.{field}") or {}).get("text", "").strip() if group else ""
        title = get("degree") or (ev.get(first) or {}).get("text", "")
        out.append({"title": title, "org": get("institution"), "year": get("status") or
                    ((ev.get(ids[1]) or {}).get("text", "") if len(ids) > 1 else ""),
                    "desc": "; ".join(_text(block.get("bullets")))})
    return out


def _contact(line: str) -> dict:
    parts = [p.strip() for p in line.split("|")]
    email = next((p for p in parts if "@" in p), "")
    phone = next((p for p in parts if re.fullmatch(r"[+\d][\d ()-]{6,}", p)), "")
    link = next((p for p in parts if "linkedin" in p.lower()), "")
    location = next((p for p in parts if p not in (email, phone, link)), "")
    return {"email": email, "phone": phone, "location": location,
            "linkedin": link if link.startswith("http") else (f"https://{link}" if link else ""),
            "linkedin_display": link.replace("https://", "").replace("www.", "")}


def _strip_section(page: str, placeholder: str) -> str:
    """Drop a whole section (title included) whose content is empty, as career-ops does."""
    at = page.find("{{" + placeholder + "}}")
    if at < 0:
        return page
    start = page.rfind('<div class="section">', 0, at)
    end = page.find("\n  </div>\n", at)
    return page[:start] + page[end + len("\n  </div>\n"):] if start >= 0 and end >= 0 else page


def _ordered_sections(page: str, cv_tpl: str) -> str:
    """Use the same supported section order as the markdown renderer."""
    blocks = list(re.finditer(r'  <div class="section">\n.*?\n  </div>', page, re.S))
    if not blocks:
        return page
    names = {'summary': 'SUMMARY', 'skills': 'COMPETENCIES', 'experience': 'EXPERIENCE',
             'education': 'EDUCATION', 'certifications': 'CERTIFICATIONS', 'additional': 'SKILLS'}
    by_name = {}
    for block in blocks:
        name = re.search(r'\{\{SECTION_([A-Z]+)\}\}', block.group())
        if name:
            by_name[name.group(1)] = block.group()
    order = [names[key] for key in CV_ORDERS[cv_tpl]]
    ordered = [by_name[name] for name in order if name in by_name]
    ordered += [block for name, block in by_name.items() if name not in order]
    return page[:blocks[0].start()] + '\n\n'.join(ordered) + page[blocks[-1].end():]


def cv_html(content: dict, profile, cv_tpl: str = "cv_consult_default") -> str:
    cv = content.get("cv") or {}
    ev = profile.by_id
    page = (TEMPLATES / "cv-template.ats.html").read_text(encoding="utf-8")
    page = page.replace("</style>", EXTRA_CSS + "\n</style>", 1)
    contact = _contact(profile.header_lines[-1] if profile.header_lines else "")
    sections: dict[str, str] = {}

    entry, blocks = _partial("competencies")
    sections["COMPETENCIES"] = "\n".join(fill_entry(entry, blocks, {"TAG": _esc(t)}) for t in _text(cv.get("skills")))
    entry, blocks = _partial("experience")
    sections["EXPERIENCE"] = "\n".join(fill_entry(entry, blocks, {
        "ROLE": _esc(e["role"]), "COMPANY": _esc(e["company"]), "PERIOD": _esc(e["period"]), "BULLETS": _lis(e["bullets"])},
        {"LOCATION_BLOCK": (_esc(e["location"]), bool(e["location"])),
         "OVERVIEW_BLOCK": (_esc(" ".join(e["overview"])), bool(e["overview"])),
         "ACHIEVEMENTS_BLOCK": (_lis(e["achievements"]), bool(e["achievements"]))})
        for e in _experience(cv.get("experience"), ev))
    entry, blocks = _partial("education")
    sections["EDUCATION"] = "\n".join(fill_entry(entry, blocks, {"TITLE": _esc(e["title"]), "YEAR": _esc(e["year"])},
        {"ORG_BLOCK": (_esc(e["org"]), bool(e["org"])), "LOCATION_BLOCK": ("", False),
         "DESC_BLOCK": (_esc(e["desc"]), bool(e["desc"]))}) for e in _education(cv.get("education"), ev))
    entry, blocks = _partial("certifications")
    sections["CERTIFICATIONS"] = "\n".join(fill_entry(entry, blocks, {"TITLE": _esc(t)},
        {"ORG_BLOCK": ("", False), "YEAR_BLOCK": ("", False)}) for t in _text(cv.get("certifications")))
    entry, blocks = _partial("skills")
    extra = [t for t in _text(cv.get("additional")) if not _WORK_RIGHTS_TEXT.search(t)]
    rows = ([("Work rights", work_rights())] if work_rights() else []) + [("", t) for t in extra]  # GENERATOR-CONTRACT rule 4: the cv_line only
    sections["SKILLS"] = "\n".join(fill_entry(entry, blocks, {"ITEMS_TEXT": _esc(text)},
        {"CATEGORY_BLOCK": (_esc(cat), bool(cat))}) for cat, text in rows)
    sections["PROJECTS"] = sections["AWARDS"] = ""

    summary = " ".join(_text(cv.get("summary")))
    for name, value in [("SUMMARY_TEXT", summary)] + list(sections.items()):
        if not value.strip():
            page = _strip_section(page, name)
    page = _ordered_sections(page, cv_tpl)
    fields = {"LANG": "en-AU", "PAGE_WIDTH": "100%", "NAME": _esc(profile.name),
              "TITLE_BLOCK": f'<div class="header-title">{_esc(headline(cv_tpl))}</div>',
              "PHONE": _esc(contact["phone"]), "EMAIL": _esc(contact["email"]), "LOCATION": _esc(contact["location"]),
              "LINKEDIN_URL": _esc(contact["linkedin"]), "LINKEDIN_DISPLAY": _esc(contact["linkedin_display"]),
              "SECTION_SUMMARY": "Professional Profile", "SECTION_COMPETENCIES": "Core Capabilities",
              "SECTION_EXPERIENCE": "Professional Experience", "SECTION_EDUCATION": "Education",
              "SECTION_CERTIFICATIONS": "Certifications", "SECTION_SKILLS": "Skills, Languages & Work Rights",
              "SECTION_PROJECTS": "Projects", "SECTION_AWARDS": "Awards", "SUMMARY_TEXT": _esc(summary), **sections}
    page = re.sub(r'\s*<a href="\{\{PORTFOLIO_URL\}\}">\{\{PORTFOLIO_DISPLAY\}\}</a>', "", page)
    for key, value in fields.items():
        page = page.replace("{{" + key + "}}", value)
    return page


def html_to_pdf(page_html: str, timeout_ms: int = 60_000) -> bytes:
    """career-ops generate-pdf.mjs print step: Chromium, backgrounds on, the CSS @page is the paper."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(java_script_enabled=False, offline=True)
            pdf_page = context.new_page()
            pdf_page.set_content(page_html, wait_until="load", timeout=timeout_ms)
            return pdf_page.pdf(print_background=True, prefer_css_page_size=True)
        finally:
            browser.close()


def ats_check(page_html: str, pdf_text: str) -> dict:
    """Python port of career-ops verify-ats.mjs structural score (weights sum to 100; A >= 90)."""
    issues, score = [], 0
    checks = [
        (15, len(pdf_text.strip()) >= 300, "no selectable text layer"),
        (20, all(re.search(w, pdf_text, re.I) for w in (r"experience", r"education", r"skills|capabilities")),
         "standard Experience / Education / Skills headings missing"),
        (15, bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", pdf_text)), "contact email not in the body text"),
        (20, not re.search(r"<table\b|column-count|columns\s*:", page_html, re.I), "table or multi-column layout"),
        (10, not re.search(r"<img\b|<svg\b|<canvas\b", page_html, re.I), "text or graphics as images"),
        (10, not re.search(r"@font-face", page_html, re.I), "non-standard web fonts"),
        (5, bool(re.search(r'<meta charset="UTF-8"', page_html, re.I)), "UTF-8 not declared"),
        (5, not re.search(r'style="[^"]*(display\s*:\s*none|color\s*:\s*#?fff(fff)?\b|font-size\s*:\s*0)', page_html, re.I),
         "hidden text"),
    ]
    for weight, ok, problem in checks:
        if ok:
            score += weight
        else:
            issues.append(problem)
    grade = "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "F"
    return {"score": score, "grade": grade, "issues": issues}


def render_cv_pdf(content: dict, profile, cv_tpl: str) -> tuple[bytes, dict]:
    import subprocess
    import tempfile
    page_html = cv_html(content, profile, cv_tpl)
    pdf = html_to_pdf(page_html)
    with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
        handle.write(pdf)
        handle.flush()
        text = subprocess.run(["pdftotext", "-layout", handle.name, "-"], capture_output=True, text=True,
                              timeout=60).stdout
        pages = subprocess.run(["pdfinfo", handle.name], capture_output=True, text=True, timeout=60).stdout
    page_count = int((re.search(r"Pages:\s+(\d+)", pages) or [0, 0])[1])
    return pdf, {"ats": ats_check(page_html, text), "pages": page_count, "max_pages": CV_PAGES[cv_tpl]}
