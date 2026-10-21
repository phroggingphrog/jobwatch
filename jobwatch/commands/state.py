"""Application status changes shared by commands and outcome decisions.

Every row write goes through the ledger (`upsert`) so `jobwatch reindex` can rebuild the DB.
'hired' is never written: it is not a status (DB CHECK on outcome_proposals + this guard).
"""
from __future__ import annotations

import json

from .. import db as dbm
from . import apply_api

# Application statuses the owner may set. 'hired' is deliberately absent (never set by jobwatch).
STATUSES = ("interested", "drafting", "drafted", "applied", "assessment", "interview", "offer",
            "rejected", "withdrawn", "skipped")

# Progress order for outcome updates; a lower or equal rank never overwrites a higher one.
RANK = {"applied": 1, "assessment": 2, "interview": 3, "offer": 4}
APPLIED_PLUS = ("applied", "assessment", "interview", "offer", "rejected")
SUCCESS = ("assessment", "interview", "offer")
OPEN_EXCLUDED = ("rejected", "withdrawn", "skipped")


class StatusError(ValueError):
    pass


def check_status(status: str) -> str:
    s = (status or "").strip().lower()
    if s == "hired":
        raise StatusError("'hired' is never set by jobwatch (use 'offer'; the hire is yours to record)")
    if s not in STATUSES:
        raise StatusError(f"unknown state '{s}' (one of: {', '.join(STATUSES)})")
    return s


def match_info(conn, match_id: int):
    return conn.execute(
        """SELECT m.id AS match_id, m.posting_id, m.arm, p.title, p.company, p.url
           FROM matches m JOIN postings p ON p.id=m.posting_id WHERE m.id=?""", (match_id,)).fetchone()


def application_for_match(conn, match_id: int):
    return conn.execute(
        """SELECT a.* FROM applications a JOIN matches m ON m.posting_id=a.posting_id
           WHERE m.id=?""", (match_id,)).fetchone()


def label(conn, match_id: int) -> str:
    m = match_info(conn, match_id)
    if not m:
        return f"#{match_id}"
    return f"#{match_id} {m['title']} — {m['company'] or '?'}"


def set_status(conn, match_id: int, to_status: str, *, actor: str, source: str,
               kind: str = "status", detail: dict | None = None, now=None,
               commit: bool = True) -> dict:
    """Create the application row if needed and move it to `to_status`.
    Returns {application_id, from_status, to_status, changed}."""
    to_status = check_status(to_status)
    m = match_info(conn, match_id)
    if not m:
        raise StatusError(f"no match #{match_id}")
    at = dbm.ts(now)
    app = application_for_match(conn, match_id)
    from_status = app["status"] if app else None
    values = {"posting_id": m["posting_id"], "match_id": match_id, "arm": m["arm"],
              "status": to_status, "updated_at": at}
    if app:
        values["id"] = app["id"]
        values["created_at"] = app["created_at"]
        values["applied_at"] = app["applied_at"]
    else:
        values["created_at"] = at
    if to_status in ("applied", "assessment", "interview", "offer") and not values.get("applied_at"):
        values["applied_at"] = at
    changed = from_status != to_status
    row = apply_api.upsert(conn, "applications", "applications", values, commit=False)
    apply_api.upsert(conn, "applications", "application_events", {
        "application_id": row["id"], "at": at, "kind": kind, "from_status": from_status,
        "to_status": to_status, "actor": actor, "source": source,
        "detail_json": json.dumps(detail or {}, sort_keys=True)}, commit=False)
    if commit:
        conn.commit()
    return {"application_id": row["id"], "from_status": from_status, "to_status": to_status,
            "changed": changed}


def open_applications(conn) -> list:
    marks = ",".join("?" for _ in OPEN_EXCLUDED)
    return conn.execute(
        f"""SELECT a.id, a.status, a.updated_at, a.applied_at, m.id AS match_id, p.title, p.company
            FROM applications a JOIN postings p ON p.id=a.posting_id
            LEFT JOIN matches m ON m.posting_id=a.posting_id
            WHERE a.status NOT IN ({marks}) ORDER BY a.updated_at DESC""", OPEN_EXCLUDED).fetchall()
