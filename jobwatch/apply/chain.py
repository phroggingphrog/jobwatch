"""Draft chain (PLAN-apply; ai-job-search style). Public API used by the command layer:

    start_draft(conn, match_id, actor_event) -> application_id
    draft_status(conn, application_id) -> dict      (no personal text)

Steps: (a) fit-stop gate -> requirements -> (b) drafter -> (c) code verifier -> (d) fresh-context
reviewer -> (e) reviser -> (c) verifier again -> (f) render PDF -> (g) verify_pdf -> (h) write
drafts/<application_id>/v<n>/ + drafts table + ledger. Runs synchronously.
jobwatch never sends anything to an employer; the owner applies.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .. import ledger, onboarding
from ..commands.state import SUBMITTED   # past the draft stages: a new draft never moves these back
from jobwatch.util.llm import LLM
from jobwatch.util.model_choice import get_model
from . import render, review
from .evidence import load_profile
from .paths import drafts_dir, ensure_dir, safe_write_bytes, safe_write_text
from .requirements import full_posting_text, get_or_extract
from .verify import iter_claims, verify_draft
from .verify_pdf import verify_pdf

log = logging.getLogger(__name__)
CURRENT_DAYS = 30          # a match is current if its posting was seen in the last 30 days
TERMINAL = ("skipped", "withdrawn", "rejected")


class DraftRefused(Exception):
    """The fit-stop gate refused (reason in str(exc)). Nothing was drafted."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _event(conn, app_id: int, kind: str, actor: str, source: str | None, from_s=None, to_s=None,
           detail: dict | None = None) -> dict:
    return ledger.upsert(conn, "applications", "application_events",
                         {"application_id": app_id, "at": _now(), "kind": kind, "from_status": from_s,
                          "to_status": to_s, "actor": actor, "source": source,
                          "detail_json": json.dumps(detail or {}, sort_keys=True)}, commit=False)


def _set_status(conn, app: dict, status: str, actor: str, source: str | None, detail=None) -> dict:
    if app["status"] == status:
        return app
    old = app["status"]
    app = ledger.upsert(conn, "applications", "applications",
                        {"id": app["id"], "status": status, "updated_at": _now()}, commit=False)
    _event(conn, app["id"], "status", actor, source, old, status, detail)
    return app


def gate(conn: sqlite3.Connection, match_id: int) -> tuple[sqlite3.Row, sqlite3.Row, dict | None]:
    """(a) fit-stop gate. The owner's command is the recorded proceed; code still refuses a
    match that is not current or an application that was skipped/closed."""
    m = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    if m is None:
        raise DraftRefused(f"match {match_id} not found")
    p = conn.execute("SELECT * FROM postings WHERE id=?", (m["posting_id"],)).fetchone()
    if p is None:
        raise DraftRefused(f"posting for match {match_id} not found")
    cutoff = (datetime.now(UTC) - timedelta(days=CURRENT_DAYS)).isoformat(timespec="seconds")
    if (p["last_seen_at"] or "") < cutoff:
        raise DraftRefused(f"match {match_id} is not current (posting last seen {p['last_seen_at']})")
    row = conn.execute("SELECT * FROM applications WHERE posting_id=?", (p["id"],)).fetchone()
    app = dict(row) if row else None
    if app and app["status"] in TERMINAL:
        raise DraftRefused(f"application {app['id']} is '{app['status']}'")
    if app:                                   # busy is judged from the draft rows: a submitted application keeps its status
        stale = (datetime.now(UTC) - timedelta(hours=2)).isoformat(timespec="seconds")
        busy = conn.execute("SELECT 1 FROM drafts WHERE application_id=? AND status='drafting' "
                            "AND created_at>=?", (app["id"], stale)).fetchone()
        if busy:
            raise DraftRefused(f"application {app['id']} is already drafting")
    return m, p, app


def start_draft(conn: sqlite3.Connection, match_id: int, actor_event: str, *, llm: LLM | None = None,
                profile=None) -> int:
    """Create/get the application, record the owner's proceed, run the chain, return its id.
    Raises DraftRefused when the gate refuses. A chain failure is recorded (draft status
    'failed' with reasons) and the application id is still returned."""
    m, p, app = gate(conn, match_id)
    now = _now()
    if app is None:
        app = ledger.upsert(conn, "applications", "applications",
                            {"posting_id": p["id"], "match_id": m["id"], "arm": m["arm"],
                             "status": "interested", "created_at": now, "updated_at": now}, commit=False)
    _event(conn, app["id"], "command", "owner", actor_event, detail={"command": "draft", "match_id": match_id})
    prev_status = app["status"]
    if prev_status not in SUBMITTED:
        app = _set_status(conn, app, "drafting", "jobwatch", actor_event)
    version = (conn.execute("SELECT MAX(version) FROM drafts WHERE application_id=?",
                            (app["id"],)).fetchone()[0] or 0) + 1
    vdir = drafts_dir() / str(app["id"]) / f"v{version}"
    draft_row = ledger.upsert(conn, "drafts", "drafts",
                              {"application_id": app["id"], "version": version, "created_at": now,
                               "status": "drafting", "dir": str(vdir)}, commit=False)
    conn.commit()
    t0 = time.monotonic()
    llm = llm or LLM()
    summary: dict
    try:
        summary = run_chain(conn, p, app["id"], version, vdir, llm, profile)
        status = "ready" if summary["verify_ok"] else "failed"
        error = None if summary["verify_ok"] else "; ".join(summary["failures"])[:1000]
    except Exception as exc:  # recorded, not swallowed silently
        log.exception("draft chain failed")
        summary = {"verify_ok": False, "failures": [f"{type(exc).__name__}: {str(exc)[:300]}"]}
        status, error = "failed", summary["failures"][0]
    summary["runtime_s"] = round(time.monotonic() - t0, 1)
    summary["models"] = sorted({c["model"] for c in llm.calls})
    summary["llm_calls"] = len(llm.calls)
    costs = [c["cost_usd"] for c in llm.calls if c.get("cost_usd") is not None]
    summary["cost_usd_est"] = round(sum(costs), 4) if costs else None
    if vdir.exists():
        safe_write_text(vdir / "summary.json", json.dumps(summary, indent=2, sort_keys=True))
    ledger.upsert(conn, "drafts", "drafts",
                  {"id": draft_row["id"], "status": status, "error": error,
                   "claims_json": json.dumps(summary.get("claims_counts", {})),
                   "verify_json": json.dumps({"ok": summary["verify_ok"], "failures": summary["failures"],
                                              "pages": summary.get("pages")}),
                   "review_json": json.dumps(summary.get("reviewer_edits", {})),
                   "models_json": json.dumps({"models": summary["models"], "calls": llm.calls})},
                  commit=False)
    cur = conn.execute("SELECT * FROM applications WHERE id=?", (app["id"],)).fetchone()   # not the stale dict
    if cur is not None and cur["status"] == "drafting":      # skipped/applied meanwhile: keep the owner's change
        _set_status(conn, dict(cur), "drafted" if status == "ready" else prev_status, "jobwatch", actor_event,
                    {"draft_version": version, "draft_status": status})
    conn.commit()
    return app["id"]


def run_chain(conn, p: sqlite3.Row, app_id: int, version: int, vdir: Path, llm: LLM, profile=None) -> dict:
    profile = profile or load_profile()
    ptext = full_posting_text(conn, p)
    posting = {"title": p["title"], "company": p["company"]}
    cv_tpl, _ = render.pick_templates(posting)
    reqs = get_or_extract(conn, p["id"], llm)
    req_ids = {r["id"] for r in reqs}
    ensure_dir(vdir)

    # (b) drafter
    res = llm.chat(get_model("writer"), review.drafter_messages(ptext, reqs, profile.cv_body, profile.evidence,
                                                                 ad_reading(conn, p["id"]), angle_notes(profile),
                                                                 None),
                   max_tokens=12000)
    draft0 = res.data or {}
    # (c) verifier
    draft1, rep1 = verify_draft(draft0, profile.by_id, ptext, req_ids)
    # (d) fresh-context reviewer: drafts inline + named refs (posting, cited evidence) only
    cited = _cited(draft1, profile)
    claim_ids = {c["id"] for _, c in iter_claims(draft1)}
    edits = review.run_reviewer(llm, render.cv_markdown(draft1, profile, tagged=True, cv_tpl=cv_tpl),
                                render.letter_markdown(draft1, profile, posting, tagged=True, cv_tpl=cv_tpl), ptext,
                                cited, claim_ids)
    edits += [e for e in review.stock_edits(draft1) if e["target"] not in {x["target"] for x in edits}]
    # (e) reviser, then (c) again
    applied, skipped = [], []
    draft2, rep2 = draft1, rep1
    if edits:
        rres = llm.chat(review.REVISER_MODEL, review.reviser_messages(draft1, edits, ptext, profile.evidence),
                        max_tokens=12000)
        revised = rres.data or {}
        applied = [i for i in revised.get("applied") or [] if isinstance(i, int)]
        skipped = [s for s in revised.get("skipped") or [] if isinstance(s, dict)]
        cand, cand_rep = verify_draft({k: revised.get(k) for k in ("cv", "letter", "honest_gaps")},
                                      profile.by_id, ptext, req_ids)
        if isinstance(revised.get("cv"), dict) and cand_rep["claims_kept"] * 2 >= rep1["claims_kept"]:
            draft2, rep2 = cand, cand_rep
        else:  # reviser output unusable -> keep the verified first draft, say so
            skipped.append({"index": -1, "why": "reviser output rejected by code (lost most claims)"})
    stock_dropped = review.drop_stock_framing(draft2)
    repeats_dropped = review.drop_repeats(draft2)
    closing_missing = any(e["reason"].startswith("no closing") for e in review.stock_edits(draft2))
    stock_left = sum(e["reason"].startswith("stock") for e in review.stock_edits(draft2))
    # (f) render
    cv_md = render.cv_markdown(draft2, profile, cv_tpl=cv_tpl)
    letter_md = render.letter_markdown(draft2, profile, posting, cv_tpl=cv_tpl)
    cv_pdf, cv_info = render.render_pdf(cv_md, max_pages=render.CV_PAGES[cv_tpl])
    letter_pdf, letter_info = render.render_pdf(letter_md, max_pages=1, letter=True)
    safe_write_text(vdir / "cv.md", cv_md)
    safe_write_text(vdir / "letter.md", letter_md)
    safe_write_bytes(vdir / "cv.pdf", cv_pdf)
    safe_write_bytes(vdir / "letter.pdf", letter_pdf)
    # (g) verify_pdf
    vres = verify_pdf(vdir / "cv.pdf", vdir / "letter.pdf", draft2, reqs, profile)
    vres["render"] = {"cv": cv_info, "letter": letter_info}
    failures = list(vres["failures"])
    if rep2["claims_kept"] == 0:
        failures.append("no verified claims left")
    # (h) write artefacts
    edits_by_kind = {k: sum(1 for e in edits if e["kind"] == k) for k in review.EDIT_KINDS}
    gaps = {g["requirement_id"] for g in draft2.get("honest_gaps") or []} | set(vres["coverage_gaps"])
    req_by_id = {r["id"]: r for r in reqs}
    safe_write_text(vdir / "claims.json", json.dumps({
        "draft": draft2, "verifier_first_pass": rep1, "verifier_final": rep2}, indent=2, ensure_ascii=False))
    safe_write_text(vdir / "verify.json", json.dumps(vres, indent=2, ensure_ascii=False))
    safe_write_text(vdir / "review.json", json.dumps({
        "reviewer_model": get_model("reviewer"), "edits": edits, "applied": applied, "skipped": skipped},
        indent=2, ensure_ascii=False))
    safe_write_text(vdir / "requirements.json", json.dumps(reqs, indent=2, ensure_ascii=False))
    summary = {
        "application_id": app_id, "version": version, "dir": str(vdir),
        "files": {n: str(vdir / n) for n in ("cv.pdf", "letter.pdf", "cv.md", "letter.md", "summary.md")},
        "posting": {"title": p["title"], "company": p["company"], "location": p["location"]},
        "requirements": {"total": len(reqs), "jd_quoted": sum(r["tier"] == "jd_quoted" for r in reqs),
                         "structural": sum(r["tier"] == "structural" for r in reqs),
                         "inferred": sum(r["tier"] == "inferred" for r in reqs),
                         "blockers": sum(bool(r["blocker"]) for r in reqs)},
        "claims_counts": {"drafted": rep1["claims_kept"] + rep1["claims_removed"],
                          "kept": rep2["claims_kept"],
                          "removed_first_pass": rep1["claims_removed"],
                          "removed_after_revision": rep2["claims_removed"],
                          "removed_by_reason": _merge_counts(rep1["removed_by_reason"], rep2["removed_by_reason"]),
                          "tiers": rep2["tiers"]},
        "gaps": [{"requirement_id": g, "requirement": req_by_id.get(g, {}).get("text"),
                  "blocker": bool(req_by_id.get(g, {}).get("blocker"))} for g in sorted(gaps)],
        "reviewer_edits": {**edits_by_kind, "applied": len(applied), "skipped": len(skipped)},
        "stock_phrases_left": stock_left, "stock_framing_dropped": stock_dropped,
        "repeats_dropped": repeats_dropped, "closing_missing": closing_missing,
        "pages": {"cv": vres["cv"]["pages"], "letter": vres["letter"]["pages"]},
        "keyword_coverage": {"covered": sum(r["covered"] for r in vres["keyword_coverage"]),
                             "total": len(vres["keyword_coverage"])},
        "verify_ok": not failures, "failures": failures,
    }
    safe_write_text(vdir / "summary.md", _summary_md(summary))
    return summary


def ad_reading(conn, posting_id: int) -> dict | None:
    """The reader's analysis of the full ad (ad_reviews.report_json): summary, requirement table with
    importance and the ad's own words, and the gaps it saw. None when the ad was not read."""
    row = conn.execute("SELECT report_json FROM ad_reviews WHERE posting_id=?", (posting_id,)).fetchone()
    try:
        rep = json.loads(row[0]) if row and row[0] else None
    except ValueError:
        rep = None
    if not isinstance(rep, dict):
        return None
    reqs = [{k: r.get(k) for k in ("requirement", "importance", "jd_signal")}
            for r in rep.get("requirements") or [] if isinstance(r, dict)]
    gaps = [g.get("gap") for g in rep.get("gaps") or [] if isinstance(g, dict) and g.get("gap")]
    return {"tldr": rep.get("tldr"), "archetype": rep.get("archetype"), "requirements": reqs[:12], "gaps": gaps[:6]}


ANGLE_SECTIONS = ("## Your Adaptive Framing", "## Your Exit Narrative")


def angle_notes(profile) -> str:
    """How the owner wants to be presented (career_ops_profile.md framing + exit narrative sections)."""
    path = Path(profile.dir) / "career_ops_profile.md"
    if not path.exists():
        return ""
    out, keep = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            keep = line.strip() in ANGLE_SECTIONS
        if keep:
            out.append(line)
    return "\n".join(out).strip()


def _merge_counts(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = out.get(k, 0) + v
    return out


def _cited(draft: dict, profile) -> list[dict]:
    ids: list[str] = []
    for _, c in iter_claims(draft):
        ids += [i for i in c.get("evidence_ids") or [] if i not in ids]
    cv = draft.get("cv") or {}
    for sec, key in (("experience", "role_ids"), ("education", "entry_ids")):
        for b in cv.get(sec) or []:
            ids += [i for i in b.get(key) or [] if i not in ids]
    return [profile.by_id[i] for i in ids if i in profile.by_id]


def _summary_md(s: dict) -> str:
    c, r = s["claims_counts"], s["requirements"]
    lines = [f"# Draft v{s['version']}: {s['posting']['title']} ({s['posting']['company']})", "",
             f"- Verify: {'PASS' if s['verify_ok'] else 'FAIL'}"
             + ("" if s["verify_ok"] else f" ({'; '.join(s['failures'])})"),
             f"- Pages: CV {s['pages']['cv']}, letter {s['pages']['letter']}",
             f"- Requirements: {r['total']} ({r['jd_quoted']} quoted, {r['structural']} structural, "
             f"{r['inferred']} inferred; {r['blockers']} blockers)",
             f"- Claims: {c['kept']} kept of {c['drafted']} drafted; removed {c['removed_first_pass']} "
             f"(first pass) + {c['removed_after_revision']} (after revision) {c['removed_by_reason']}",
             f"- Reviewer edits: {s['reviewer_edits']}",
             f"- Stock phrases left: {s.get('stock_phrases_left', 0)}; repeated facts dropped: "
             f"{s.get('repeats_dropped', 0)}; closing paragraph: {'missing' if s.get('closing_missing') else 'yes'}",
             f"- Keyword coverage (advisory): {s['keyword_coverage']['covered']}/{s['keyword_coverage']['total']}",
             "", "## Honest gaps", ""]
    lines += [f"- {'[blocker] ' if g['blocker'] else ''}{g['requirement']}" for g in s["gaps"]] or ["- none"]
    lines += ["", "jobwatch never sends anything to an employer. Review the PDFs, then apply yourself."]
    return "\n".join(lines) + "\n"


def draft_status(conn: sqlite3.Connection, application_id: int) -> dict:
    """Latest draft of an application, in the shape the command layer consumes:
    {application_id, found, status (draft: ready|failed|drafting|none), application_status,
     version, summary (summary.md text: posting title, counts, gaps; no profile text),
     error, dir, files {cv_pdf, letter_pdf, summary_md}, metrics (summary dict)}"""
    app = conn.execute("SELECT * FROM applications WHERE id=?", (application_id,)).fetchone()
    if app is None:
        return {"application_id": application_id, "found": False, "status": "none",
                "error": "application not found", "files": {}}
    d = conn.execute("SELECT * FROM drafts WHERE application_id=? ORDER BY version DESC LIMIT 1",
                     (application_id,)).fetchone()
    out = {"application_id": application_id, "found": True, "status": "none",
           "application_status": app["status"], "match_id": app["match_id"],
           "posting_id": app["posting_id"], "version": None, "summary": "", "error": None,
           "dir": None, "files": {}, "metrics": None}
    if d is None:
        return out
    vdir = Path(d["dir"]) if d["dir"] else None
    out.update(status=d["status"], version=d["version"], error=d["error"], dir=d["dir"])
    if vdir:
        files = {"cv_pdf": vdir / "cv.pdf", "letter_pdf": vdir / "letter.pdf", "summary_md": vdir / "summary.md"}
        out["files"] = {k: str(v) for k, v in files.items() if v.exists()}
        if files["summary_md"].exists():
            out["summary"] = files["summary_md"].read_text(encoding="utf-8")
        if (vdir / "summary.json").exists():
            out["metrics"] = json.loads((vdir / "summary.json").read_text(encoding="utf-8"))
    return out
