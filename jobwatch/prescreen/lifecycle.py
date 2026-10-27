"""What happens to a posting after a prescreen decision: screen what is already in the queue, take a skip back when the
rules, the profile or an override change, and learn from a person's override. All of it is reversible."""
from __future__ import annotations

from pipeline import store as pstore
from pipeline.schemas import Stage

from . import store
from .engine import Engine, fields_of_row


def _row(conn, posting_id):
    return conn.execute("SELECT * FROM postings WHERE id=?", (posting_id,)).fetchone()


def _ad_text(conn, row) -> str:
    from jobwatch import adtext
    try:
        text, kind = adtext.local_text(conn, dict(row))
    except Exception:                       # noqa: BLE001 - no stored ad: the listing fields decide
        return ""
    return text if kind == "full" else ""


def screen_ingested(conn, policy) -> list[int]:
    """Screen jobs already INGESTED (before this feature, or after a rule/profile change). Archives clear mismatches."""
    pstore.ensure(conn)
    engine = Engine.load(conn, policy)
    done = []
    for (pid,) in conn.execute("SELECT posting_id FROM pipeline_state WHERE stage='ingested' ORDER BY posting_id").fetchall():
        if store.is_current(conn, pid, engine.rules_hash, "full"):
            continue
        row = _row(conn, pid)
        if row is None:
            continue
        out = engine.screen(conn, pid, fields_of_row(row, _ad_text(conn, row)), stage="full")
        if out.skip:
            pstore.move(conn, pid, "prescreen", Stage.INGESTED, Stage.ARCHIVED, output={"prescreen": out.summary()}, reason="prescreened")
            done.append(pid)
    conn.commit()
    return done


def reconsider(conn, policy, *, limit: int = 500) -> int:
    """Re-run the rules on every prescreened job whose decision is out of date (different rules hash). A job the rules no
    longer skip goes back into the queue: INGESTED if its ad is stored, otherwise it is read again by ingest."""
    pstore.ensure(conn)
    engine = Engine.load(conn, policy)
    back = 0
    for (pid,) in conn.execute("SELECT posting_id FROM pipeline_state WHERE stage='archived' AND reason='prescreened' "
                               "ORDER BY updated_at LIMIT ?", (limit * 4,)).fetchall():
        if store.is_current(conn, pid, engine.rules_hash):
            continue
        row = _row(conn, pid)
        if row is None or row["closed_at"] if "closed_at" in row.keys() else False:
            continue
        out = engine.screen(conn, pid, fields_of_row(row, _ad_text(conn, row)), stage="full")
        if not out.skip and store.readmit(conn, pid, "prescreen_reconsider"):
            back += 1
            if back >= limit:
                break
    conn.commit()
    return back


def override_skip(conn, posting_id: int, *, term_too: bool = True, note: str = "") -> dict:
    """The person overrides a skip: this posting is admitted, and (unless term_too is False) the term that fired is switched off for
    this person only. The job returns to the queue. Returns what was recorded."""
    pstore.ensure(conn)
    d = store.latest_decision(conn, posting_id)
    done = {"posting_id": posting_id, "term_id": None, "readmitted": False}
    store.add_override(conn, kind="posting", posting_id=posting_id, note=note)
    if term_too and d is not None and d["outcome"] == "skip" and d["term_id"]:
        store.add_override(conn, kind="term", term_id=d["term_id"], note=note)
        done["term_id"] = d["term_id"]
    done["readmitted"] = store.readmit(conn, posting_id, "prescreen_override")
    conn.commit()
    return done
