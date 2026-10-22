"""One check for every command that collects or assesses on its own: the current person's profile must have been
confirmed with its scope shown (candidate.intake.discovery_scope)."""
from __future__ import annotations

SKIPPED = "no_confirmed_profile"


def profile_location_rule(posting, policy) -> str | None:
    """Conservative metadata admission from confirmed preferences, never a default home.

    Unknown locations remain assessable. This prefilter does not certify practical
    eligibility; the full-ad gate checks its quoted location and constraints.
    """
    from .candidate.policy import exclusion_hit
    from pipeline.agentic.location import location_verdict, _REMOTE_WORDS
    text = ' '.join(str(value) for value in (posting.location, posting.state) if value)
    remote = bool(posting.remote) or bool(_REMOTE_WORDS.search(text))
    if remote:
        text += ' remote'
    if exclusion_hit(policy, family=None, company='', title='', location_text=text,
                     remote=remote, hours='') is not None:
        return None
    if not policy.regions:
        return 'profile_location_unknown'
    verdict = location_verdict(text, frozenset(policy.regions),
        remote_fit=remote and policy.remote_ok is not False, remote_ok=policy.remote_ok)
    return {'in':'profile_region', 'remote':'profile_remote',
            'unknown':'profile_location_unknown', 'outside':None}[verdict]


def allowed(cmd: str) -> bool:
    from . import users
    from .candidate import intake
    who = users.current()
    if intake.discovery_scope(who) is not None:
        return True
    print(f"{cmd}: skipped {who}: {SKIPPED} (confirm the profile and its scope first)")
    return False
