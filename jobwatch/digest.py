"""Weekly digest without an LLM: Reddit chatter themes + top posts, and posting/match stats."""
from __future__ import annotations

import html
import json
from datetime import timedelta

from . import db as dbm
from .config import Config
from .models import now_utc
from .outcomes.callback import callback_stats, render_lines as callback_lines


def gather(conn, days: int = 7, now=None) -> dict:
    since = dbm.ts((now or now_utc()) - timedelta(days=days))
    chatter = conn.execute(
        "SELECT * FROM reddit_posts WHERE stream='chatter' AND COALESCE(published_at, seen_at) >= ?",
        (since,)).fetchall()
    themes: dict[str, int] = {}
    for row in chatter:
        for theme in json.loads(row["themes_json"] or "[]"):
            themes[theme] = themes.get(theme, 0) + 1
    top = sorted(chatter, key=lambda r: (r["score"] or -1, r["comments"] or -1,
                                         r["published_at"] or r["seen_at"]), reverse=True)[:10]
    by_sub: dict[str, int] = {}
    for row in chatter:
        by_sub[row["subreddit"]] = by_sub.get(row["subreddit"], 0) + 1
    q = lambda sql: [tuple(r) for r in conn.execute(sql, (since,)).fetchall()]
    return {
        "days": days,
        "chatter_total": len(chatter),
        "hiring_posts": conn.execute("SELECT COUNT(*) FROM reddit_posts WHERE stream='hiring' AND seen_at>=?",
                                     (since,)).fetchone()[0],
        "themes": sorted(themes.items(), key=lambda x: -x[1]),
        "by_subreddit": sorted(by_sub.items(), key=lambda x: -x[1]),
        "top": [{"title": r["title"], "url": r["url"], "subreddit": r["subreddit"],
                 "score": r["score"], "comments": r["comments"]} for r in top],
        "postings_by_source": q("SELECT source, COUNT(*) FROM postings WHERE first_seen_at>=? "
                                "GROUP BY source ORDER BY 2 DESC"),
        "sightings_by_source": q("SELECT source, COUNT(*) FROM sightings WHERE first_seen_at>=? "
                                 "GROUP BY source ORDER BY 2 DESC"),
        "matches_by_arm": q("SELECT arm, COUNT(*) FROM matches WHERE matched_at>=? GROUP BY arm ORDER BY 2 DESC"),
        "matches_by_source": q("SELECT p.source, COUNT(*) FROM matches m JOIN postings p ON p.id=m.posting_id "
                               "WHERE m.matched_at>=? GROUP BY p.source ORDER BY 2 DESC"),
        "alerts_by_status": q("SELECT status, COUNT(*) FROM alerts WHERE created_at>=? GROUP BY status"),
        "callbacks": callback_stats(conn),     # all-time, per arm (PLAN-apply D9)
    }


def render(data: dict) -> tuple[str, str]:
    lines = [f"jobwatch weekly digest (last {data['days']} days)", ""]
    lines.append(f"Reddit market chatter: {data['chatter_total']} posts; hiring posts: {data['hiring_posts']}")
    if data["themes"]:
        lines.append("Themes: " + ", ".join(f"{t} {n}" for t, n in data["themes"]))
    if data["by_subreddit"]:
        lines.append("By subreddit: " + ", ".join(f"r/{s} {n}" for s, n in data["by_subreddit"]))
    if data["top"]:
        lines += ["", "Top posts (score/comments when known, else newest):"]
        for i, t in enumerate(data["top"], 1):
            extra = f" ({t['score']} pts, {t['comments']} comments)" if t["score"] is not None else ""
            lines.append(f"{i}. {t['title']} — r/{t['subreddit']}{extra}\n   {t['url']}")
    def table(name, rows):
        if rows:
            lines.append(f"{name}: " + ", ".join(f"{k} {v}" for k, v in rows))
    lines.append("")
    table("New postings by source", data["postings_by_source"])
    table("Sightings by source", data["sightings_by_source"])
    table("Matches by arm", data["matches_by_arm"])
    table("Matches by source", data["matches_by_source"])
    table("Alerts by status", data["alerts_by_status"])
    if data.get("callbacks"):
        lines += [""] + callback_lines(data["callbacks"])
    plain = "\n".join(lines)
    return plain, html.escape(plain).replace("\n", "<br/>")


def run_digest(config: Config, dry_run: bool = False, printer=print, now=None) -> dict:
    conn = dbm.connect(config.db_path)
    run_id = dbm.start_run(conn, "digest", None, dry_run)
    data = gather(conn, now=now)
    plain, _ = render(data)
    result = {"run_id": run_id, "printed": True, "error": None}
    printer(plain)                                  # no push channel: the text goes to the journal
    dbm.finish_run(conn, run_id, {**result, "chatter_total": data["chatter_total"]})
    conn.close()
    return result
