"""One check for every command that collects or assesses on its own: the current person's profile must have been
confirmed with its scope shown (candidate.intake.discovery_scope)."""
from __future__ import annotations

SKIPPED = "no_confirmed_profile"


def allowed(cmd: str) -> bool:
    from . import users
    from .candidate import intake
    who = users.current()
    if intake.discovery_scope(who) is not None:
        return True
    print(f"{cmd}: skipped {who}: {SKIPPED} (confirm the profile and its scope first)")
    return False
