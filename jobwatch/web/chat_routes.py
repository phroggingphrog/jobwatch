"""Chat page: one thread on the board. jobwatch posts its news here (and to the person's notification channels, see jobwatch.notify); the person asks
questions or gives rulings, and the model they chose for the "chat" role (jobwatch.model_choice) answers from a live
snapshot of the board. The assistant reads only; it never changes rules, submits or messages anyone. Rulings stay in the
thread for the maintainer to act on.
"""
from __future__ import annotations

import os
import re
from collections import Counter

from jobwatch.util.model_choice import get_model
from pathlib import Path

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from jobwatch import notify as nt

from . import queries as q

HISTORY = 20
SYSTEM = """You are the chat box on the person's jobwatch board (their personal job search system). Reply in plain,
short English: answer first, at most 5 bullet points, no preamble. Use only the snapshot below and the conversation; if the snapshot does not say,
say you do not know. You can only read. You cannot change rules, settings or jobs, submit applications or message
anyone. When the person gives a decision or a new rule, say "Saved for the maintainer to apply" (their message is kept
in this thread). Never invent jobs, scores or reasons. Speak to the person as "you"; do not use their name or username. Never show internal codes, file paths or ticket ids
(like insufficient_evidence, posting_unavailable, dlq, READY, held or T19): say it in plain words, using only the group names Good, Not fully read, Hidden by AI and Waiting for AI. Quote numbers exactly as the snapshot gives them and never correct them; if asked again, repeat the same numbers. For a job named in the question, answer from its detail lines; if none is there, say you cannot find that job. Do not contradict
earlier answers unless the snapshot clearly changed; if you were wrong, say so once, briefly."""


def system_prompt() -> str:
    """SYSTEM plus the person's own reply style (profile.yaml candidate.reply_style) when they set one."""
    from jobwatch.reader import person_prefs
    style = person_prefs()["reply_style"]
    return SYSTEM + (f"\n\nReply style the person asked for: {style}" if style else "")


_REG = None  # set by register(); the same registry the app pages use


def _plain(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _job_lines(rows) -> list[str]:
    """One job in plain words: the same AI summary, score and pros/cons the job page shows."""
    out = []
    for r in rows:
        ai = r.get("ai") or {}
        rep = ai.get("report") or {}
        rec = q.REC_WORDS.get(q.rec_key(r)) or "no recommendation yet"
        score = f"{r['score5']:.1f} out of 5" if r.get("score5") is not None else "not scored yet"
        state = dict(q.AI_VIEWS).get(r.get("ai_state"), "")
        line = (f"- {r['title']} at {r['company']} ({q.short_location(r.get('location')) or 'location not stated'}): "
                f"score {score}; AI view: {rec}; board group: {state}; your status: {r['status']}.")
        if rep.get("tldr") or ai.get("reason"):
            line += " Summary: " + _plain(rep.get("tldr") or ai.get("reason"))[:400]
        pros = [_plain(x)[:160] for x in (ai.get("pros") or [])[:4]]
        cons = [_plain(x)[:160] for x in (ai.get("cons") or [])[:4]] or \
               [_plain(g.get("gap"))[:160] for g in (rep.get("gaps") or [])[:3]]
        if pros:
            line += " Pros: " + "; ".join(pros) + "."
        if cons:
            line += " Cons: " + "; ".join(cons) + "."
        if ai.get("verdict") == "hide" and ai.get("hide_reason"):
            line += " The AI hid it because it " + q.hide_sentence(ai["hide_reason"]) + "."
        out.append(line)
    return out


def find_jobs(conn, text: str, reg=None, limit: int = 3) -> list[dict]:
    """Jobs whose title (and ideally company) is named in the question."""
    low = _plain(text).lower()
    hits = []
    for pid, title, company in conn.execute("SELECT id,title,COALESCE(company,'') FROM postings"):
        t = _plain(title).lower()
        if len(t) >= 6 and t in low:
            hits.append((0 if company and company.lower() in low else 1, -len(t), pid))
    ids = [pid for *_, pid in sorted(hits)[:limit]]
    return q.load_rows(conn, "all", ids=ids, reg=reg) if ids else []


def snapshot(conn, question: str = "") -> str:
    """Every number comes from the same query functions the Board and Insights pages use."""
    reg = _REG.refresh() if _REG else None
    rows = q.load_rows(conn, "matches", reg=reg)
    views = dict(q.AI_VIEWS)
    n = {k: 0 for k in views}
    for r in rows:
        n[r["ai_state"]] = n.get(r["ai_state"], 0) + 1
    pr = q.ai_progress(conn)
    lines = [f"Matched jobs on the board: {len(rows)}. By the board's AI view: " +
             ", ".join(f"{views[k]} {n[k]}" for k in views) + ".",
             f"Reader progress (the AI reading each matched ad in full): {pr['read']} of {pr['total']} read, {pr['left']} left to read."]
    top = sorted((r for r in rows if r["ai_state"] == "show" and r["status"] != "hidden"),
                 key=lambda r: -(r["score5"] or 0))[:8]
    lines.append("Best jobs now (the Good group, highest score first):" if top else "No jobs are in the Good group yet.")
    lines += _job_lines(top)
    held = Counter(q.hold_words(r["ai"].get("reason")) if r.get("ai") else "" for r in rows if r["ai_state"] == "review")
    if held:
        lines.append("Why jobs are held back as Not fully read: " +
                     ", ".join(f"{w or 'other'} {c}" for w, c in held.most_common(5)))
    hid = Counter(q.hide_label(r["ai"].get("hide_reason")) for r in rows if r["ai_state"] == "hide" and r.get("ai"))
    if hid:
        lines.append("Why the AI hid jobs: " + ", ".join(f"{w} {c}" for w, c in hid.most_common(6)))
    if reg:
        t = q.insights(conn, reg)["totals"]
        lines.append(f"Insights page totals: {t['postings']} jobs collected, {t['matches']} matched your search, "
                     f"{t['matches_7d']} new matches in the last 7 days, {t['matches_30d']} in the last 30 days, "
                     f"{t['employers_live']} employers seen in the last week.")
    apps = conn.execute("SELECT COUNT(*) FROM applications WHERE status NOT IN ('skipped','rejected','withdrawn')").fetchone()[0]
    lines.append(f"Applications in progress: {apps}.")
    bad = [c for c, f in conn.execute("SELECT collector,consecutive_failures FROM source_health") if f >= 3]
    lines.append("Job sources failing 3+ times in a row: " + (", ".join(q.src_label(b) for b in bad) if bad else "none."))
    named = find_jobs(conn, question, reg)
    if named:
        lines.append("Job(s) named in the question (full detail):")
        lines += _job_lines(named)
    return "\n".join(lines)


def answer(conn, llm=None) -> str:
    from jobwatch.util.llm import LLM
    rows = conn.execute("SELECT role,text FROM chat_messages WHERE " + nt.CHAT_VISIBLE + " ORDER BY id DESC LIMIT ?", (HISTORY,)).fetchall()[::-1]
    messages = [{"role": "system", "content": system_prompt() + "\n\nSNAPSHOT\n" + snapshot(conn, rows[-1][1] if rows else "")}]
    for role, text in rows:
        messages.append({"role": "user" if role == "owner" else "assistant",
                         "content": text if role != "jobwatch" else f"[jobwatch update] {text}"})
    if messages[-1]["role"] != "user":
        return ""
    result = (llm or LLM()).chat(get_model("chat"), messages, json_mode=False, max_tokens=1200, timeout=90)
    return (result.text or "").strip()


CHAT_HISTORY = 40

SUGGESTIONS = [
    "What is worth applying for today?",
    "What did the agent hold back, and why?",
    "How far has the reader got?",
]


def chat_history(conn) -> list[dict]:
    """The board's real chat messages as the app shows them (owner -> 'user')."""
    try:
        rows = conn.execute("SELECT role, text, created_at FROM chat_messages WHERE " + nt.CHAT_VISIBLE +
                            " ORDER BY id DESC LIMIT ?", (CHAT_HISTORY,)).fetchall()[::-1]
    except Exception:
        return []
    out = []
    for role, text, at in rows:
        stamp = ""
        if at:
            try:
                stamp = q.parse_ts(at).astimezone().strftime("%-I:%M %p")
            except Exception:
                stamp = ""
        msg = {"role": "assistant" if role != "owner" else "user", "text": str(text or "")[:4000], "time": stamp}
        # jobwatch's own pipeline notices are not chat replies: the chat shows errors in one strip
        # above the composer and "Ready for you" as a notice that opens the job.
        if role == "jobwatch":
            if msg["text"].startswith("Error:"):
                msg["notice"] = "error"
            elif msg["text"].startswith("Ready for you"):
                msg["notice"] = "ready"
                m = re.search(r"/job/(\d+)", msg["text"])
                if m:
                    msg["job"] = m.group(1)
                    msg["text"] = re.sub(r"\s*\S*/job/\d+\S*", "", msg["text"]).strip()
        out.append(msg)
    return out


def ask_card(skip: list[str], verify: bool = False, change: str | None = None):
    """The next quick question for Chat, or None (no answers file: no cards)."""
    from . import ask_cards
    try:
        return ask_cards.card(skip, verify=verify, change=change)
    except Exception:  # noqa: BLE001
        return None


def ask_answer(field: str, choice: str, other: str, skip: str) -> dict:
    """Save one quick-question answer. Returns the questions now done and the one to change, if any."""
    from . import ask_cards
    c = ask_cards.card([], change=field)
    opts = {str(i): v for i, (_, v) in enumerate(c["options"])} if c else {}
    value = other.strip() or opts.get(choice, "")
    seen = [x for x in skip.split(",") if x]
    if choice == "change":
        return {"skip": seen, "change": field}
    if choice in ("keep", "skip"):
        seen.append(field)
    elif value:
        ask_cards.save_answer(field, value)
        seen.append(field)
    return {"skip": seen, "change": None}


def register(app, config, conn_factory, render):
    global _REG
    _REG = q.Registry(lambda: config)

    @app.get("/chat")
    def chat_page():
        return RedirectResponse("/#chat", status_code=307)   # one Chat: the app's

    @app.post("/chat/ask")
    def chat_ask(field: str = Form(...), choice: str = Form(""), other: str = Form(""), skip: str = Form(""),
                 verify: str = Form("")):
        ask_answer(field, choice, other, skip)
        return RedirectResponse("/#chat", status_code=303)

