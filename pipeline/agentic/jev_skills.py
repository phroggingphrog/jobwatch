"""Jev skills inside the evaluator and writer (owner, 2026-10-12: build 1-3; Jev may see "career facts only").

1. fit_scores: one Jev call scores the career-ops dimensions 1-5 for a job, as a second opinion beside Opus.
2. unsupported_claims: before the Opus reviewer, Jev checks each CV/letter line against the evidence it cites.
3. requirement_map: for each requirement in the ad, embeddings shortlist the owner's evidence and Jev picks the
   fact that best meets it, so the writer can restate that true fact in the ad's own words.

Career facts only: never the owner's name, contact details, visa or work rights, answers or referees. Items that
name them are left out and the name is masked. Every failure returns None / {} and the pipeline runs as before.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from jobwatch.candidate.person import field_phrase
from jobwatch.openrouter_extras import _cosine, _post, extras_settings, vectors

PRIVATE_ID = re.compile(r"work_rights|visa|answers|referee|contact|email|phone|linkedin|candidate\.name|candidate\.location")
PRIVATE_TEXT = re.compile(r"(?i)\bvisa\b|subclass|\b500\b|@|\+?61\s?4|\b04\d{2}\s?\d{3}\s?\d{3}\b|linkedin\.com|"
                          r"citizen|permanent resid|work rights|working rights")
DIMENSIONS = {
    "role_match": "How well does the candidate's background match what this role does (its duties and field)?",
    "level_fit": "How well does the role's seniority match the experience level the candidate's evidence shows?",
    "skills_match": "How much of the ad's required skills and tools does the candidate's evidence show?",
    "hours_fit": "How well do the role's hours suit the candidate's stated availability and work-rights limits?",
    "growth": "How much would this role build the candidate's career in {field}?",
}
LEVELS = ["very poor", "poor", "fair", "good", "excellent"]


def safe_facts(profile, owner_name: str = "") -> dict[str, str]:
    """{evidence_id: text} with private items removed and the owner's name masked."""
    names = [n for n in re.split(r"\s+", owner_name or "") if len(n) > 2]
    out = {}
    for item in profile.evidence:
        text = str(item.get("text") or "").strip()
        if not text or PRIVATE_ID.search(item["id"]) or PRIVATE_TEXT.search(text):
            continue
        for n in names:
            text = re.sub(rf"\b{re.escape(n)}\b", "the candidate", text)
        out[item["id"]] = text[:400]
    return out


def labelled(facts: dict[str, str]) -> dict[str, str]:
    """Give one-line facts their context so Jev can weigh them: 'Work as <job title> at <employer>: ...'."""
    out = {}
    for k, v in facts.items():
        m = re.match(r"pf\.(experience|education|activities)\.(\d+)\.", k)
        if m and m.group(1) == "experience":
            title = facts.get(f"pf.experience.{m.group(2)}.title", "")
            company = facts.get(f"pf.experience.{m.group(2)}.company", "")
            label = f"Work as {title} at {company}".replace(" at ", " at ", 1) if title or company else "Work"
        elif m and m.group(1) == "education":
            label = f"Study ({facts.get(f'pf.education.{m.group(2)}.degree', '')})"
        elif m:
            label = "Activity"
        elif k.startswith("pf.skills."):
            label = "Skill"
        elif k.startswith("pf.projects."):
            label = "Project"
        else:
            label = "CV"
        out[k] = f"{label}: {v}"
    return out


def _facts_block(facts: dict[str, str], limit_chars: int = 40_000) -> str:
    lines, used = [], 0
    for k, v in facts.items():
        line = f"[{k}] {v}"
        if used + len(line) > limit_chars:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


def fit_scores(ad_text: str, facts: dict[str, str], config=None) -> dict | None:
    """{dimension: {"score": 1-5, "confidence": c}, "overall": mean}; None if Jev was not reached."""
    cfg = extras_settings(config)
    questions = {k: {"type": "score", "instructions": q.replace("{field}", field_phrase()), "criteria": LEVELS} for k, q in DIMENSIONS.items()}
    out = _post(cfg, "systemone", {"model": cfg["jev_model"],
                                   "state": {"job_ad": ad_text[:24_000], "candidate_facts": _facts_block(facts, 30_000)},
                                   "questions": questions})
    try:
        scores = {k: {"score": round(1 + float(out["answers"][k]["score"]), 2),  # Jev: expected level 0-4
                      "confidence": round(float(out["answers"][k]["confidence"]), 2)} for k in DIMENSIONS}
    except (TypeError, KeyError, ValueError):
        return None
    scores["overall"] = round(sum(v["score"] for v in scores.values()) / len(DIMENSIONS), 2)
    return scores


def unsupported_claims(claims: list[dict], facts: dict[str, str], config=None, below: float = 0.3) -> set[str] | None:
    """Ids of claims whose cited (shareable) evidence does not support them. Claims citing only private
    evidence are not sent and are never dropped here (code checks them)."""
    cfg = extras_settings(config)
    checkable = [c for c in claims if c.get("id") and any(e in facts for e in c.get("evidence_ids") or [])]
    dropped: set[str] = set()
    for start in range(0, len(checkable), 25):
        chunk = checkable[start:start + 25]
        state = {f"c{i}": {"claim": str(c.get("text") or "")[:600],
                           "evidence": [facts[e] for e in c.get("evidence_ids") or [] if e in facts]}
                 for i, c in enumerate(chunk)}
        questions = {f"c{i}": {"type": "noul",
                               "instructions": f"Is claim c{i} fully supported by its own evidence list (same facts, no "
                                               "added numbers, tools, employers, outcomes or seniority)? Rewording the "
                                               "evidence in a job ad's terms is fine.",
                               "criteria": {"true": "supported by its evidence", "false": "adds or changes facts"}}
                     for i in range(len(chunk))}
        out = _post(cfg, "systemone", {"model": cfg["jev_model"], "state": state, "questions": questions})
        try:
            for i, c in enumerate(chunk):
                if float(out["answers"][f"c{i}"]["noul"]) < below:
                    dropped.add(c["id"])
        except (TypeError, KeyError, ValueError):
            return None
    return dropped


def requirement_map(requirements: list[dict], facts: dict[str, str], cache_path: Path, config=None) -> list[dict]:
    """[{requirement_id, requirement, evidence_id, evidence, meets}] for requirements Jev can map; [] on failure."""
    # Work-rights / visa requirements are about private facts Jev never sees; Opus and the gate handle them.
    reqs = [r for r in requirements if r.get("id") and r.get("text")
            and not re.search(r"(?i)right to work|work(ing)? rights|visa|citizen|permanent resid|clearance|sponsor",
                              r["text"])]
    # Profile summary lines describe the candidate in general; they are not evidence for a requirement.
    facts = labelled({k: v for k, v in facts.items() if not k.startswith("cv.L9.")})
    if not reqs or not facts:
        return []
    conn = sqlite3.connect(cache_path)
    try:
        got = vectors(conn, {**{f"fact:{k}": v for k, v in facts.items()},
                             **{f"req:{r['text'][:500]}": "Instruct: Given a job requirement, retrieve the candidate "
                                                           "fact that shows it\nQuery: " + r["text"][:500] for r in reqs}},
                      config)
    finally:
        conn.close()
    if not got:
        return []
    cfg = extras_settings(config)
    questions, shortlists = {}, {}
    for i, r in enumerate(reqs[:30]):
        q = got[f"req:{r['text'][:500]}"]
        short = sorted(facts, key=lambda k: -_cosine(q, got[f"fact:{k}"]))[:5]
        shortlists[f"r{i}"] = short
        questions[f"r{i}"] = {"type": "choice", "instructions": f"Which candidate fact is the most direct proof "
                              f"of this job requirement: {r['text'][:300]!r}? Prefer work or study that shows it.",
                              "criteria": {**{f"e{j}": facts[k][:200] for j, k in enumerate(short)},
                                           "none": "none of these shows it"}}
        questions[f"m{i}"] = {"type": "noul", "instructions": f"Taken together, do these facts fully meet the "
                              f"requirement {r['text'][:300]!r}? Facts: " + " | ".join(facts[k][:160] for k in short),
                              "criteria": {"true": "fully met", "false": "partly met or not met"}}
    out = _post(cfg, "systemone", {"model": cfg["jev_model"], "state": {"task": "match job requirements to "
                                   "candidate facts"}, "questions": questions})
    mapped = []
    try:
        for i, r in enumerate(reqs[:30]):
            pick = out["answers"][f"r{i}"]
            # Several true facts often fit one requirement, so confidence is split; 0.3 still means a clear pick.
            if pick["choice"] == "none" or float(pick["confidence"]) < 0.3:
                continue
            k = shortlists[f"r{i}"][int(pick["choice"][1:])]
            mapped.append({"requirement_id": r["id"], "requirement": r["text"][:300], "evidence_id": k,
                           "evidence": facts[k], "meets": "fully" if float(out["answers"][f"m{i}"]["noul"]) >= 0.5
                           else "partly"})
    except (TypeError, KeyError, ValueError):
        return []
    return mapped


def save(conn: sqlite3.Connection, posting_id: int, ad_hash: str, kind: str, value) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS jev_judgments (posting_id INTEGER NOT NULL, ad_hash TEXT NOT NULL, "
                 "kind TEXT NOT NULL, value_json TEXT NOT NULL, at TEXT NOT NULL DEFAULT (datetime('now')), "
                 "PRIMARY KEY (posting_id, ad_hash, kind))")
    conn.execute("INSERT OR REPLACE INTO jev_judgments(posting_id,ad_hash,kind,value_json) VALUES (?,?,?,?)",
                 (posting_id, ad_hash, kind, json.dumps(value)))
    conn.commit()


def latest(conn: sqlite3.Connection, posting_id: int, kind: str):
    try:
        row = conn.execute("SELECT value_json FROM jev_judgments WHERE posting_id=? AND kind=? ORDER BY at DESC "
                           "LIMIT 1", (posting_id, kind)).fetchone()
    except sqlite3.OperationalError:
        return None
    return json.loads(row[0]) if row else None
