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
import os
import sys
import time
import uuid

from . import collectors as registry
from . import db as dbm
from .config import load_config
from . import discovery_gate


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
                 "jobwatch.web.cli_ext", "jobwatch.review_cli", "pipeline.cli", "jobwatch.preference_cli", "jobwatch.profile_cli",
                 "jobwatch.baseline_cli", "jobwatch.evaluation_cli", "jobwatch.user_cli", "jobwatch.notifier.cli",
                 "jobwatch.prescreen.cli"):
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
    # People run one after another inside one unit: split its time over those who will actually run (a person
    # without a confirmed scope is skipped in ~0 s), so the whole run stays inside the unit's TimeoutStartSec.
    from . import pipeline
    unit_seconds = pipeline.SLOW_UNIT_BUDGET_S if '--tier' in argv and argv[argv.index('--tier')+1] == 'slow' else pipeline.UNIT_BUDGET_S
    slow = '--tier' in argv and argv[argv.index('--tier')+1] == 'slow'
    invocation_deadline = time.time() + unit_seconds
    # The one absolute stop: a started assessment may run past its person's window (when that person has no per-job
    # time limit) but never past this. Override with JOBWATCH_HARD_STOP_SECONDS; keep it below the unit's timeout.
    from pipeline.agentic import execution as _execution
    try:
        hard_seconds = float(os.environ.get('JOBWATCH_HARD_STOP_SECONDS') or (pipeline.SLOW_HARD_STOP_S if slow else pipeline.HARD_STOP_S))
    except ValueError:
        hard_seconds = pipeline.SLOW_HARD_STOP_S if slow else pipeline.HARD_STOP_S
    positional = [a for i, a in enumerate(argv) if not a.startswith('-') and (i == 0 or argv[i-1] != '--config-dir')]
    timer_run = bool(positional) and positional[0] in ('read', 'run')   # never for the long-running web service
    hard_stop = _execution.HARD_STOP.set(time.time() + hard_seconds if timer_run else None)
    from .candidate import intake
    running = sum(1 for name in names if name and intake.discovery_scope(name) is not None)
    share = pipeline.PEOPLE_SHARE.set(1.0 / max(1, running))
    try:
        for name in names:
            with (users.use(name) if name else contextlib.nullcontext()):
                rc = _main(argv, deadline=min(invocation_deadline, time.time()+unit_seconds/max(1,running))) or rc
    finally:
        pipeline.PEOPLE_SHARE.reset(share)
        _execution.HARD_STOP.reset(hard_stop)
    return rc


def _main(argv: list[str], *, deadline=None) -> int:
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
    p_run.add_argument('--collect-only', action='store_true', help='Publish postings without running assessment')
    sub.add_parser("read", help="AI reader only: read and judge waiting ads, no collecting")
    p_exit = sub.add_parser('service-exit', help='Record an abnormal managed worker exit and flush error notifications')
    p_exit.add_argument('--unit', required=True)
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

    if args.cmd == 'service-exit':
        from pipeline.agentic import incidents
        conn = dbm.connect(config.db_path)
        try:
            import os
            result = os.environ.get('SERVICE_RESULT', 'success')
            if result != 'success':
                incidents.reconcile_service_exit(conn, unit=args.unit,
                    reason='service_timeout' if result == 'timeout' else 'worker_interrupted')
            incidents.flush_notifications(conn)
        finally:
            conn.close()
        return 0

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
    if args.cmd in ("read", "run") and not discovery_gate.allowed(args.cmd):
        return 0
    if args.cmd == "read":
        # 2026-10-19 owner: "make the reader read more ads per run". The collect runs leave the reader ~4 min, so it
        # read 2-5 ads and skipped ~17 each time; this run is the reader alone with the whole 13 min.
        from pipeline.agentic import service as agentic
        from .pipeline import PEOPLE_SHARE, UNIT_BUDGET_S
        conn = dbm.connect(config.db_path)
        from . import expiry
        from .profile_check import check as _check_profile
        for problem in _check_profile():
            print("profile check:", problem)
        part = PEOPLE_SHARE.get()                     # --user all: this person's share of the unit
        from pipeline.agentic import incidents
        import os
        run_id = 'reader-' + uuid.uuid4().hex
        deadline = deadline if deadline is not None else time.time()+UNIT_BUDGET_S*part
        incidents.reconcile_known_failures(conn)
        incidents.begin_run(conn, run_id, unit=os.environ.get('JOBWATCH_SERVICE_UNIT', 'manual'))
        state = 'completed'
        try:
            incidents.mark_phase(conn, run_id, 'expiry')
            phase_start = time.monotonic()
            swept = expiry.sweep(conn, max_seconds=max(0,min(180*part, deadline-time.time())))
            incidents.mark_phase(conn, run_id, 'expiry', completed=True)
            print({'expiry': swept, 'phase_seconds': {'expiry': time.monotonic()-phase_start}}, flush=True)
            result = agentic.after_collect(conn, config, max_seconds=max(0,deadline-time.time()),
                deadline=deadline, run_id=run_id)
            print(result, flush=True)
        except Exception as exc:
            state = 'failed'
            incidents.report(conn, run_id=run_id, reason=getattr(exc,'code','execution_failed'), phase='reader')
            raise
        finally:
            incidents.end_run(conn, run_id, state=state)
            conn.close()
        return 0
    if args.cmd == "run":
        from .pipeline import run
        if args.dry_run:
            summary = run(config, args.tier, dry_run=True, only=args.only, limit=args.limit,
                assess=False, deadline=deadline)
            _print_run(summary)
            return 0
        from pipeline.agentic import incidents
        import os
        conn = dbm.connect(config.db_path)
        run_id = 'collector-' + uuid.uuid4().hex
        incidents.begin_run(conn, run_id, unit=os.environ.get('JOBWATCH_SERVICE_UNIT', 'manual'))
        state = 'completed'
        try:
            incidents.mark_phase(conn, run_id, 'collection')
            summary = run(config, args.tier, dry_run=args.dry_run, only=args.only, limit=args.limit,
                assess=not args.collect_only, deadline=deadline, run_id=run_id)
        except Exception as exc:
            state = 'failed'
            incidents.report(conn, run_id=run_id, reason=getattr(exc,'code','execution_failed'), phase='collection')
            raise
        finally:
            incidents.end_run(conn, run_id, state=state)
            conn.close()
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
