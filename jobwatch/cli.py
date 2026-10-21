"""jobwatch CLI.

  jobwatch run --tier fast|slow|all [--dry-run] [--only <collector>] [--limit N]
  jobwatch read                      AI reader only, no collecting (its own timer)
  jobwatch digest [--dry-run]
  jobwatch health
  jobwatch init-db
"""
from __future__ import annotations

import argparse
import logging
import sys

from . import collectors as registry
from . import db as dbm
from .config import load_config


def _print_run(summary: dict) -> None:
    print(f"run {summary['run_id']}: {summary['requests']} HTTP requests")
    print(f"{'collector':22} {'status':8} {'fetched':>7} {'AU kept':>7} {'STATE':>5} {'new':>5} {'matched':>7} "
          f"{'queued':>6} {'secs':>6}  errors")
    for c in summary["collectors"]:
        err = "; ".join(c["errors"])[:110]
        print(f"{c['collector']:22} {c['status']:8} {c['fetched']:>7} {c['au_kept']:>7} {c.get('vic', 0):>5} "
              f"{c['new']:>5} {c['matched']:>7} {c['queued']:>6} {c.get('latency_ms', 0) / 1000:>6.1f}  {err}")
    print(f"alerts: {summary['alerts']}; pruned={summary['pruned']}")


def all_failed(summary: dict) -> bool:
    """Every collector in the run errored -> exit 1 so systemd marks the unit failed.
    Partial failures stay exit 0 (`jobwatch health` and the Sources page show them)."""
    cols = summary.get("collectors") or []
    return bool(cols) and all(c.get("status") == "error" for c in cols)


def _extensions():
    """Optional sub-command packages (apply layer, outcomes). Each module exposes
    register(subparsers) and handle(args) -> int | None (None = not mine)."""
    import importlib
    mods = []
    for name in ("jobwatch.apply.cli_ext", "jobwatch.outcomes.cli_ext",
                 "jobwatch.web.cli_ext", "jobwatch.review_cli", "pipeline.cli", "jobwatch.preference_cli", "jobwatch.profile_cli"):
        try:
            mods.append(importlib.import_module(name))
        except ModuleNotFoundError as exc:
            if exc.name and not name.startswith(exc.name):
                raise
    return mods


def main(argv: list[str] | None = None) -> int:
    """`jobwatch --user <name|all> <command>`: run as one person, or once for every person."""
    import contextlib
    from . import users
    argv = list(sys.argv[1:] if argv is None else argv)
    who = None
    if "--user" in argv:
        i = argv.index("--user")
        who = argv[i + 1]
        del argv[i:i + 2]
    names = (users.list_users() if who == "all" else [who]) if who else [None]
    rc = 0
    for name in names:
        with (users.use(name) if name else contextlib.nullcontext()):
            rc = _main(argv) or rc
    return rc


def _discovery_on(cmd: str) -> bool:
    """Discovery (collection and assessment) runs only for a person whose current profile was confirmed with its scope."""
    from . import users
    from .candidate import intake
    who = users.current()
    if intake.discovery_scope(who) is not None:
        return True
    print(f"{cmd}: skipped {who}: no_confirmed_profile (confirm the profile and its scope first)")
    return False


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="jobwatch", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config-dir", help="config directory (default: <repo>/config)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="collect, filter, dedupe, alert")
    p_run.add_argument("--tier", choices=["fast", "slow", "all"], default="fast")
    p_run.add_argument("--dry-run", action="store_true", help="store postings and matches, but leave new matches queued (not on the board)")
    p_run.add_argument("--only", choices=registry.COLLECTORS, help="run one collector")
    p_run.add_argument("--limit", type=int, help="max postings per collector (also stops requests early)")
    sub.add_parser("read", help="AI reader only: read and judge waiting ads, no collecting")
    chk = sub.add_parser("check", help="list misspelled or wrong lines in your profile and settings files")
    chk.add_argument("--code", action="store_true", help="also list places where your own facts appear in the code")
    p_dig = sub.add_parser("digest", help="weekly Reddit chatter + stats digest")
    p_dig.add_argument("--dry-run", action="store_true")
    sub.add_parser("health", help="show per-collector health")
    sub.add_parser("init-db", help="create/migrate the SQLite database")
    exts = _extensions()
    for ext in exts:
        ext.register(sub)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    for noisy in ("JobSpy", "jobspy", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    config = load_config(args.config_dir)

    if args.cmd == "init-db":
        conn = dbm.connect(config.db_path)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        print(f"db ready: {config.db_path} (schema v{version}, journal={mode})")
        return 0
    if args.cmd == "health":
        conn = dbm.connect(config.db_path)
        rows = conn.execute("SELECT * FROM source_health ORDER BY collector").fetchall()
        if not rows:
            print("no health rows yet (run a collector first)")
        for r in rows:
            print(f"{r['collector']:22} {r['last_status'] or '-':8} count={r['last_count']} "
                  f"fails={r['consecutive_failures']} last_ok={r['last_ok_at']} "
                  f"latency={r['last_latency_ms']}ms {('err: ' + r['last_error'][:100]) if r['last_error'] else ''}")
        return 0
    if args.cmd == "digest":
        from .digest import run_digest
        result = run_digest(config, dry_run=args.dry_run)
        if result["error"]:
            print(f"digest error: {result['error']}", file=sys.stderr)
            return 1
        return 0
    if args.cmd == "check":
        from .profile_check import check
        problems = check()
        if args.code:
            from .profile_check import check_code
            problems += check_code()
        print("\n".join("- " + p for p in problems) if problems else "Profile and settings: all lines known and well formed.")
        return 1 if problems else 0
    if args.cmd in ("read", "run") and not _discovery_on(args.cmd):
        return 0
    if args.cmd == "read":
        # 2026-10-19 owner: "make the reader read more ads per run". The collect runs leave the reader ~4 min, so it
        # read 2-5 ads and skipped ~17 each time; this run is the reader alone with the whole 13 min.
        from pipeline.agentic import service as agentic
        from .pipeline import UNIT_BUDGET_S
        conn = dbm.connect(config.db_path)
        from . import expiry
        from .profile_check import check as _check_profile
        for problem in _check_profile():
            print("profile check:", problem)
        swept = expiry.sweep(conn, max_seconds=180)  # stale-ad check first, at most 3 of the reader's minutes
        print({"expiry": swept})
        print(agentic.after_collect(conn, config, max_seconds=max(60, UNIT_BUDGET_S - 180)))
        return 0
    if args.cmd == "run":
        from .pipeline import run
        summary = run(config, args.tier, dry_run=args.dry_run, only=args.only, limit=args.limit)
        _print_run(summary)
        if all_failed(summary):
            print("every collector in this run errored", file=sys.stderr)
            return 1
        return 0
    for ext in _extensions():
        rc = ext.handle(args)
        if rc is not None:
            return rc
    return 2


if __name__ == "__main__":
    sys.exit(main())
