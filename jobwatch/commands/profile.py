"""`jobwatch profile adopt|confirm`: approved-profile maintenance for the current person.

`confirm` is the only way discovery turns on. It shows the scope the person is about to authorise, refuses when
the scope is unusable, and records the approval as the person's own act. A model, an agent or an API client can
never pass `actor="person"`, so this command is the human step, not a step an automation may take.
"""
import sys


def register(sub):
    parser = sub.add_parser("profile", help="approved-profile maintenance for the current person (--user <name>)")
    parser.add_argument("action", choices=["adopt", "confirm"],
                        help="adopt: turn the existing profile/ files into version 1 (overwrite protection and history only; "
                             "it does not turn discovery on, onboarding does). "
                             "confirm <proposal_id>: show the discovery scope and confirm the proposal as the person")
    parser.add_argument("proposal_id", nargs="?", help="confirm: the draft proposal id shown by onboarding")
    parser.add_argument("--yes", action="store_true",
                        help="confirm: record the approval without asking again (running it is the person's own act)")


def _show(config, person, proposal_id):
    """Print exactly what confirming authorises. Returns the digests confirm() needs, or None when it must refuse."""
    from jobwatch.candidate import intake
    shown = intake.confirmation(person, proposal_id, config)
    scope = shown["scope"]
    print(f"proposal {proposal_id}")
    print(f"  role basis   {', '.join(scope.basis) or '(none)'}")
    print(f"  locations    {', '.join(scope.locations) or '(none)'}")
    print(f"  per day      {scope.daily_assessments} assessments, {scope.daily_token_ceiling:,} tokens charged")
    print(f"  authorises   {', '.join(shown['authorises'])}")
    print(f"  never        {', '.join(shown['does_not_authorise'])}")
    proposal = intake.load_proposal(person, proposal_id)
    if proposal.questions:
        print(f"  open questions ({len(proposal.questions)}) - recorded as open, not guessed:")
        for question in proposal.questions:
            print(f"    - {question.text[:100]}")
    if not scope.basis or not scope.locations:
        print("\nrefused: the scope needs at least one role basis and one location. "
              "Answer the open questions in onboarding, then confirm again.", file=sys.stderr)
        return None
    return shown


def _confirm(args):
    from jobwatch import users
    from jobwatch.candidate import intake
    from jobwatch.candidate.contracts import CandidateError
    from jobwatch.config import load_config
    person = users.current()
    if not args.proposal_id:
        print("usage: jobwatch profile confirm <proposal_id> [--yes]", file=sys.stderr)
        return 1
    try:
        shown = _show(load_config(), person, args.proposal_id)
    except (intake.IntakeError, CandidateError) as exc:
        print(getattr(exc, "code", None) or str(exc), file=sys.stderr)
        return 1
    except (ValueError, OSError):
        print("profile_operation_unavailable", file=sys.stderr)
        return 1
    if shown is None:
        return 1
    if not args.yes:
        print("\nType 'confirm' to record this approval, or anything else to stop: ", end="", file=sys.stderr, flush=True)
        if (sys.stdin.readline() or "").strip().lower() != "confirm":
            print("nothing changed", file=sys.stderr)
            return 1
    try:
        version = intake.confirm(person, args.proposal_id, proposal_digest=shown["proposal_digest"],
                                 scope_digest=shown["scope_digest"], actor="person", config=load_config())
    except (intake.IntakeError, CandidateError) as exc:
        print(getattr(exc, "code", None) or str(exc), file=sys.stderr)
        return 1
    except (ValueError, OSError):
        print("profile_operation_unavailable", file=sys.stderr)
        return 1
    live = intake.discovery_scope(person)
    print(f"confirmed profile version {version}")
    print(f"discovery scope {'is now open' if live is not None else 'is still closed'}")
    return 0 if live is not None else 1


def handle(args):
    if getattr(args, "cmd", None) != "profile":
        return None
    if args.action == "confirm":
        return _confirm(args)
    from jobwatch import users
    from jobwatch.candidate import intake
    from jobwatch.candidate.contracts import CandidateError
    person = users.current()
    try:
        n = intake.adopt_existing(person, actor="person")      # running this command is the person's own act
    except (intake.IntakeError, CandidateError) as exc:
        print(getattr(exc, "code", None) or str(exc), file=sys.stderr)
        return 1
    except (ValueError, OSError):
        print("profile_operation_unavailable", file=sys.stderr)
        return 1
    print(f"adopted profile as version {n}")
    return 0
