"""CLI hooks for the AI ad reader (picked up by cli._extensions):

  jobwatch review [--limit N] [--posting ID ...] [--model M] [--workers N]   read ads not yet read, store verdicts
  jobwatch review --refetch [--fetch N]                                     also fetch ads the fetch log gave up on
  jobwatch review recall [--limit N]                                        AI judges non-matching postings by meaning
  jobwatch review sort                                                      AI names why each "not a target role" job is not one
  jobwatch review rederive                                                  re-apply the hiding rules to stored model answers
  jobwatch review stats                                                     counts of verdicts and hide reasons
"""
from __future__ import annotations

import json


def register(sub) -> None:
    p = sub.add_parser("review", help="AI reads the full job ads and decides (stores verdicts in ad_reviews)")
    p.add_argument("action", nargs="?", choices=["run", "stats", "rederive", "recall", "sort"], default="run")
    p.add_argument("--limit", type=int, default=None, help="max ads this run (default: all pending)")
    p.add_argument("--posting", type=int, action="append", help="review this posting id again (repeatable)")
    p.add_argument("--redo", action="store_true", help="look at every match again (after editing the profile); only ads whose text, model or profile changed are re-read")
    p.add_argument("--model", default=None, help="override reader.model (a claude/ combo)")
    p.add_argument("--workers", type=int, default=None)
    p.add_argument("--fetch", type=int, default=None, help="max Seek ad pages to fetch this run (default: reader.seek_fetches_per_run)")
    p.add_argument("--refetch", action="store_true", help="fetch the pending ads' pages again even when the fetch log says wait or gave up (--posting does the same for its ads)")


def handle(args) -> int | None:
    if getattr(args, "cmd", None) != "review":
        return None
    from . import db as dbm
    from . import reader
    from .config import load_config
    config = load_config(args.config_dir)
    conn = dbm.connect(config.db_path)
    if args.action == "stats":
        for row in conn.execute("SELECT verdict, COALESCE(hide_reason,'-') r, COUNT(*) n, ROUND(AVG(fit)) f "
                                "FROM ad_reviews GROUP BY 1,2 ORDER BY 3 DESC"):
            print(f"{row['verdict']:<7} {row['r']:<22} {row['n']:>5}   avg fit {row['f']}")
        n = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        d = conn.execute("SELECT COUNT(*) FROM ad_reviews").fetchone()[0]
        kinds = dict(conn.execute("SELECT text_source, COUNT(*) FROM ad_reviews GROUP BY 1").fetchall())
        print(f"read {d} of {n} matches; {kinds.get('teaser', 0)} from a teaser only, "
              f"{kinds.get('partial', 0)} from a cut text only (ad body not fetched)")
        return 0
    if args.action in ("run", "recall", "sort"):
        from . import discovery_gate
        if not discovery_gate.allowed("review " + args.action):
            return 0
        return _locked(args, config, conn)
    if args.action == "rederive":
        return _rederive(config, conn)
    return None


def _locked(args, config, conn) -> int:
    """`review` and `review recall`, one at a time: a second run (or the pipeline hook) skips with a note."""
    from jobwatch.util import adtext as adtext
    from jobwatch import reader
    with adtext.review_lock(adtext.lock_path(config)) as got:
        if not got:
            print(json.dumps({"skipped": "busy", "note": "another review or recall run holds review.lock"}))
            return 0
        if args.action == "sort":
            print(json.dumps(reader.sort_not_target(conn, config, limit=args.limit, printer=print)))
            return 0
        if args.action == "recall":
            from . import recall
            print(json.dumps(recall.triage_new(conn, config, limit=args.limit if args.limit is not None else None,
                                               printer=print)))
            return 0
        if args.model:
            config.settings.setdefault("reader", {})["model"] = args.model
        if args.fetch is not None:
            config.settings.setdefault("reader", {})["seek_fetches_per_run"] = args.fetch
        if args.workers:
            config.settings.setdefault("reader", {})["workers"] = args.workers
        stats = reader.review_pending(conn, config, limit=args.limit if args.limit is not None else 10**6,
                                      posting_ids=args.posting, printer=print, redo=args.redo,
                                      refetch=bool(getattr(args, "refetch", False)))                  # no time limit
        print(json.dumps(stats))
        return 0


def _rederive(config, conn) -> int:
    """`review rederive` rewrites every verdict, so it never runs beside a review: busy = say so, change nothing."""
    from jobwatch.util import adtext as adtext
    from jobwatch import reader
    with adtext.review_lock(adtext.lock_path(config)) as got:
        if not got:
            print("another review or recall run holds review.lock; rederive changed nothing, try again when it ends")
            return 1
        print(json.dumps(reader.rederive(conn, config)))
        return 0
