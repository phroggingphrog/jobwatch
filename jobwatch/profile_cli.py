"""`jobwatch profile adopt`: bring the current person's hand-made profile/ in as approved version 1 (rewrites nothing)."""
import sys


def register(sub):
    parser = sub.add_parser("profile", help="approved-profile maintenance for the current person (--user <name>)")
    parser.add_argument("action", choices=["adopt"], help="adopt: turn the existing profile/ files into version 1")


def handle(args):
    if getattr(args, "cmd", None) != "profile":
        return None
    from . import users
    from .candidate import intake
    from .candidate.contracts import CandidateError
    try:
        n = intake.adopt_existing(users.current(), actor="person")      # running this command is the person's own act
    except (intake.IntakeError, CandidateError) as exc:
        print(getattr(exc, "code", None) or str(exc), file=sys.stderr)
        return 1
    except (ValueError, OSError):
        print("profile_operation_unavailable", file=sys.stderr)
        return 1
    print(f"adopted profile as version {n}")
    return 0
