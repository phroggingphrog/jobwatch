"""Owner decisions on outcome proposals: `approve <n…>` / `reject <n…>` (PLAN-apply D8).

Numbers refer to the batch the command replies to, else the latest batch. Approve moves the
application forward (never backwards; 'rejected' always applies; 'hired' never exists).
"""
from __future__ import annotations

import json
from datetime import timedelta

from .. import db as dbm
from ..commands import apply_api
from ..commands.state import label as match_label, set_status
from ..models import now_utc
from .sync import BATCHES_KEY, LAST_BATCH_KEY, _proposed_at, changes_status


def _batch(conn, reply_to: str | None):
    batches = dbm.get_state(conn, BATCHES_KEY, {}) or {}
    if reply_to:
        for bid, b in batches.items():
            if b.get("event_id") == reply_to:
                return bid, b
    last = dbm.get_state(conn, LAST_BATCH_KEY)
    return (last, batches.get(last)) if last in batches else (None, None)


def decide(conn, numbers: list[int], decision: str, *, source: str, reply_to: str | None = None,
           expire_days: int = 7, now=None) -> list[str]:
    assert decision in ("approve", "reject")
    now = now or now_utc()
    bid, batch = _batch(conn, reply_to)
    if not batch:
        return ["No outcome batch to decide on."]
    ids = batch.get("ids") or []
    out = []
    for n in numbers:
        if n < 1 or n > len(ids):
            out.append(f"{n}) no such item in batch ({len(ids)} items)")
            continue
        row = conn.execute("SELECT * FROM outcome_proposals WHERE id=?", (ids[n - 1],)).fetchone()
        if row is None:
            out.append(f"{n}) proposal gone")
            continue
        at = _proposed_at(row)
        if row["status"] == "proposed" and at and now - at > timedelta(days=expire_days):
            apply_api.upsert(conn, "outcomes", "outcome_proposals",
                             {**dict(row), "status": "expired", "decided_at": dbm.ts(now)})
            out.append(f"{n}) expired")
            continue
        if row["status"] != "proposed":
            out.append(f"{n}) already {row['status']}")
            continue
        app = conn.execute("SELECT * FROM applications WHERE id=?", (row["application_id"],)).fetchone()
        match_id = app["match_id"] if app else None
        name = match_label(conn, match_id) if match_id else f"application {row['application_id']}"
        status = "approved" if decision == "approve" else "rejected"
        evidence = json.loads(row["evidence_json"] or "{}")
        apply_api.upsert(conn, "outcomes", "outcome_proposals",
                         {**dict(row), "status": status, "decided_at": dbm.ts(now)}, commit=False)
        detail = {"proposal_id": row["id"], "decision": status, "batch_id": bid,
                  "flags": evidence.get("flags") or []}
        if decision == "approve" and app and match_id and changes_status(app["status"], row["proposed_status"]):
            res = set_status(conn, match_id, row["proposed_status"], actor="owner", source=source,
                             kind="outcome_decided", detail=detail, now=now, commit=False)
            flag = " (offer: review it yourself)" if row["proposed_status"] == "offer" else ""
            out.append(f"{n}) {name}: {res['from_status']} → {res['to_status']}{flag}")
        else:
            if app:
                apply_api.upsert(conn, "applications", "application_events", {
                    "application_id": app["id"], "at": dbm.ts(now), "kind": "outcome_decided",
                    "from_status": app["status"], "to_status": app["status"], "actor": "owner",
                    "source": source, "detail_json": json.dumps(detail, sort_keys=True)}, commit=False)
            what = "rejected (no change)" if decision == "reject" else \
                f"approved, status stays {app['status'] if app else '?'}"
            out.append(f"{n}) {name}: {what}")
        conn.commit()
    return out
