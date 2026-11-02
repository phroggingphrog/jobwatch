"""Shared assessment semantics: fit is advisory; only explicit conflicts exclude.

This record describes an assessment, not authority to submit an application.
Audit gaps belong in unknowns and technical failures belong in errors. Neither
silently turns a positive career goal into a hard restriction.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


@dataclass(frozen=True)
class AssessmentDecision:
    fit_score: float | None
    explicit_conflicts: tuple[str, ...]
    unknowns: tuple[str, ...]
    errors: tuple[str, ...]
    recommendation: Literal['consider', 'exclude', 'needs_clarification', 'retry']
    completeness: Literal['complete', 'partial', 'unavailable']

    def model_dump(self, **kwargs):
        return asdict(self)


def build_decision(*, fit_score=None, explicit_conflicts=(), unknowns=(), errors=(), recommendation=None):
    """One precedence for all assessment paths, without a minimum-fit gate."""
    def values(items):
        return tuple(dict.fromkeys(str(item) for item in items if item))
    conflicts, gaps, failures = values(explicit_conflicts), values(unknowns), values(errors)
    if conflicts:
        choice = 'exclude'
    elif failures and fit_score is None:
        choice = 'retry'
    elif gaps:
        choice = 'needs_clarification'
    else:
        choice = 'consider'
    # Recommendations supplied by a model cannot grant exclusion authority.
    return AssessmentDecision(fit_score, conflicts, gaps, failures, choice,
        'unavailable' if failures and fit_score is None else 'partial' if gaps or failures else 'complete')
