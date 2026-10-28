"""`jobwatch outcomes`: read-only mail scan -> outcome proposals -> one approval batch (PLAN-apply D8).

* Only applications in applied+ states with an applied_at are considered.
* Search (read-only MCP tools only): mail since applied_at from the company (name, distinctive word,
  careers domain) plus common ATS senders, in the configured mailboxes.
* Classify with rules; ambiguous mail may go to a paid allowlisted model (subject + 1,500 chars).
* Stored per proposal: subject (<=200), sender *domain*, message-id, a <=200-char evidence snippet.
  Bodies, addresses and names are never stored, printed or logged.
* Nothing changes an application until the owner replies `approve <n…>`. Proposals expire after 7 days.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from .. import db as dbm
from .. import google_oauth, users
from ..commands import apply_api
from ..commands.state import RANK
from ..models import now_utc
from .classify import classify_llm, classify_rules, never_hired
from .mcp import DEFAULT_URL, McpClient
from jobwatch.settings import DEFAULT_MODEL

log = logging.getLogger("jobwatch.outcomes")

DEFAULTS = {
    "mcp_url": DEFAULT_URL,
    "mailboxes": [{"account": "gmail", "mailbox": "[Gmail]/All Mail"},
                  {"account": "icloud", "mailbox": "Inbox"},
                  {"account": "icloud", "mailbox": "Archive"}],
    "ats_senders": ["workday", "pageup", "successfactors", "smartrecruiters", "greenhouse", "lever",
                    "ashby", "seek", "linkedin", "indeed", "careers.vic", "jobadder", "livehire",
                    "applynow"],
    "expire_days": 7,
    "use_llm": True,
    "llm_model": DEFAULT_MODEL,
    "max_llm_calls": 10,
    "slack_days": 2,             # mail up to 2 days before applied_at counts (the owner may log late)
}
ACTIVE = ("applied", "assessment", "interview", "offer")
SEEN_KEY, SEEN_CAP = "outcomes:seen", 5000
BATCHES_KEY, LAST_BATCH_KEY = "outcomes:batches", "outcomes:last_batch"
_STOP = {"pty", "ltd", "limited", "group", "australia", "australian", "inc", "the", "and", "of",
         "department", "services", "service", "company", "co", "corporation", "holdings", "careers", "jobs", "health", "council", "city", "state",
         "government", "bank", "university", "hospital"}


def _place_words() -> set[str]:
    """The person's own state and city words are not company names (state code, state name, city)."""
    from jobwatch.place import STATES, location_text, person_state
    state = person_state()
    words = set(re.findall(r"[a-z]+", f"{state or ''} {STATES.get(state, '')} {location_text()}".lower()))
    return words | ({"victorian"} if state == "VIC" else set())


_BOARD_HOSTS = ("seek.", "linkedin.", "indeed.", "myworkdayjobs", "workday", "pageup", "successfactors",
                "smartrecruiters", "greenhouse", "lever.co", "ashbyhq", "workable", "employmenthero",
                "applynow", "careers.vic", "jora", "google.", "reddit.", "oraclecloud", "phenom")


def settings_for(config) -> dict:
    out = dict(DEFAULTS)
    out.update((config.settings.get("outcomes") or {}))
    return out


# -- helpers --------------------------------------------------------------------------
def _norm_mid(mid: str | None) -> str:
    return (mid or "").strip().strip("<>").strip()


def _domain(addr: str | None) -> str:
    a = (addr or "").strip().lower()
    return a.rsplit("@", 1)[-1] if "@" in a else ""


def _parse_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else None


def company_terms(company: str | None, url: str | None) -> dict:
    """Search terms for one employer: full name, a distinctive word, a careers domain."""
    name = re.sub(r"\s+", " ", (company or "").strip())
    words = [w for w in re.findall(r"[a-z0-9]+", name.lower()) if len(w) >= 4 and w not in _STOP and w not in _place_words()]
    key = max(words, key=len) if words else ""
    host = (urlsplit(url or "").hostname or "").lower()
    domain = ""
    if host and not any(b in host for b in _BOARD_HOSTS):
        parts = host.split(".")
        keep = 4 if re.search(r"\.(vic|nsw|qld|sa|wa|tas|act|nt)\.gov\.au$", host) else \
            3 if host.endswith((".com.au", ".gov.au", ".org.au", ".net.au", ".edu.au")) else 2
        domain = ".".join(parts[-keep:])
    return {"name": name, "key": key, "domain": domain}


def _q(value: str) -> str:
    return '"' + value.replace('"', "") + '"'


def app_query(terms: dict, after: str) -> str | None:
    parts = []
    if terms["name"]:
        parts += [f"from {_q(terms['name'])}", f"subject {_q(terms['name'])}"]
    if terms["key"] and terms["key"] != terms["name"].lower():
        parts.append(f"from {terms['key']}")
    if terms["domain"]:
        parts.append(f"from {terms['domain']}")
    return f"({' or '.join(parts)}) and after {after}" if parts else None


def generic_query(senders: list[str], after: str) -> str:
    return "(" + " or ".join(f"from {s}" for s in senders) + f") and after {after}"


def _mentions(app: dict, env: dict) -> bool:
    """Does this envelope name the application's employer or job title?"""
    frm = env.get("from") or []
    frm = frm if isinstance(frm, list) else [frm]
    hay = " ".join([str(env.get("subject") or "")] +
                   [f"{(f or {}).get('name') or ''} {(f or {}).get('email') or ''}" for f in frm
                    if isinstance(f, dict)]).lower()
    t = app["terms"]
    if t["name"] and t["name"].lower() in hay:
        return True
    if t["key"] and re.search(rf"\b{re.escape(t['key'])}\b", hay):
        return True
    if t["domain"] and t["domain"] in hay:
        return True
    title = (app.get("title") or "").lower().strip()
    return len(title) >= 8 and title in hay


def _from_email(env: dict) -> str:
    frm = env.get("from") or []
    frm = frm if isinstance(frm, list) else [frm]
    for f in frm:
        if isinstance(f, dict) and f.get("email"):
            return f["email"]
    return ""


def active_applications(conn) -> list[dict]:
    marks = ",".join("?" for _ in ACTIVE)
    rows = conn.execute(
        f"""SELECT a.id, a.status, a.applied_at, a.arm, m.id AS match_id, p.company, p.title, p.url
            FROM applications a JOIN postings p ON p.id=a.posting_id
            LEFT JOIN matches m ON m.posting_id=a.posting_id
            WHERE a.applied_at IS NOT NULL AND a.status IN ({marks})""", ACTIVE).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["terms"] = company_terms(d["company"], d["url"])
        d["applied_dt"] = _parse_dt(d["applied_at"])
        out.append(d)
    return out


def changes_status(current: str | None, label: str) -> bool:
    if label == "rejected":
        return current != "rejected"
    return RANK.get(label, 0) > RANK.get(current or "", 0)


# -- expiry -----------------------------------------------------------------------------
def _proposed_at(row) -> datetime | None:
    try:
        return _parse_dt(json.loads(row["evidence_json"] or "{}").get("proposed_at"))
    except ValueError:
        return None


def expire(conn, days: int, now=None, dry_run: bool = False) -> int:
    now = now or now_utc()
    n = 0
    for row in conn.execute("SELECT * FROM outcome_proposals WHERE status='proposed'").fetchall():
        at = _proposed_at(row)
        if at and now - at > timedelta(days=days):
            n += 1
            if not dry_run:
                apply_api.upsert(conn, "outcomes", "outcome_proposals",
                                 {**dict(row), "status": "expired", "decided_at": dbm.ts(now)}, commit=False)
    if n and not dry_run:
        conn.commit()
    return n


# -- proposals (shown on the web Inbox; `--dry-run --show` prints them) -----------------------
def render_proposals(items: list[dict]) -> str:
    lines = [f"Job outcomes: {len(items)} to review (from your mail, read-only)"]
    for n, it in enumerate(items, 1):
        subj = (it.get("subject") or "").strip()
        subj = subj[:40] + ("…" if len(subj) > 40 else "")
        flag = " (offer: please review)" if it["proposed_status"] == "offer" else ""
        lines.append(f"{n}) #{it.get('match_id') or '?'} {it.get('company') or '?'} → "
                     f"{it['proposed_status']}{flag} — '{subj}' ({it.get('mailbox') or '?'})")
    return "\n".join(lines)


def open_proposals(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT o.*, m.id AS match_id, p.company FROM outcome_proposals o
           LEFT JOIN applications a ON a.id=o.application_id
           LEFT JOIN postings p ON p.id=a.posting_id
           LEFT JOIN matches m ON m.posting_id=a.posting_id
           WHERE o.status='proposed' ORDER BY o.id""").fetchall()
    return [dict(r) for r in rows]


# -- scan ----------------------------------------------------------------------------------
def scan(conn, mcp: McpClient, conf: dict, *, dry_run: bool, now=None, llm=None, stats: dict) -> list[dict]:
    """Search, dedupe, map, classify. Returns new proposals (inserted unless dry_run)."""
    now = now or now_utc()
    apps = active_applications(conn)
    stats["applications"] = len(apps)
    if not apps:
        return []
    slack = timedelta(days=int(conf["slack_days"]))
    first = min(a["applied_dt"] for a in apps if a["applied_dt"]) - slack
    after = (first - timedelta(days=1)).date().isoformat()
    known = {_norm_mid(r[0]) for r in conn.execute("SELECT source_message_id FROM outcome_proposals")}
    seen = set(dbm.get_state(conn, SEEN_KEY, []) or [])
    envelopes: dict[str, tuple[dict, dict, int | None]] = {}     # mid -> (env, mailbox conf, app id hint)
    for box in conf["mailboxes"]:
        queries: list[tuple[str, int | None]] = []
        for a in apps:
            q = app_query(a["terms"], ((a["applied_dt"] - slack) - timedelta(days=1)).date().isoformat())
            if q:
                queries.append((q, a["id"]))
        if conf["ats_senders"]:
            queries.append((generic_query(conf["ats_senders"], after), None))
        for q, hint in queries:
            try:
                envs = mcp.search(box["account"], box["mailbox"], q)
                stats["searches"] += 1
            except Exception as exc:
                stats["search_errors"] += 1
                log.warning("mail search failed on %s: %s", box["account"], type(exc).__name__)
                continue
            for env in envs:
                mid = _norm_mid(env.get("message-id") or env.get("message_id"))
                if not mid:
                    continue
                if mid not in envelopes or (hint is not None and envelopes[mid][2] is None):
                    envelopes[mid] = (env, box, hint)
    stats["messages_scanned"] = len(envelopes)

    by_id = {a["id"]: a for a in apps}
    proposals: list[dict] = []
    for mid, (env, box, hint) in envelopes.items():
        if mid in known or mid in seen:
            stats["already_seen"] += 1
            continue
        when = _parse_dt(env.get("date"))
        cands = [a for a in apps if _mentions(a, env)]
        if hint is not None and by_id[hint] not in cands:
            cands.append(by_id[hint])
        cands = [a for a in cands if a["applied_dt"] and (when is None or when >= a["applied_dt"] - slack)]
        if len(cands) != 1:
            stats["unmatched"] += 1
            continue
        app = cands[0]
        subject = str(env.get("subject") or "")
        verdict = classify_rules(subject)
        if verdict.label in (None, "applied"):
            try:
                body = mcp.read_body(box["account"], box["mailbox"], env.get("id"), 1500)
                stats["bodies_read"] += 1
            except Exception:
                body = ""
            verdict = classify_rules(subject, body)
            if verdict.ambiguous and conf["use_llm"]:
                if dry_run:
                    stats["would_llm"] += 1
                elif stats["llm_calls"] < int(conf["max_llm_calls"]):
                    stats["llm_calls"] += 1
                    verdict = classify_llm(subject, body, llm=llm, model=conf["llm_model"]) or verdict
        label = never_hired(verdict.label, verdict.flags)
        if label is None:
            stats["not_outcome"] += 1
            seen.add(mid)
            continue
        if not changes_status(app["status"], label):
            stats["no_change"] += 1
            seen.add(mid)
            continue
        row = {"application_id": app["id"], "source_message_id": mid, "mailbox": box["account"],
               "received_at": dbm.ts(when) if when else None, "subject": subject[:200],
               "from_addr": _domain(_from_email(env)), "proposed_status": label,
               "confidence": round(verdict.confidence, 2), "batch_id": None, "status": "proposed",
               "evidence_json": json.dumps({"snippet": verdict.snippet[:200], "rule": verdict.rule,
                                            "method": verdict.method, "flags": verdict.flags,
                                            "proposed_at": dbm.ts(now)}, sort_keys=True)}
        assert row["proposed_status"] != "hired"
        if not dry_run:
            row = apply_api.upsert(conn, "outcomes", "outcome_proposals", row, commit=False)
            apply_api.upsert(conn, "applications", "application_events", {
                "application_id": app["id"], "at": dbm.ts(now), "kind": "outcome_proposed",
                "from_status": app["status"], "to_status": label, "actor": "jobwatch",
                "source": f"mail:{mid}", "detail_json": json.dumps({"proposal_id": row["id"]})},
                commit=False)
            conn.commit()    # short write transaction: the next loop turn may read a body or call a model
        proposals.append({**row, "match_id": app["match_id"], "company": app["company"]})
        known.add(mid)
    if not dry_run:
        dbm.set_state(conn, SEEN_KEY, sorted(seen)[-SEEN_CAP:])
        conn.commit()
    return proposals


def new_stats() -> dict:
    return {"tools": 0, "applications": 0, "searches": 0, "search_errors": 0, "messages_scanned": 0,
            "already_seen": 0, "unmatched": 0, "bodies_read": 0, "llm_calls": 0, "would_llm": 0,
            "not_outcome": 0, "no_change": 0, "proposals": 0, "expired": 0, "error": None}


def run_outcomes(config, dry_run: bool = False, show: bool = False, printer=print, mcp=None,
                 llm=None, now=None, conn=None) -> dict:
    conf = settings_for(config)
    stats = new_stats()
    own_conn = conn is None
    conn = conn or dbm.connect(config.db_path)
    now = now or now_utc()
    try:
        stats["expired"] = expire(conn, int(conf["expire_days"]), now, dry_run)
        if mcp is None and users.current() != users.DEFAULT_USER and google_oauth.load():
            from ..google_gmail import GmailMcp      # a connected friend reads their own Gmail
            mcp, conf = GmailMcp(), {**conf, "mailboxes": [{"account": "gmail", "mailbox": "all"}]}
        mcp = mcp or McpClient(conf["mcp_url"])
        stats["tools"] = len(mcp.list_tools())
        proposals = scan(conn, mcp, conf, dry_run=dry_run, now=now, llm=llm, stats=stats)
        stats["proposals"] = len(proposals)
        if dry_run and show:
            items = open_proposals(conn) + proposals
            if items:
                printer(render_proposals(items))
    except Exception as exc:
        stats["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    finally:
        if own_conn:
            conn.close()
    return stats
