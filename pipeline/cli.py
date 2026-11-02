"""`jobwatch pipeline ...` (picked up by jobwatch.cli._extensions):

  jobwatch pipeline run [--limit N] [--no-ingest] [--posting ID]   one run: admit new (or named) jobs, move every job forward
  jobwatch pipeline status                          jobs per stage, open dead letters
  jobwatch pipeline dlq [--retry ID]                list the dead letter queue, or put one job back
  jobwatch pipeline dropped [--days N]              postings the early title check skipped, one JSON line each (default 7 days)
  jobwatch pipeline sort [--limit N]                name why each archived "not a target role" job is not one (BUI-96)
"""
from __future__ import annotations

import json


def register(sub) -> None:
    p = sub.add_parser("pipeline", help="deterministic state pipeline: ingest -> extract -> score -> gate -> draft -> form map")
    p.add_argument("action", choices=["run", "status", "dlq", "sort", "dropped"])
    p.add_argument("--limit", type=int, default=None, help="max unfinished jobs to move this run")
    p.add_argument("--no-ingest", action="store_true", help="skip node 1 (only move jobs already admitted)")
    p.add_argument("--posting", type=int, action="append", help="admit these posting ids in node 1 (repeatable)")
    p.add_argument("--days", type=int, default=7, help="with dropped: how many days back")
    p.add_argument("--retry", type=int, default=None, help="with dlq: put this DLQ entry's job back in its stage")


def handle(args) -> int | None:
    if getattr(args, "cmd", None) != "pipeline":
        return None
    from jobwatch.util import adtext as adtext
    from jobwatch import db as dbm
    from jobwatch.config import load_config

    from . import graph, store
    config = load_config(args.config_dir)
    conn = dbm.connect(config.db_path)
    store.ensure(conn)
    if args.action == "status":
        dlq = conn.execute("SELECT COUNT(*) FROM pipeline_dlq WHERE resolved_at IS NULL").fetchone()[0]
        print(json.dumps({"stages": store.counts(conn), "dlq_open": dlq}))
        return 0
    if args.action == "dropped":
        from jobwatch.web.queries import dropped_by_title
        for row in dropped_by_title(conn, args.days):
            print(json.dumps(row))
        return 0
    if args.action == "dlq":
        if args.retry is not None:
            print(json.dumps({"requeued_posting": store.retry_dlq(conn, args.retry)}))
            conn.commit()
            return 0
        for r in conn.execute("SELECT d.id, d.posting_id, d.node, d.attempts, substr(d.error,1,160) e, p.title "
                              "FROM pipeline_dlq d JOIN postings p ON p.id=d.posting_id WHERE d.resolved_at IS NULL "
                              "ORDER BY d.id"):
            print(f"{r['id']:>5} posting {r['posting_id']:>6} {r['node']:<9} x{r['attempts']}  {r['title'][:50]}  | {r['e']}")
        return 0
    from jobwatch import discovery_gate
    if not discovery_gate.allowed("pipeline " + args.action):      # run and sort assess; no confirmed scope, no assessment
        return 0
    # run: one at a time (shares the reader's lock, so it never runs beside a review or another pipeline run)
    with adtext.review_lock(adtext.lock_path(config)) as got:
        if not got:
            print(json.dumps({"skipped": "busy"}))
            return 0
        if args.action == "sort":
            from .nodes import sort
            s = graph.Settings.from_config(config)
            print(json.dumps(sort.run(conn, graph.LLM(), s.sort_model, limit=args.limit)))
            return 0
        print(json.dumps(graph.run_once(conn, str(config.db_path), config, ingest_new=not args.no_ingest,
                                        limit=args.limit, posting_ids=args.posting), default=str))
    return 0
