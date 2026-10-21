"""Write side of the web board. Every apply-table write goes through the existing APIs:

* application status / notes -> `jobwatch.commands.state.set_status` (matches) or `ledger.upsert`
  (postings without a match), so `jobwatch reindex` can rebuild them;
* drafting -> the configured career-ops runtime in the existing background thread,
  status via `draft_status`;
* outcome approve/reject -> `jobwatch.outcomes.decide.decide`.
"""
from __future__ import annotations

import contextvars
import functools
import importlib
import json
import logging
import threading
import uuid
from datetime import UTC, datetime

from .. import db as dbm
from .. import ledger, users
from ..commands import state as cstate

log = logging.getLogger("jobwatch.web")
SOURCE = "web"


class ActionError(ValueError):
    pass


def _app_for_posting(conn, posting_id: int):
    return conn.execute("SELECT * FROM applications WHERE posting_id=?", (posting_id,)).fetchone()


def set_status(conn, posting_id: int, status: str, *, source: str = SOURCE) -> dict:
    """Move a posting's application to `status` (creating it if needed). No-op if unchanged."""
    try:
        status = cstate.check_status(status)
    except cstate.StatusError as exc:
        raise ActionError(str(exc)) from exc
    p = conn.execute("SELECT id FROM postings WHERE id=?", (posting_id,)).fetchone()
    if p is None:
        raise ActionError(f"no job {posting_id}")
    app = _app_for_posting(conn, posting_id)
    if app and app["status"] == status:
        return {"application_id": app["id"], "from_status": status, "to_status": status, "changed": False}
    m = conn.execute("SELECT id FROM matches WHERE posting_id=?", (posting_id,)).fetchone()
    if m:
        return cstate.set_status(conn, m["id"], status, actor="owner", source=source)
    # a posting outside the matches (All jobs scope): same writes, by posting id
    at = dbm.ts()
    values = {"posting_id": posting_id, "match_id": None, "arm": None, "status": status, "updated_at": at}
    if app:
        values.update(id=app["id"], created_at=app["created_at"], applied_at=app["applied_at"],
                      match_id=app["match_id"], arm=app["arm"])
    else:
        values["created_at"] = at
    if status in ("applied", "assessment", "interview", "offer") and not values.get("applied_at"):
        values["applied_at"] = at
    row = ledger.upsert(conn, "applications", "applications", values, commit=False)
    ledger.upsert(conn, "applications", "application_events", {
        "application_id": row["id"], "at": at, "kind": "status",
        "from_status": app["status"] if app else None, "to_status": status, "actor": "owner",
        "source": source, "detail_json": "{}"}, commit=False)
    conn.commit()
    return {"application_id": row["id"], "from_status": app["status"] if app else None,
            "to_status": status, "changed": True}


def hide(conn, posting_id: int) -> dict:
    """Hide = 'skipped'. Refused once the application is past 'applied' (change its status instead)."""
    app = _app_for_posting(conn, posting_id)
    if app and app["status"] in ("applied", "assessment", "interview", "offer"):
        raise ActionError(f"Already {app['status']}: change its status instead of hiding it")
    return set_status(conn, posting_id, "skipped")


def save(conn, posting_id: int) -> tuple[dict, str]:
    """Save = 'interested'. Never moves an application that is already further along backwards."""
    app = _app_for_posting(conn, posting_id)
    if app and app["status"] not in ("skipped",):
        if app["status"] == "interested":
            return {"changed": False}, "Already saved"
        return {"changed": False}, f"Already in your applications ({app['status']})"
    return set_status(conn, posting_id, "interested"), "Saved"


def set_notes(conn, posting_id: int, notes: str, *, source: str = SOURCE) -> dict:
    notes = (notes or "").replace("\r\n", "\n").strip()[:4000]
    app = _app_for_posting(conn, posting_id)
    if app is None:
        set_status(conn, posting_id, "interested", source=source)
        app = _app_for_posting(conn, posting_id)
    if (app["notes"] or "") == notes:
        return dict(app)
    return ledger.upsert(conn, "applications", "applications",
                         {"id": app["id"], "notes": notes or None, "updated_at": dbm.ts()})


# -- drafting -------------------------------------------------------------------------------------
_JOBS: dict[tuple[str, int], dict] = {}   # (person, posting_id) -> {state: running|done|error, error, started, actor}
_LOCK = threading.Lock()


def _chain():
    return importlib.import_module("jobwatch.apply.chain")


def draft_job(posting_id: int) -> dict | None:
    with _LOCK:
        j = _JOBS.get((users.current(), posting_id))
        return dict(j) if j else None


def start_draft(conn, db_path, posting_id: int, *, config=None) -> dict:
    """Run the selected career-ops implementation in the existing draft worker."""
    from jobwatch.config import load_config
    from pipeline.agentic import service as agentic
    from pipeline.schemas import Stage
    config = config if config is not None else load_config()
    use_agentic = agentic.enabled(config)
    m = conn.execute("SELECT id FROM matches WHERE posting_id=?", (posting_id,)).fetchone()
    if m is None and not use_agentic:
        raise ActionError("Only matched jobs can be drafted (this job did not match a target arm).")
    key = (users.current(), posting_id)
    with _LOCK:
        j = _JOBS.get(key)
        if j and j["state"] == "running":
            return dict(j)
    chain = _chain() if not use_agentic else None
    if chain is not None:
        try:
            chain.gate(conn, m["id"])
        except chain.DraftRefused as exc:
            raise ActionError(f"Draft refused: {exc}") from exc
    actor = f"web:{uuid.uuid4().hex[:12]}"
    job = {"state": "running", "error": None, "started": datetime.now(UTC).isoformat(timespec="seconds"),
           "actor": actor}
    with _LOCK:
        _JOBS[key] = job

    def run():
        c = dbm.connect(db_path)
        try:
            if use_agentic:
                stage = agentic.run_agentic_job(posting_id, config, c)
                res = {'state': 'done' if stage == Stage.READY else 'error',
                       'error': None if stage == Stage.READY else 'Application package is held; open the job for its reason.'}
            else:
                chain.start_draft(c, m["id"], actor)
                res = {"state": "done", "error": None}
        except Exception as exc:            # recorded for the status chip, and logged
            log.error("draft worker failed: %s", type(exc).__name__)
            res = {"state": "error", "error": "Draft worker failed; open the job for its current status."}
        finally:
            c.close()
        with _LOCK:
            _JOBS[key].update(res)

    ctx = contextvars.copy_context()        # the worker runs as the person who pressed Draft (their DB, profile, drafts)
    threading.Thread(target=functools.partial(ctx.run, run), name=f"draft-{posting_id}", daemon=True).start()
    return dict(job)


def _file_urls(files: dict) -> dict:
    """Absolute draft paths -> /files/drafts/... URLs (only files inside the drafts dir are linked)."""
    from pathlib import Path

    from ..apply import paths as apaths
    root = apaths.drafts_dir().resolve()
    out = {}
    for key, name in (("cv", "cv_pdf"), ("letter", "letter_pdf"), ("summary", "summary_md")):
        p = files.get(name)
        if not p:
            continue
        try:
            out[key] = "/files/drafts/" + Path(p).resolve().relative_to(root).as_posix()
        except ValueError:
            continue
    return out


def draft_state(conn, posting_id: int) -> dict:
    """{state: none|running|ready|failed|error, error, files {cv,letter,summary} (absolute paths),
    version, started}. Combines the in-process job with the drafts table."""
    job = draft_job(posting_id)
    app = _app_for_posting(conn, posting_id)
    ds = _chain().draft_status(conn, app["id"]) if app else {"status": "none", "files": {}}
    out = {"state": "none", "error": None, "files": {}, "version": ds.get("version"), "started": None}
    if job and job["state"] == "running":
        out.update(state="running", started=job["started"])
        return out
    st = ds.get("status") or "none"
    if st == "drafting":
        out["state"] = "running"
    elif st == "ready":
        out.update(state="ready", files=_file_urls(ds.get("files") or {}))
    elif st == "failed":
        out.update(state="failed", error=(ds.get("error") or "")[:300])
    if job and job["state"] == "error" and out["state"] in ("none", "failed"):
        out.update(state="error", error=job["error"])
    return out


# -- outcome proposals ------------------------------------------------------------------------------
def decide_proposal(conn, proposal_id: int, decision: str) -> str:
    """Approve/reject one proposal through outcomes.decide. decide() works on numbered batches,
    so a one-item batch (event id web:p<id>) is registered for the call and removed after."""
    if decision not in ("approve", "reject"):
        raise ActionError("decision must be approve or reject")
    from ..outcomes import decide as dmod
    from ..outcomes.sync import BATCHES_KEY
    row = conn.execute("SELECT status FROM outcome_proposals WHERE id=?", (proposal_id,)).fetchone()
    if row is None:
        raise ActionError("proposal not found")
    if row["status"] != "proposed":
        return f"Already {row['status']}"
    key, event = f"web-p{proposal_id}", f"web:p{proposal_id}"
    batches = dbm.get_state(conn, BATCHES_KEY, {}) or {}
    batches[key] = {"event_id": event, "ids": [proposal_id], "at": dbm.ts()}
    dbm.set_state(conn, BATCHES_KEY, batches)
    conn.commit()
    try:
        out = dmod.decide(conn, [1], decision, source=SOURCE, reply_to=event)
    finally:
        batches = dbm.get_state(conn, BATCHES_KEY, {}) or {}
        batches.pop(key, None)
        dbm.set_state(conn, BATCHES_KEY, batches)
        conn.commit()
    text = "; ".join(out)
    return text.split(") ", 1)[1] if text.startswith("1) ") else text


# -- saved searches (UI-only table) -------------------------------------------------------------------
def save_search(conn, name: str, params: dict) -> int:
    name = (name or "").strip()[:80] or "Saved search"
    now = dbm.ts()
    cur = conn.execute("INSERT INTO saved_searches(name, query_json, created_at, last_visit_at) VALUES(?,?,?,?)",
                       (name, json.dumps(params, sort_keys=True), now, now))
    conn.commit()
    return cur.lastrowid


def touch_search(conn, search_id: int) -> None:
    conn.execute("UPDATE saved_searches SET last_visit_at=? WHERE id=?", (dbm.ts(), search_id))
    conn.commit()


def delete_search(conn, search_id: int) -> None:
    conn.execute("DELETE FROM saved_searches WHERE id=?", (search_id,))
    conn.commit()
