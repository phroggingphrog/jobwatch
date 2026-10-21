from __future__ import annotations

from .contracts import TargetPolicy, default_allowed_families


def default_policy() -> TargetPolicy:
    """The current person's target projection: every known family except the ones they do not want.
    The version string is stored in run keys, so it keeps its original identifier."""
    return TargetPolicy(version="owner-targets-v1", allowed_families=default_allowed_families())
