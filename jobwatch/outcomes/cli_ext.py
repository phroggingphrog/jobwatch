"""CLI hook: `jobwatch outcomes [--dry-run] [--show]` (picked up by cli._extensions)."""
from __future__ import annotations

import sys


def register(sub) -> None:
    p = sub.add_parser("outcomes", help="read-only mail scan -> outcome proposals (approve or reject them on the web Inbox)")
    p.add_argument("--dry-run", action="store_true",
                   help="scan and classify only: no DB writes, no LLM calls; prints counts")
    p.add_argument("--show", action="store_true",
                   help="with --dry-run, also print the proposals (contains mail subjects)")


def handle(args) -> int | None:
    if getattr(args, "cmd", None) != "outcomes":
        return None
    from ..config import load_config
    from .sync import run_outcomes
    stats = run_outcomes(load_config(args.config_dir), dry_run=args.dry_run, show=args.show)
    print("outcomes: " + " ".join(f"{k}={v}" for k, v in stats.items() if k != "error"))
    if stats.get("error"):
        print(f"outcomes error: {stats['error']}", file=sys.stderr)
        return 1
    return 0
