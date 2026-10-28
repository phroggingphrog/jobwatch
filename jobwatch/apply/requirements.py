"""Posting requirements with provenance tiers (PLAN-apply D5).

tier jd_quoted   the model gives a verbatim quote; code checks it appears in the posting text
                 (whitespace/case-normalised) else the requirement is downgraded to inferred
tier structural  taken from structured posting fields (location, work type, salary, grade);
                 code checks the quote appears in that structured block, else -> inferred
tier inferred    weight capped at INFERRED_MAX_WEIGHT and never a blocker (code + DB CHECK)

Requirements are extracted once per posting and reused (ledger-backed rows).
"""
from __future__ import annotations

import json
import sqlite3

from .. import ledger
from jobwatch.util.llm import LLM
from .evidence import norm

INFERRED_MAX_WEIGHT = 0.3
TIERS = ("jd_quoted", "structural", "inferred")

SYSTEM = """You extract hiring requirements from ONE job posting. Output JSON only:
{"requirements":[{"text": str, "tier": "jd_quoted"|"structural"|"inferred",
  "quote": str|null, "weight": number 0..1, "blocker": bool}]}
Rules:
- jd_quoted: "quote" MUST be copied character-for-character from the POSTING TEXT (a short span,
  3-25 words, no ellipses, no paraphrase). Use this for anything the ad states.
- structural: comes from the STRUCTURED FIELDS block (location, work type, salary, grade);
  "quote" is the exact field value.
- inferred: not stated, only implied by the role. quote null. Never a blocker; weight <= 0.3.
- blocker = a stated must-have (licence, right to work, mandatory qualification, clearance).
- weight = importance to the employer. 8-15 requirements, no duplicates, no candidate facts.
"""


def structured_block(p: sqlite3.Row | dict) -> str:
    get = (lambda k: p[k] if k in p.keys() else None) if hasattr(p, "keys") else p.get
    fields = [("Title", get("title")), ("Company", get("company")), ("Location", get("location")),
              ("State", get("state")), ("Work type", get("work_type")), ("Salary", get("salary_text")),
              ("Remote", "yes" if get("remote") else None)]
    raw = get("raw_json")
    if raw:
        try:
            cls = (json.loads(raw) or {}).get("classification")
            fields.append(("Classification", cls if isinstance(cls, str) else None))
        except (ValueError, AttributeError):
            pass
    return "\n".join(f"{k}: {v}" for k, v in fields if v)


def posting_text(p) -> str:
    desc = p["description"] if "description" in p.keys() else None
    return f"{structured_block(p)}\n\n{desc or ''}".strip()


def full_posting_text(conn: sqlite3.Connection, p) -> str:
    """posting_text with the longest ad body held: the reader's fetched full ad (ad_text) when it is
    longer than the collector's description, which is often a 0-300 character teaser."""
    row = conn.execute("SELECT text FROM ad_text WHERE posting_id=?", (p["id"],)).fetchone()
    desc = (p["description"] if "description" in p.keys() else None) or ""
    if row and len(row[0] or "") > len(desc):
        return f"{structured_block(p)}\n\n{row[0]}".strip()
    return posting_text(p)


def verify_requirements(raw: list[dict], text: str, structured: str) -> list[dict]:
    """Apply the code checks. Returns rows ready for the requirements table."""
    nt, ns = norm(text), norm(structured)
    out, seen = [], set()
    for r in raw or []:
        if not isinstance(r, dict) or not str(r.get("text", "")).strip():
            continue
        req_text = str(r["text"]).strip()[:300]
        if norm(req_text) in seen:
            continue
        seen.add(norm(req_text))
        tier = r.get("tier") if r.get("tier") in TIERS else "inferred"
        quote = (r.get("quote") or "").strip() or None
        try:
            weight = float(r.get("weight", 0.5))
        except (TypeError, ValueError):
            weight = 0.5
        weight = min(max(weight, 0.0), 1.0)
        blocker = bool(r.get("blocker"))
        verified = False
        if tier == "jd_quoted":
            verified = bool(quote) and len(norm(quote)) >= 3 and norm(quote) in nt
        elif tier == "structural":
            verified = bool(quote) and norm(quote) in ns
        if tier in ("jd_quoted", "structural") and not verified:
            tier, quote = "inferred", None          # downgrade: quote not found verbatim
        if tier == "inferred":
            weight, blocker, quote = min(weight, INFERRED_MAX_WEIGHT), False, None
        out.append({"text": req_text, "tier": tier, "quote": quote,
                    "quote_verified": int(verified), "weight": round(weight, 3),
                    "blocker": int(blocker)})
    return out


def get_or_extract(conn: sqlite3.Connection, posting_id: int, llm: LLM, model: str | None = None) -> list[dict]:
    rows = conn.execute("SELECT * FROM requirements WHERE posting_id=? ORDER BY id", (posting_id,)).fetchall()
    if rows:
        return [dict(r) for r in rows]
    p = conn.execute("SELECT * FROM postings WHERE id=?", (posting_id,)).fetchone()
    if p is None:
        raise ValueError(f"posting {posting_id} not found")
    text, structured = full_posting_text(conn, p), structured_block(p)
    from jobwatch.util.model_choice import get_model
    res = llm.chat(model or get_model("reader"), [{"role": "system", "content": SYSTEM},
                           {"role": "user", "content": f"STRUCTURED FIELDS:\n{structured}\n\n"
                                                       f"POSTING TEXT:\n{text}"}])
    reqs = verify_requirements((res.data or {}).get("requirements") or [], text, structured)
    stored = []
    for r in reqs:
        stored.append(ledger.upsert(conn, "drafts", "requirements",
                                    {"posting_id": posting_id, **r}, commit=False))
    conn.commit()
    return stored
