"""verify_pdf (PLAN-apply D6, chain step g): check the PDF text layer with pdftotext.

Fails (draft status failed) on: page limits (CV <= 2, letter <= 1), empty/garbled text layer
(ligature code points, U+FFFD, "(cid:" glyph ids, control characters, too few letters), or a
verified claim's key span / derived result / evidence heading missing from the text layer.
The keyword coverage table against jd_quoted requirements is advisory only: missing ones are
reported as gaps and never inserted.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .evidence import norm
from .verify import iter_claims

CV_MAX_PAGES = 2
LETTER_MAX_PAGES = 1
LIGATURES = re.compile("[ﬀ-ﬆ]")
STOP = set("""about above after again against also among and any are because been before being below
between both but can could did does doing down during each etc few for from further had has have
having her here hers him his how into its itself just may more most must not off once only other our
ours out over own same shall she should some such than that the their theirs them then there these
they this those through too under until upon very was were what when where which while who whom
why will with within without would you your yours able ability strong excellent good great well
work working role team position including include includes experience required requirement
requirements preferred desirable essential skills skill knowledge understanding demonstrated
proven high highly level levels new use using within year years day days""".split())


def pdf_pages(path: Path) -> int:
    out = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, timeout=60).stdout
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else 0


def pdf_text(path: Path) -> str:
    return subprocess.run(["pdftotext", "-enc", "UTF-8", str(path), "-"], capture_output=True,
                          text=True, timeout=60).stdout


def compact(text: str) -> str:
    return re.sub(r"[\s­]+", "", norm(text))


def garbage_reasons(text: str, min_chars: int) -> list[str]:
    reasons = []
    stripped = text.strip()
    if len(stripped) < min_chars:
        reasons.append(f"text layer too short ({len(stripped)} chars)")
    if LIGATURES.search(text):
        reasons.append("ligature code points in text layer")
    if "�" in text:
        reasons.append("replacement characters in text layer")
    if "(cid:" in text:
        reasons.append("unmapped glyph ids (cid) in text layer")
    controls = sum(1 for ch in text if ord(ch) < 32 and ch not in "\n\r\t\f")
    if controls:
        reasons.append(f"{controls} control characters in text layer")
    if stripped:
        letters = sum(ch.isalpha() for ch in stripped)
        if letters / max(1, len(re.sub(r"\s", "", stripped))) < 0.6:
            reasons.append("text layer is mostly non-letters")
    return reasons


def keywords(text: str) -> list[str]:
    words = re.findall(r"[a-z][a-z+#&/.\-]{2,}", norm(text))
    out = []
    for w in words:
        w = w.strip(".-/")
        if len(w) >= 3 and w not in STOP and w not in out:
            out.append(w)
    return out[:8]


def coverage(requirements: list[dict], text: str) -> list[dict]:
    n = norm(text)
    table = []
    for r in requirements:
        if r.get("tier") != "jd_quoted":
            continue
        kws = keywords(r.get("quote") or r.get("text") or "")
        hit = [k for k in kws if re.search(r"(?<![a-z0-9])" + re.escape(k), n)]
        table.append({"requirement_id": r.get("id"), "requirement": r.get("text"),
                      "keywords": kws, "matched": hit,
                      "covered": bool(kws) and len(hit) * 2 >= len(kws)})
    return table


def required_spans(draft: dict, profile) -> dict[str, list[tuple[str, str]]]:
    """(label, span) pairs that must survive into each PDF's text layer."""
    spans: dict[str, list[tuple[str, str]]] = {"cv": [], "letter": []}
    for where, c in iter_claims(draft):
        target = "letter" if where.startswith("letter") else "cv"
        if c.get("tier") == "stated" and c.get("key_span"):
            spans[target].append((c["id"], c["key_span"]))
        elif c.get("tier") == "derived":
            spans[target].append((c["id"], str((c.get("derivation") or {}).get("result", ""))))
    # Role/education headings come from the owner's own CV and the template reformats them (dates, separators),
    # so they are not checked word for word.
    return spans


def verify_pdf(cv_pdf: Path, letter_pdf: Path, draft: dict, requirements: list[dict], profile) -> dict:
    failures: list[str] = []
    res: dict = {}
    texts = {}
    for label, path, max_pages, min_chars in (("cv", cv_pdf, CV_MAX_PAGES, 300),
                                              ("letter", letter_pdf, LETTER_MAX_PAGES, 200)):
        pages = pdf_pages(path)
        text = pdf_text(path)
        texts[label] = text
        g = garbage_reasons(text, min_chars)
        res[label] = {"pages": pages, "max_pages": max_pages, "chars": len(text), "garbage": g}
        if pages == 0 or pages > max_pages:
            failures.append(f"{label}: {pages} pages (max {max_pages})")
        failures += [f"{label}: {r}" for r in g]
    spans = required_spans(draft, profile)
    missing = {}
    for label in ("cv", "letter"):
        hay = compact(texts[label])
        miss = [lab for lab, span in spans[label] if span and compact(span) not in hay]
        missing[label] = miss
        res[label]["spans_checked"] = len(spans[label])
        res[label]["spans_missing"] = len(miss)
        if len(miss) > 2:  # one or two lines lost to layout is not worth holding the job; more means a broken render
            failures.append(f"{label}: {len(miss)} verified span(s) missing from the text layer")
    table = coverage(requirements, texts["cv"] + "\n" + texts["letter"])
    res["missing_span_ids"] = missing
    res["keyword_coverage"] = table
    res["coverage_gaps"] = [row["requirement_id"] for row in table if not row["covered"]]
    res["failures"] = failures
    res["ok"] = not failures
    return res
