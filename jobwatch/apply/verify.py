"""Code claim verifier (PLAN-apply D5, chain step c). Nothing here calls a model.

Draft schema (drafter/reviser output):
{
  "cv": {
    "summary":        [claim],
    "skills":         [claim],
    "experience":     [{"role_ids": [evidence id of the title line, (dates line)], "bullets": [claim]}],
    "education":      [{"entry_ids": [evidence ids], "bullets": [claim]}],
    "certifications": [claim],
    "additional":     [claim]
  },
  "letter": {"paragraphs": [[claim]]},
  "honest_gaps": [{"requirement_id": int, "note": str}]
}
claim = {"id", "text", "evidence_ids": [...], "tier": "stated"|"derived"|"framing",
         "key_span": verbatim span of a cited evidence item that also appears in text,
         "derivation": {"inputs": [ids], "method": "years_between"|"count", "result": str}}

* framing (letter only): no candidate facts; no numbers/dates; every name must come from the
  posting or the profile evidence.
* stated: >=1 existing evidence id; key_span in the claim text and in a cited evidence text.
* derived: inputs cited and existing; the result is recomputed by code (years_between / count).
* every number, year and month in a claim must appear in its cited evidence (derived result
  excepted); every capitalised name must appear in the posting or the evidence.
* role / education headings are rendered from evidence text, never from model text.
Anything failing is removed and listed with a reason.
"""
from __future__ import annotations

import copy
import re
from datetime import datetime

from .evidence import norm

CLAIM_LISTS = ("summary", "skills", "certifications", "additional")
BRANDING = re.compile(r"\b(seek|linkedin|indeed|jobwatch|chatgpt|openai|claude|anthropic|gemini|"
                      r"omniroute|ai[- ]generated|as an ai)\b", re.I)
# Drafting-rule talk leaking into the text ("without claiming prior experience", "the evidence shows").
META = re.compile(r"without claiming|\b(?:not|never|don't|do not) claim|\b(?:the|my|cited) evidence\b|"
                  r"\bhonest gap|\bkey[_ ]span\b", re.I)
NUM = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)*%?")
YEAR = re.compile(r"\b(19|20)\d{2}\b")
MONTHS = ("january february march april june july august september october november december "
          "jan feb mar apr jun jul aug sep sept oct nov dec").split()
NUMBER_WORDS = {w: str(i) for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty".split()) if i >= 2}  # "one of", "zero-based": not counts
NUMBER_WORDS.update({"thirty": "30", "forty": "40", "fifty": "50", "hundred": "100"})
CAP = re.compile(r"\b[A-Z][A-Za-z0-9&'\-]*[A-Za-z0-9]\b|\b[A-Z]\b")
COMMON_CAPS = {"i", "i'm", "i've", "i'd", "i'll", "dear", "hiring", "manager", "kind", "regards",
               "yours", "sincerely", "thank", "thanks", "re", "the", "a", "an", "my", "in", "at",
               "as", "with", "and", "for", "to", "of", "on", "this", "your", "you", "while", "during",
               "through", "across", "since", "over", "having", "these", "those", "both", "each"}


def _numbers(text: str) -> set[str]:
    t = text.lower()
    nums = {n.rstrip("%").replace(",", "") for n in NUM.findall(t)}
    nums |= {NUMBER_WORDS[w] for w in re.findall(r"[a-z]+", t) if w in NUMBER_WORDS}
    return nums


def _months(text: str) -> set[str]:
    return {w[:3] for w in re.findall(r"[a-z]+", text.lower()) if w in MONTHS}


def _caps(text: str) -> set[str]:
    """Capitalised tokens that are not sentence/bullet initial."""
    found = set()
    for sent in re.split(r"(?:[.!?:;]\s+|\n|^)", text):
        words = sent.strip().split()
        for idx, w in enumerate(words):
            w2 = w.strip("()[],\"'*")
            if idx == 0 or not w2:
                continue
            for m in CAP.findall(w2):
                if m.lower() not in COMMON_CAPS:
                    found.add(m)
    return found


def _word_in(token: str, haystack_norm: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(token.lower()) + r"(?![a-z0-9])", haystack_norm) is not None


def _years_between(texts: list[str], now_year: int) -> int | None:
    years = []
    for t in texts:
        years += [int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", t)]
        if re.search(r"\b(present|current|now|ongoing)\b", t, re.I):
            years.append(now_year)
    if len(years) < 2:
        return None
    return max(years) - min(years)


class ClaimVerifier:
    def __init__(self, evidence_by_id: dict, posting_text: str, now_year: int | None = None):
        self.ev = evidence_by_id
        self.posting_norm = norm(posting_text)
        self.posting_sq = re.sub(r"[^a-z0-9]", "", self.posting_norm)  # 'HEXhire' matches the ad's 'HEX Hire'
        self.all_ev_norm = norm(" \n ".join(e["text"] for e in evidence_by_id.values()))
        self.now_year = now_year or datetime.now().year

    def check(self, claim: dict, where: str) -> str | None:
        """Return None if the claim passes, else a reason code."""
        text = str(claim.get("text") or "").strip()
        if not text:
            return "empty"
        tier = claim.get("tier")
        if tier == "inferred":
            return "inferred_claim"
        if tier not in ("stated", "derived", "framing", "prose"):
            return "unknown_tier"
        if BRANDING.search(text):
            return "third_party_branding"
        if META.search(text):
            return "meta_text"
        if tier == "framing":
            if not where.startswith("letter"):
                return "framing_outside_letter"
            # numbers/dates only when the ad itself has them (e.g. "Graduate Accountant - 2027")
            if not (_numbers(text) <= set(_numbers(self.posting_norm)) and _months(text) <= _months(self.posting_norm)):
                return "framing_has_numbers_or_dates"
            for cap in _caps(text):
                if not (_word_in(cap, self.posting_norm) or _word_in(cap, self.all_ev_norm)
                        or re.sub(r"[^a-z0-9]", "", cap.lower()) in self.posting_sq):
                    return "unsupported_name"
            return None
        if tier == "prose":
            # A whole letter paragraph in natural prose (owner 2026-10-20: letters must read human). Checked as a
            # whole: every number and date in it must come from the evidence it cites, any evidence, or the ad.
            if not where.startswith("letter"):
                return "prose_outside_letter"
            ids = [i for i in (claim.get("evidence_ids") or []) if i in self.ev]
            claim["evidence_ids"] = ids
            cited = norm(" \n ".join(self.ev[i]["text"] for i in ids))
            pool = f"{cited} \n {self.posting_norm}"
            if not _numbers(text) <= set(_numbers(pool)) | set(_numbers(self.all_ev_norm)):
                return "number_not_in_evidence"
            if not _months(text) <= _months(pool) | _months(self.all_ev_norm):
                return "date_not_in_evidence"
            # No capitalised-word check here: it blocked the employer's own names from research and chained the
            # writer to CV wording (2026-10-20). Invented employers/courses are caught by the reviewer's
            # claims_supported gate, which still blocks.
            return None
        ids = [i for i in (claim.get("evidence_ids") or []) if i in self.ev]
        claim["evidence_ids"] = ids
        if not ids:
            return "no_evidence"
        cited_norm = norm(" \n ".join(self.ev[i]["text"] for i in ids))
        allowed_nums = set(_numbers(cited_norm))
        if tier == "stated":
            span = norm(claim.get("key_span") or "")
            if len(span) < 8 or len(span.split()) < 2:     # "the" matches almost any evidence; the prompt asks for 3-8 words
                return "missing_key_span"
            if span not in cited_norm:
                return "key_span_not_in_evidence"
            if span not in norm(text):
                return "key_span_not_in_claim"
        else:  # derived
            d = claim.get("derivation") or {}
            inputs = [i for i in (d.get("inputs") or []) if i in self.ev]
            result = str(d.get("result") or "").strip()
            if not inputs or not set(inputs) <= set(ids) or not result:
                return "derivation_missing_inputs"
            res_nums = _numbers(result)
            if len(res_nums) != 1:
                return "derivation_unverifiable"
            try:
                value = int(float(next(iter(res_nums))))
            except ValueError:                              # "1.2.3": not a number, so not verifiable
                return "derivation_unverifiable"
            method = str(d.get("method") or "")
            if method == "years_between":
                calc = _years_between([self.ev[i]["text"] for i in inputs], self.now_year)
                # whole-year dates can overstate tenure by under a year, never understate it: claim calc or calc-1, not more
                if calc is None or not calc - 1 <= value <= calc:
                    return "derivation_mismatch"
            elif method == "count":
                if value != len(inputs):
                    return "derivation_mismatch"
            else:
                return "derivation_unverifiable"
            if not (_numbers(text) & res_nums):
                return "derivation_result_not_in_claim"
            allowed_nums |= res_nums
        if not _numbers(text) <= allowed_nums:
            return "number_not_in_evidence"
        if not _months(text) <= _months(cited_norm):
            return "date_not_in_evidence"
        for cap in _caps(text):
            if not (_word_in(cap, cited_norm) or _word_in(cap, self.all_ev_norm)
                    or _word_in(cap, self.posting_norm)
                    or re.sub(r"[^a-z0-9]", "", cap.lower()) in self.posting_sq):
                return "unsupported_name"
        return None


def iter_claims(draft: dict):
    """Yield (where, claim) for every claim in a draft."""
    cv = draft.get("cv") or {}
    for sec in CLAIM_LISTS:
        for c in cv.get(sec) or []:
            yield f"cv.{sec}", c
    for n, block in enumerate(cv.get("experience") or []):
        for part in ("overview", "bullets", "achievements"):
            for c in block.get(part) or []:
                yield f"cv.experience.{n}", c
    for n, block in enumerate(cv.get("education") or []):
        for c in block.get("bullets") or []:
            yield f"cv.education.{n}", c
    for n, para in enumerate((draft.get("letter") or {}).get("paragraphs") or []):
        for c in para or []:
            yield f"letter.p{n}", c


def assign_ids(draft: dict) -> dict:
    used = {c.get("id") for _, c in iter_claims(draft) if isinstance(c, dict) and c.get("id")}
    n = 0
    seen = set()
    for _, c in iter_claims(draft):
        if not isinstance(c, dict):
            continue
        if not c.get("id") or c["id"] in seen:
            while f"c{n}" in used or f"c{n}" in seen:
                n += 1
            c["id"] = f"c{n}"
            n += 1
        seen.add(c["id"])
    return draft


def verify_draft(draft: dict, evidence_by_id: dict, posting_text: str, requirement_ids: set,
                 now_year: int | None = None) -> tuple[dict, dict]:
    """Return (clean draft, report). The input is not modified."""
    d = assign_ids(copy.deepcopy(draft or {}))
    v = ClaimVerifier(evidence_by_id, posting_text, now_year)
    removed, kept, seen_text = [], [], set()

    def filt(claims, where):
        out = []
        for c in claims or []:
            if not isinstance(c, dict):
                removed.append({"id": None, "where": where, "reason": "malformed"})
                continue
            reason = v.check(c, where)
            key = norm(c.get("text", ""))
            if reason is None and key in seen_text:
                reason = "duplicate"
            if reason:
                removed.append({"id": c.get("id"), "where": where, "reason": reason,
                                "tier": c.get("tier"), "text": c.get("text")})
            else:
                seen_text.add(key)
                kept.append(c["id"])
                out.append(c)
        return out

    cv = d.setdefault("cv", {})
    for sec in CLAIM_LISTS:
        cv[sec] = filt(cv.get(sec), f"cv.{sec}")
    for sec, id_key, kinds in (("experience", "role_ids", {"role"}), ("education", "entry_ids", {"education"})):
        blocks = []
        for n, block in enumerate(cv.get(sec) or []):
            ids = [i for i in (block.get(id_key) or []) if i in evidence_by_id
                   and evidence_by_id[i]["kind"] in kinds]
            if not ids:
                removed.append({"id": None, "where": f"cv.{sec}.{n}", "reason": "bad_heading_ref",
                                "text": None})
                continue
            kept_block = {id_key: ids[:2], "bullets": filt(block.get("bullets"), f"cv.{sec}.{n}")}
            if sec == "experience":
                for part in ("overview", "achievements"):
                    if block.get(part):
                        kept_block[part] = filt(block.get(part), f"cv.{sec}.{n}")
            blocks.append(kept_block)
        cv[sec] = blocks
    letter = d.setdefault("letter", {})
    letter["paragraphs"] = [p for p in (filt(p, f"letter.p{n}") for n, p in
                                        enumerate(letter.get("paragraphs") or [])) if p]
    gaps = []
    for g in d.get("honest_gaps") or []:
        if isinstance(g, dict) and g.get("requirement_id") in requirement_ids:
            gaps.append({"requirement_id": g["requirement_id"], "note": str(g.get("note") or "")[:300]})
    d["honest_gaps"] = gaps
    tiers: dict[str, int] = {}
    for _, c in iter_claims(d):
        tiers[c["tier"]] = tiers.get(c["tier"], 0) + 1
    by_reason: dict[str, int] = {}
    for r in removed:
        by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + 1
    report = {"ok": bool(kept), "claims_kept": len(kept), "claims_removed": len(removed),
              "removed": removed, "removed_by_reason": by_reason, "tiers": tiers,
              "gaps": len(gaps)}
    return d, report
