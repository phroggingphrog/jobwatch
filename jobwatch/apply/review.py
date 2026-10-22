"""Drafter, fresh-context reviewer and reviser prompts (chain steps b, d, e).

The reviewer gets ONLY: the two drafts inline (claim-tagged) + two named references (the posting
text and the evidence items the drafts cite). No profile, no requirements, no history. Its
edits are suggestions; it verifies nothing (the code verifier re-runs after revision).
"""
from __future__ import annotations

import json
import re

from ..llm import LLM

from ..settings import get as _setting

REVISER_MODEL = _setting("JOBWATCH_LLM_MODEL", "gpt-4o")  # the model that revises the draft after review
EDIT_KINDS = ("grounding", "style")

SCHEMA_HELP = """Output JSON only, exactly this shape:
{"cv": {"summary": [claim], "skills": [claim],
        "experience": [{"role_ids": ["<evidence id of the job title line>", "<evidence id of its dates line>"],
                        "overview": [claim (1-2 sentences: what the role was)], "bullets": [claim (key responsibilities)],
                        "achievements": [claim (key achievements; may be empty)]}],
        "education": [{"entry_ids": ["<evidence id of the qualification line>", "<evidence id of its dates line>"], "bullets": [claim]}],
        "certifications": [claim], "additional": [claim]},
 "letter": {"paragraphs": [[claim]]},   (each letter paragraph = ONE claim with tier "prose")
 "honest_gaps": [{"requirement_id": <int>, "note": "<why it is not met, plainly>"}]}
claim = {"id": "c<n>", "text": "<sentence or bullet>", "evidence_ids": ["<id>"],
         "tier": "stated" | "derived" | "framing" | "prose",
         (prose = a whole letter paragraph written as natural prose; evidence_ids lists every item it relies on)
         "key_span": "<3-8 words copied EXACTLY from one cited evidence text that ALSO appear EXACTLY in text>",
         "derivation": {"inputs": ["<id>"], "method": "years_between" | "count", "result": "<number>"}  (derived only)}"""

# Stock cover-letter phrases (owner 2026-10-07: "reads like a template"). The drafter is told to avoid
# them; any that survive become style edits for the reviser (stock_edits).
STOCK_PHRASES = (
    r"i am (?:writing to )?(?:apply|applying) for", r"i am writing to express", r"i wish to apply",
    r"i would (?:welcome|appreciate|love) the (?:opportunity|chance)", r"thank you for (?:your )?(?:time|consideration)",
    r"look(?:ing)? forward to hearing", r"bringing (?:my |strong |extensive )?experience",
    r"(?:proven|strong) track record", r"passionate about", r"team player", r"hit the ground running",
    r"i am confident (?:that )?(?:i|my)", r"(?:ideal|perfect) (?:candidate|fit)", r"excited to apply",
    r"detail[- ]oriented", r"results[- ]driven", r"self[- ]starter", r"\bleverag", r"as an? [\w ,&-]{1,40} professional",
    r"i believe i (?:would|will) be", r"(?:make|making) me (?:a|an) (?:strong|excellent|great)",
    r"(?:could|would|will) support your", r"wealth of (?:experience|knowledge)",
    r"thank you for considering", r"\b(?:is|are|was) (?:directly |highly )?relevant to", r"\baligns? (?:well )?with",
    r"provides? a (?:strong |solid )?foundation for")
STOCK_RE = re.compile("|".join(STOCK_PHRASES), re.I)
STOCK_HELP = ('"I am applying for", "I am writing to express", "I would welcome the opportunity", '
              '"thank you for your consideration", "I look forward to hearing", "bringing experience", '
              '"proven track record", "passionate about", "team player", "hit the ground running", '
              '"I am confident that", "ideal candidate", "excited to apply", "detail-oriented", '
              '"results-driven", "self-starter", "leverage", "As a ... professional", "I believe I would be", '
              '"makes me a strong ...", "could support your ...", "wealth of experience", '
              '"thank you for considering", "is relevant to", "aligns with", "provides a foundation for"')

DRAFTER_SYSTEM = f"""You tailor a candidate's CV and write a cover letter for ONE job posting.
Ground truth is the union of three sources only: POSTING, CV (the candidate's own CV text) and
EVIDENCE (atomic verbatim items with ids). Hard rules:
1. Never add a fact. Reorder, select and lightly rephrase the CV only. No new employers, titles,
   dates, numbers, tools, qualifications or achievements. If it is not in EVIDENCE, leave it out.
2. Every factual sentence/bullet is a claim citing >=1 evidence id. tier "stated" = said in the
   evidence; its key_span must be copied character-for-character from a cited evidence text and
   appear unchanged inside the claim text (keep the original wording around numbers and names).
   tier "derived" = computed from stated facts (only years_between or count), with derivation.
3. tier "framing" is allowed ONLY in the letter, for sentences with no candidate facts (e.g. the
   opening line naming the role, the closing). Framing has no numbers or dates.
4. Requirements not met go in honest_gaps (by requirement id). Do not paper over gaps.
5. No keyword stuffing: use a posting term only where a cited evidence item supports it.
6. No third-party branding (job boards, AI tools, this system). Australian English.
7. Experience/education headings are chosen by evidence id only (role_ids / entry_ids); the
   heading text is printed from the evidence, so do not write titles or dates yourself.
8. Respect the supported template's page limit and the letter's one-page PDF limit. Select only
   relevant supported content; no paragraph count, bullet quota or academic emphasis is implied.
9. Follow WRITING PREFERENCES and any candidate-provided samples for voice and presentation only.
   With no confirmed style choice, use neutral factual prose. Explain job-specific supported experience;
   never invent motivation, enthusiasm or a qualification. AD READING is advisory analysis of the ad;
   ANGLE NOTES and preferences are framing, never evidence. Keep ability, career interests and practical
   eligibility separate. No word-choice or structural preference can override evidence requirements.
{SCHEMA_HELP}"""

REVIEWER_SYSTEM = """You are a fresh-context reviewer of a job application draft. You see only the
draft text below and two named references. You do not decide what is true; you point at
sentences whose wording goes beyond what the cited references support (kind "grounding") and at
style problems relative to WRITING PREFERENCES and candidate-provided samples (kind "style").
Without a confirmed style choice, use neutral factual prose. Keep style advice separate from grounding.
Assess relevance to the posting without demanding a fixed letter structure or an enthusiastic voice. Never suggest adding facts, metrics, tools or keywords that are not in
the references. Each draft sentence is tagged [c<n>]; use that id as target ("cv" or "letter"
for whole-document remarks). Output JSON only:
{"edits": [{"kind": "grounding"|"style", "target": "c<n>"|"cv"|"letter",
            "suggestion": "<concrete rewrite or action>", "reason": "<short why>"}]}
At most 12 edits, most important first. Empty list if nothing is worth changing."""

REVISER_SYSTEM = f"""You revise a job application draft (JSON) by applying reviewer edits.
Apply every "grounding" edit (usually by narrowing the wording to what the cited evidence says,
or deleting the claim). Apply a "style" edit only if it adds no fact; otherwise skip it.
Keep claim ids; keep every rule of the original drafting brief (evidence ids, tiers, key_span
copied exactly from a cited evidence text and present in the claim text, no new facts).
Return the full revised draft plus "applied": [edit index], "skipped": [{{"index": n, "why": str}}].
{SCHEMA_HELP}"""


def drafter_messages(posting_text: str, requirements: list[dict], cv_body: str, evidence: list[dict],
                     ad_reading: dict | None = None, angle: str = "",
                     letter_samples: list[str] | None = None) -> list[dict]:
    guide = _writing_guide()
    if guide['preferences'].get('use_style_examples') is not True:
        letter_samples = None
    reqs = [{"id": r["id"], "text": r["text"], "tier": r["tier"], "weight": r["weight"],
             "blocker": bool(r["blocker"])} for r in requirements]
    ev = [{"id": e["id"], "kind": e["kind"], "text": e["text"], **({"group": e["group"]} if e.get("group") else {})}
          for e in evidence]
    user = (f"POSTING:\n{posting_text}\n\nREQUIREMENTS (extracted from the posting):\n"
            f"{json.dumps(reqs, ensure_ascii=False)}\n\n"
            + (f"AD READING:\n{json.dumps(ad_reading, ensure_ascii=False)}\n\n" if ad_reading else "")
            + (f"ANGLE NOTES:\n{angle}\n\n" if angle else "")
            + ("LETTER SAMPLES (the candidate's own past letters; copy their voice, sentence length and "
               "structure only. Never reuse their facts, employers, names or sentences):\n"
               + "\n---\n".join(x[:4000] for x in letter_samples[:3]) + "\n\n" if letter_samples else "")
            + f"CV:\n{cv_body}\n\nEVIDENCE:\n{json.dumps(ev, ensure_ascii=False)}")
    user += "\n\nWRITING PREFERENCES (form only):\n" + json.dumps(guide, ensure_ascii=False)
    return [{"role": "system", "content": DRAFTER_SYSTEM}, {"role": "user", "content": user}]


def reviewer_messages(cv_tagged: str, letter_tagged: str, posting_text: str,
                      cited_evidence: list[dict]) -> list[dict]:
    """The reviewer's entire context. Built from scratch on every call (fresh context)."""
    refs = "\n".join(f"- {e['id']}: {e['text']}" for e in cited_evidence)
    user = (f"DRAFT CV:\n{cv_tagged}\n\nDRAFT COVER LETTER:\n{letter_tagged}\n\n"
            f"REFERENCE \"posting\":\n{posting_text}\n\nREFERENCE \"evidence\" (items the draft cites):\n{refs}")
    user += "\n\nWRITING PREFERENCES (form only):\n" + json.dumps(_writing_guide(), ensure_ascii=False)
    return [{"role": "system", "content": REVIEWER_SYSTEM}, {"role": "user", "content": user}]


def clean_edits(raw, claim_ids: set) -> list[dict]:
    out = []
    for e in (raw or {}).get("edits") or [] if isinstance(raw, dict) else []:
        if not isinstance(e, dict) or e.get("kind") not in EDIT_KINDS:
            continue
        target = str(e.get("target") or "")
        if target not in claim_ids and target not in ("cv", "letter"):
            continue
        out.append({"kind": e["kind"], "target": target,
                    "suggestion": str(e.get("suggestion") or "")[:500],
                    "reason": str(e.get("reason") or "")[:300]})
    return out[:12]


def reviser_messages(draft: dict, edits: list[dict], posting_text: str, evidence: list[dict]) -> list[dict]:
    ev = [{"id": e["id"], "kind": e["kind"], "text": e["text"]} for e in evidence]
    numbered = [{"index": n, **e} for n, e in enumerate(edits)]
    user = (f"POSTING:\n{posting_text}\n\nEVIDENCE:\n{json.dumps(ev, ensure_ascii=False)}\n\n"
            f"DRAFT:\n{json.dumps(draft, ensure_ascii=False)}\n\nEDITS:\n{json.dumps(numbered, ensure_ascii=False)}")
    return [{"role": "system", "content": REVISER_SYSTEM}, {"role": "user", "content": user}]


def _writing_guide() -> dict:
    from pipeline.agentic.writing_guide import writing_guide
    return writing_guide('', '', '')


def _style_options(style_options: dict | None) -> dict:
    return _writing_guide()['preferences'] if style_options is None else style_options


def stock_edits(draft: dict, *, style_options: dict | None = None) -> list[dict]:
    """Code check: a style edit for every letter / CV-summary claim that still uses a stock phrase,
    plus one whole-letter edit when most letter sentences open with "I"."""
    options = _style_options(style_options)
    out = []
    claims = [c for p in (draft.get("letter") or {}).get("paragraphs") or [] for c in p or []]
    for c in claims + list((draft.get("cv") or {}).get("summary") or []):
        m = STOCK_RE.search(str(c.get("text") or ""))
        if m and options.get("avoid_stock_phrases") is True:
            out.append({"kind": "style", "target": c["id"],
                        "suggestion": f'Rewrite without the stock phrase "{m.group(0)}"; say the specific thing '
                                      "this posting needs instead, or delete the sentence if it adds nothing.",
                        "reason": "stock phrase (code check)"})
    for c in repeated_claims(claims) if options.get("avoid_repetition") is True else []:
        if c["id"] not in {e["target"] for e in out}:
            out.append({"kind": "style", "target": c["id"],
                        "suggestion": "This repeats a fact already given earlier in the letter; delete it or "
                                      "replace it with a different example.", "reason": "repeated fact (code check)"})
    paras = (draft.get("letter") or {}).get("paragraphs") or []
    if options.get("short_closing") is True and len(paras) >= 2 and any(c.get("tier") != "framing" for c in paras[-1] or []):
        out.append({"kind": "style", "target": "letter",
                    "suggestion": "End with a short closing paragraph of 1-2 plain sentences tied to this role "
                                  "(framing: no new facts, no stock phrases).", "reason": "no closing paragraph (code check)"})
    starts = [str(c.get("text") or "").lstrip().startswith(("I ", "I'")) for c in claims]
    if options.get("vary_openings") is True and len(starts) >= 4 and sum(starts) * 2 > len(starts):
        out.append({"kind": "style", "target": "letter",
                    "suggestion": "Vary sentence openings: lead some sentences with the employer's need or the "
                                  "place/task, not \"I\".", "reason": "most sentences start with I (code check)"})
    return out


def repeated_claims(claims: list[dict]) -> list[dict]:
    """Letter claims that say a fact already said earlier in the letter: same key_span, or every cited
    evidence item was already cited by an earlier claim (catches the same fact in new words)."""
    spans: set[str] = set()
    ids: set[str] = set()
    out = []
    for c in claims:
        span = " ".join(str(c.get("key_span") or "").lower().split())
        ev = set(c.get("evidence_ids") or []) if c.get("tier") in ("stated", "derived") else set()
        if (span and span in spans) or (ev and ev <= ids):
            out.append(c)
        spans.add(span)
        ids |= ev
    return out


def drop_repeats(draft: dict, *, style_options: dict | None = None) -> int:
    """Delete letter claims that repeat an earlier fact (repeated_claims), after revision. Returns the count."""
    if _style_options(style_options).get("avoid_repetition") is not True:
        return 0
    letter = draft.get("letter") or {}
    claims = [c for p in letter.get("paragraphs") or [] for c in p or []]
    rep = {id(c) for c in repeated_claims(claims)}
    if not rep:
        return 0
    letter["paragraphs"] = [k for k in ([c for c in p or [] if id(c) not in rep]
                                        for p in letter.get("paragraphs") or []) if k]
    return len(rep)


def drop_stock_framing(draft: dict, *, style_options: dict | None = None) -> int:
    """Delete letter framing sentences (no candidate facts) that still use a stock phrase after revision.
    Safe because framing carries no evidence; returns how many were dropped."""
    if _style_options(style_options).get("avoid_stock_phrases") is not True:
        return 0
    letter = draft.get("letter") or {}
    dropped, paras = 0, []
    for para in letter.get("paragraphs") or []:
        keep = [c for c in para or [] if not (c.get("tier") == "framing" and STOCK_RE.search(str(c.get("text") or "")))]
        dropped += len(para or []) - len(keep)
        if keep:
            paras.append(keep)
    if dropped:
        letter["paragraphs"] = paras
    return dropped


def run_reviewer(llm: LLM, cv_tagged: str, letter_tagged: str, posting_text: str,
                 cited_evidence: list[dict], claim_ids: set, model: str | None = None) -> list[dict]:
    from ..model_choice import get_model
    res = llm.chat(model or get_model("reviewer"), reviewer_messages(cv_tagged, letter_tagged, posting_text, cited_evidence),
                   max_tokens=4000)
    return clean_edits(res.data, claim_ids)
