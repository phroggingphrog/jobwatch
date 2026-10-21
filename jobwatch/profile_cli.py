"""`jobwatch profile adopt | confirm-scope`: approved-profile maintenance for the current person."""
import sys


def register(sub):
    parser = sub.add_parser("profile", help="approved-profile maintenance for the current person (--user <name>)")
    parser.add_argument("action", choices=["adopt", "confirm-scope"],
                        help="adopt: turn the existing profile/ files into version 1; "
                             "confirm-scope: show the search scope (no options) or confirm it (--base-version, --scope-digest)")
    parser.add_argument("--base-version", type=int, help="confirm-scope: the version shown")
    parser.add_argument("--scope-digest", help="confirm-scope: the digest shown, exactly")


def handle(args):
    if getattr(args, "cmd", None) != "profile":
        return None
    from . import users
    from .candidate import intake
    from .candidate.contracts import CandidateError
    from .config import load_config
    person = users.current()
    try:
        if args.action == "confirm-scope":
            if args.base_version is None and args.scope_digest is None:
                shown = intake.scope_confirmation(person, load_config(getattr(args, "config_dir", None)))
                print(f"base_version: {shown['base_version']}\nscope_digest: {shown['scope_digest']}")
                print("scope:", shown["scope"].model_dump_json())
                print("authorises:", "; ".join(shown["authorises"]))
                print("does not authorise:", "; ".join(shown["does_not_authorise"]))
                return 0
            if args.base_version is None or args.scope_digest is None:
                print("confirm-scope needs both --base-version and --scope-digest", file=sys.stderr)
                return 2
            n = intake.confirm_scope(person, base_version=args.base_version, scope_digest=args.scope_digest,
                                     actor="person", config=load_config(getattr(args, "config_dir", None)))      # running this command is the person's own act
            print(f"confirmed scope as version {n}; discovery is on")
            return 0
        n = intake.adopt_existing(person, actor="person")      # running this command is the person's own act
    except (intake.IntakeError, CandidateError) as exc:
        print(getattr(exc, "code", None) or str(exc), file=sys.stderr)
        return 1
    except (ValueError, OSError):
        print("profile_operation_unavailable", file=sys.stderr)
        return 1
    print(f"adopted profile as version {n}")
    return 0
