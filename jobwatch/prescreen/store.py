"""Database access for prescreen: seeds, terms, rules, overrides, decisions, stats, re-admission. No vocabulary here."""
from __future__ import annotations

import json
import re
import sqlite3
from importlib.resources import files

CATEGORIES = ("seniority_level", "off_target_occupation", "location_outside", "employment_type", "work_rights", "experience")
MATCH_TYPES = ("word", "phrase", "regex")
APPLIES_TO = ("title", "location", "hours", "ad_text")
RULE_KINDS = ("term_hit", "level_not_approved", "years_over", "region_outside")
SEED_STATE_KEY = "prescreen_seed_version"


def _now() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).isoformat(timespec="seconds")


def compile_term(term: str, match_type: str) -> re.Pattern:
    """The one place a stored term becomes a pattern. Raises ValueError for a bad term (also used to validate on add)."""
    if match_type not in MATCH_TYPES:
        raise ValueError(f"match_type must be one of {MATCH_TYPES}")
    if not isinstance(term, str) or not term.strip():
        raise ValueError("term is empty")
    try:
        if match_type == "regex":
            return re.compile(term, re.I)
        body = r"\s+".join(re.escape(w) for w in term.split())
        if match_type == "word":
            body = r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])"
        return re.compile(body, re.I)
    except re.error as exc:
        raise ValueError(f"bad regex: {exc}") from None


# -- seeds ----------------------------------------------------------------------
def _seed(name: str) -> dict:
    return json.loads(files("jobwatch.prescreen").joinpath("seed", name).read_bytes())


def ensure_seeds(conn: sqlite3.Connection) -> int:
    """Insert seed rows that are missing (by seed_key). Never changes or re-enables a row the person edited. Returns rows added."""
    terms, rules = _seed("terms.json"), _seed("rules.json")
    version = int(terms["version"]) * 1000 + int(rules["version"])
    row = conn.execute("SELECT value FROM state WHERE key=?", (SEED_STATE_KEY,)).fetchone()
    if row and int(json.loads(row[0])) >= version:
        return 0
    added = 0
    now = _now()
    for t in terms["terms"]:
        compile_term(t["term"], t["match_type"])
        added += conn.execute(
            "INSERT OR IGNORE INTO prescreen_terms(category,term,match_type,applies_to,polarity,strength,value,field_tag,"
            "scope,source,enabled,seed_key,created_at) VALUES(?,?,?,?,?,?,?,?,'shared',?,1,?,?)",
            (t["category"], t["term"], t["match_type"], t["applies_to"], t.get("polarity", "exclude"),
             t.get("strength", "weak"), t.get("value"), t.get("field_tag"), t.get("source", ""), t["key"], now)).rowcount
    for r in rules["rules"]:
        added += conn.execute(
            "INSERT OR IGNORE INTO prescreen_rules(kind,params_json,effect,enabled,scope,source,seed_key,created_at) "
            "VALUES(?,?,?,1,'shared',?,?,?)",
            (r["kind"], json.dumps(r["params"], sort_keys=True), r.get("effect", "skip"), r.get("source", ""), r["key"], now)).rowcount
    conn.execute("INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (SEED_STATE_KEY, json.dumps(version)))
    conn.commit()
    return added


# -- terms and rules (CLI / settings routes) ---------------------------------------
def add_term(conn, *, category, term, match_type="word", applies_to="title", polarity="exclude", strength="weak",
             value=None, field_tag=None, source="person") -> int:
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of {CATEGORIES}")
    if applies_to not in APPLIES_TO:
        raise ValueError(f"applies_to must be one of {APPLIES_TO}")
    if polarity not in ("exclude", "allow") or strength not in ("obvious", "weak"):
        raise ValueError("polarity is exclude|allow and strength is obvious|weak")
    compile_term(term, match_type)
    cur = conn.execute(
        "INSERT INTO prescreen_terms(category,term,match_type,applies_to,polarity,strength,value,field_tag,scope,source,enabled,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,'person',?,1,?)",
        (category, term, match_type, applies_to, polarity, strength, value, field_tag, source, _now()))
    conn.commit()
    return cur.lastrowid


def set_term_enabled(conn, term_id: int, enabled: bool) -> bool:
    n = conn.execute("UPDATE prescreen_terms SET enabled=? WHERE id=?", (int(enabled), term_id)).rowcount
    conn.commit()
    return bool(n)


def add_rule(conn, *, kind, params: dict, effect="skip", source="person") -> int:
    if kind not in RULE_KINDS or effect not in ("skip", "flag"):
        raise ValueError(f"kind must be one of {RULE_KINDS}; effect is skip|flag")
    cur = conn.execute("INSERT INTO prescreen_rules(kind,params_json,effect,enabled,scope,source,created_at) VALUES(?,?,?,1,'person',?,?)",
                       (kind, json.dumps(params, sort_keys=True), effect, source, _now()))
    conn.commit()
    return cur.lastrowid


def set_rule_enabled(conn, rule_id: int, enabled: bool) -> bool:
    n = conn.execute("UPDATE prescreen_rules SET enabled=? WHERE id=?", (int(enabled), rule_id)).rowcount
    conn.commit()
    return bool(n)


# -- overrides ---------------------------------------------------------------------
def add_override(conn, *, kind, term_id=None, posting_id=None, employer=None, note="") -> None:
    conn.execute("INSERT OR IGNORE INTO prescreen_overrides(kind,term_id,posting_id,employer,note,created_at) VALUES(?,?,?,?,?,?)",
                 (kind, term_id, posting_id, (employer or "").casefold() or None, note, _now()))
    conn.commit()


# -- decisions ----------------------------------------------------------------------
def record_decision(conn, posting_id: int, stage: str, out) -> int:
    cur = conn.execute(
        "INSERT INTO prescreen_decisions(posting_id,at,stage,outcome,rule_id,term_id,category,matched_text,reason,"
        "parsed_fields_json,rules_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (posting_id, _now(), stage, out.outcome, out.rule_id, out.term_id, out.category, out.matched_text, out.reason,
         json.dumps(out.parsed, sort_keys=True, default=str), out.rules_hash))
    return cur.lastrowid


def latest_decision(conn, posting_id: int):
    return conn.execute("SELECT * FROM prescreen_decisions WHERE posting_id=? ORDER BY id DESC LIMIT 1", (posting_id,)).fetchone()


def is_current(conn, posting_id: int, rules_hash: str, stage: str | None = None) -> bool:
    row = latest_decision(conn, posting_id)
    return row is not None and row["rules_hash"] == rules_hash and (stage is None or row["stage"] == stage)


def stats(conn) -> list[dict]:
    """Hit counts per term from decisions: skips and the admits/flags where the term fired, to prune bad terms."""
    rows = conn.execute(
        "SELECT t.id, t.category, t.term, t.strength, t.enabled, "
        "SUM(d.outcome='skip') AS skips, SUM(d.outcome='flag') AS flags, "
        "(SELECT COUNT(*) FROM prescreen_overrides o WHERE o.term_id=t.id) AS overridden "
        "FROM prescreen_terms t JOIN prescreen_decisions d ON d.term_id=t.id GROUP BY t.id ORDER BY skips DESC, flags DESC").fetchall()
    return [dict(r) for r in rows]


# -- re-admission -----------------------------------------------------------------------
def readmit(conn, posting_id: int, node: str = "prescreen") -> bool:
    """Undo a prescreen skip. A skip made before the ad was fetched has no text yet: drop the row so ingest reads it again.
    A skip made with the full ad goes back to INGESTED."""
    from pipeline import store
    from pipeline.schemas import Stage
    row = store.get(conn, posting_id)
    if row is None or row["stage"] != str(Stage.ARCHIVED) or row["reason"] != "prescreened":
        return False
    if str(row["content_hash"]).startswith("prescreen:"):
        conn.execute("DELETE FROM pipeline_state WHERE posting_id=?", (posting_id,))
        store.event(conn, posting_id, node, Stage.ARCHIVED, Stage.INGESTED, 1, "prescreen_readmitted")
    else:
        store.move(conn, posting_id, node, Stage.ARCHIVED, Stage.INGESTED)
    return True
