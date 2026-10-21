"""Node 5: document drafting. Wraps the existing draft chain (jobwatch/apply/chain.py: requirements -> drafter ->
code verifier -> fresh reviewer -> reviser -> PDF render -> verify_pdf), then checks its result by code into an
ApplicationPackage. A draft the chain marks failed, missing PDFs or a page count over the limits = a failed attempt.
"""
from __future__ import annotations

import json
from pathlib import Path

from jobwatch import db as dbm
from jobwatch.apply import chain
from jobwatch.models import now_utc

from ..schemas import ApplicationPackage

ACTOR = "pipeline"


def ensure_match(conn, posting_id: int) -> int:
    """The draft chain works on a match. A job the pipeline passed but no keyword arm matched gets one (arm
    'pipeline'), so it also appears on the board."""
    r = conn.execute("SELECT id FROM matches WHERE posting_id=?", (posting_id,)).fetchone()
    if r:
        return r[0]
    cur = conn.execute("INSERT INTO matches(posting_id, arm, arm_tier, arms_json, rules_json, flags_json, matched_at) "
                       "VALUES(?,?,?,?,?,?,?)", (posting_id, "pipeline", "ai", json.dumps(["pipeline"]),
                                                 json.dumps({"gate": "pipeline"}), "[]",
                                                 now_utc().isoformat(timespec="seconds")))
    conn.commit()
    return cur.lastrowid


def run(db_path: str, posting_id: int, llm=None) -> ApplicationPackage:
    """One drafting attempt in its own connection (called from a worker thread). Raises on failure."""
    conn = dbm.connect(db_path)
    try:
        match_id = ensure_match(conn, posting_id)
        app_id = chain.start_draft(conn, match_id, ACTOR, llm=llm)
        d = conn.execute("SELECT * FROM drafts WHERE application_id=? ORDER BY version DESC LIMIT 1",
                         (app_id,)).fetchone()
        if d is None or d["status"] != "ready":
            why = (d["error"] if d is not None else None) or "no draft row"
            raise RuntimeError(f"draft chain did not produce a verified draft: {why[:300]}")
        vdir = Path(d["dir"])
        summary = json.loads((vdir / "summary.json").read_text())
        return ApplicationPackage(application_id=app_id, draft_version=d["version"],
                                  cv_pdf=str(vdir / "cv.pdf"), letter_pdf=str(vdir / "letter.pdf"),
                                  verify_ok=bool(summary.get("verify_ok")) and (vdir / "cv.pdf").is_file()
                                  and (vdir / "letter.pdf").is_file(),
                                  pages_cv=int((summary.get("pages") or {}).get("cv") or 0),
                                  pages_letter=int((summary.get("pages") or {}).get("letter") or 0))
    finally:
        conn.close()
