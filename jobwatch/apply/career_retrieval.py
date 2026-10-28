"""Find the owner's career-record facts that answer a form question, by meaning (owner, 2026-10-12: "some of the
forms that was asked can be retrieved through embeddings").

The record (<data dir>/career/career_master.yaml) is split into short facts that follow GENERATOR-CONTRACT.md:
no bullets left out of the master CV, no stale or retired cover-letter blocks, only skills that are safe to claim, and
never date of birth, street address, nationality, gender or referees. Embeddings run through OmniRoute (paid route).
The answer agent receives only the top facts per question, as the source "career_record", and must quote them.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import yaml

from jobwatch.settings import get as get_setting

from jobwatch.util.openrouter_extras import _cosine, vectors

PER_QUESTION = 4
MIN_SCORE = 0.4  # 2026-10-12: facts with no real answer (salary, 'how did you hear') scored ~0.35
MAX_FACTS = 30
QUERY = ("Instruct: Given a question on a job application form, retrieve the applicant's career facts that answer "
         "it\nQuery: ")
EXPERIENCE_KEYS = ("title", "company", "location", "start_date", "end_date", "is_current", "employment_type",
                   "hours_per_week_avg", "work_mode", "overview", "highlights")
CANDIDATE_KEYS = ("preferred_name", "headline", "languages", "availability", "work_rights_cv_line",
                  "claimable_experience")


def career_dir() -> Path:
    """The person's career folder (CV, letters, examples). JOBWATCH_CAREER_DIR moves only the main user's: one person's
    letters and CV are never used for another (owner: "my own cover letter examples and cv is strictly for my use")."""
    from jobwatch import users
    from jobwatch.apply.paths import data_dir
    own = get_setting("JOBWATCH_CAREER_DIR") if users.current() == users.DEFAULT_USER else ""
    return Path(os.path.expanduser(own)) if own else data_dir() / "career"


def _keep(item: dict, keys) -> dict:
    return {k: item[k] for k in keys if item.get(k) not in (None, "", [], {})}


def career_facts(root: Path | None = None) -> dict[str, str]:
    """{fact_id: short YAML text} from the career record, filtered by the generator contract."""
    try:
        record = yaml.safe_load((Path(root or career_dir()) / "career_master.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    facts: dict[str, dict] = {}
    for item in record.get("experience") or []:
        facts[f"experience.{item.get('id')}"] = {"experience": _keep(item, EXPERIENCE_KEYS)}
    for section in ("education", "projects", "certifications", "checks", "language_tests", "activities"):
        for i, item in enumerate(record.get(section) or []):
            if isinstance(item, dict):
                facts[f"{section}.{item.get('id', i)}"] = {section: {k: v for k, v in item.items()
                                                                       if k not in ("source_doc_keys", "onet_dwas")}}
    for item in record.get("bullet_bank") or []:
        if item.get("include_in_master") is not False and item.get("text_canonical"):
            facts[f"bullet.{item['id']}"] = {"achievement": item["text_canonical"]}
    for item in record.get("cover_letter_blocks") or []:
        if item.get("use") not in ("stale", "retired", "firm_specific_stale") and item.get("text"):
            facts[f"letter_block.{item['id']}"] = {"own_words": item["text"]}
    safe = [s["name"] for s in record.get("skill_bank") or [] if s.get("safe_to_claim") is True and s.get("name")]
    if safe:
        facts["skills.safe_to_claim"] = {"skills": safe}
    rights = record.get("work_rights") or {}
    if rights.get("current") or rights.get("cv_line"):
        facts["work_rights.current"] = {"work_rights": {"current": rights.get("current"), "cv_line": rights.get("cv_line")}}
    candidate = _keep(record.get("candidate") or {}, CANDIDATE_KEYS)
    if candidate:
        facts["candidate.summary"] = {"candidate": candidate}
    return {k: yaml.safe_dump({"fact": k, **v}, sort_keys=False, allow_unicode=True, width=10_000).strip()
            for k, v in facts.items()}


def relevant_facts(questions: list[str], cache_path: Path, root: Path | None = None, config=None) -> str:
    """The career facts closest to these questions, as one source text; "" if embeddings are unavailable."""
    facts = career_facts(root)
    asked = [q.strip() for q in questions if q and q.strip()]
    if not facts or not asked:
        return ""
    conn = sqlite3.connect(cache_path)
    try:
        os.chmod(cache_path, 0o600)
        texts = {f"fact:{k}": v for k, v in facts.items()}
        texts.update({f"question:{q}": QUERY + q for q in asked})
        got = vectors(conn, texts, config)
    finally:
        conn.close()
    if not got:
        return ""
    chosen: list[str] = []
    for q in asked:
        ranked = sorted(facts, key=lambda k: -_cosine(got[f"question:{q}"], got[f"fact:{k}"]))
        chosen.extend(k for k in ranked[:PER_QUESTION]
                      if k not in chosen and _cosine(got[f"question:{q}"], got[f"fact:{k}"]) >= MIN_SCORE)
    return "\n---\n".join(facts[k] for k in chosen[:MAX_FACTS])
