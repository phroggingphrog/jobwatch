"""CLI extension (picked up by jobwatch.cli._extensions):

  jobwatch draft <match_id> [--actor-event SRC]   run the draft chain (prints a summary, no personal text)
  jobwatch reindex [--dry-run]                    rebuild the apply tables from the ledger
  jobwatch profile-check                          profile/ perms, files, evidence verbatim check (counts only)
"""
from __future__ import annotations

import json
import stat


def register(sub) -> None:
    p = sub.add_parser("draft", help="draft a tailored CV + cover letter for a match (apply layer)")
    p.add_argument("match_id", type=int)
    p.add_argument("--actor-event", default="cli", help="source of the owner's proceed (default: cli)")
    p = sub.add_parser("reindex", help="rebuild apply tables from the append-only ledger")
    p.add_argument("--dry-run", action="store_true")
    sub.add_parser("profile-check", help="check the read-only candidate profile (counts only)")


def handle(args) -> int | None:
    if args.cmd not in ("draft", "reindex", "profile-check"):
        return None
    from .. import db as dbm
    from ..config import load_config
    config = load_config(getattr(args, "config_dir", None))
    if args.cmd == "profile-check":
        return _profile_check()
    conn = dbm.connect(config.db_path)
    if args.cmd == "reindex":
        from .. import ledger
        try:
            counts = ledger.reindex(conn, dry_run=args.dry_run)
        except ledger.ReindexRefused as exc:
            print(f"reindex refused: {exc}")
            return 1
        print(("would rebuild " if args.dry_run else "rebuilt ") + json.dumps(counts))
        return 0
    from .chain import DraftRefused, draft_status, start_draft
    try:
        app_id = start_draft(conn, args.match_id, args.actor_event)
    except DraftRefused as exc:
        print(f"draft refused: {exc}")
        return 1
    st = draft_status(conn, app_id)
    m = dict(st.get("metrics") or {})
    m.pop("posting", None)     # keep stdout to metrics and paths
    m.pop("gaps", None)
    print(json.dumps({"application_id": app_id, "application_status": st.get("application_status"),
                      "draft_status": st["status"], "error": st.get("error"), "files": st.get("files"),
                      **m}, indent=2))
    return 0 if st["status"] == "ready" else 1


def _profile_check() -> int:
    from .evidence import KINDS, check_evidence, load_profile
    from .paths import profile_dir
    pdir = profile_dir()
    problems = []
    if not pdir.is_dir():
        print("profile dir missing; run scripts/seed_profile.py")
        return 1
    if stat.S_IMODE(pdir.stat().st_mode) != 0o700:
        problems.append("profile dir is not mode 700")
    for f in sorted(pdir.iterdir()):
        if f.is_file() and not f.is_symlink() and stat.S_IMODE(f.stat().st_mode) & 0o077:
            problems.append(f"{f.name} is readable by others")
    prof = load_profile(pdir)
    bad = check_evidence(pdir, prof.evidence)
    by_kind = {k: sum(1 for e in prof.evidence if e["kind"] == k) for k in KINDS}
    print(f"profile: {len(list(pdir.iterdir()))} entries; evidence {len(prof.evidence)} items {by_kind}; "
          f"verbatim failures {len(bad)}; header lines {len(prof.header_lines)}")
    for p in problems:
        print(f"problem: {p}")
    return 1 if problems or bad else 0
