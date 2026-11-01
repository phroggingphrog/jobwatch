"""Retained pipeline routing through canonical confirmed-person eligibility.

The holistic rubric remains advisory comparison data. It cannot manufacture a
personal preference or override factual/eligibility checks.
"""
from __future__ import annotations

from typing import Literal

from ..schemas import GateDecision, JobFacts, MatchScore

# Kept for old configuration readers; never a personal exclusion threshold.
THRESHOLD = 3.8
Route = Literal['draft', 'archive', 'review']


def decide(facts: JobFacts, score: MatchScore, text: str, title: str = '',
           threshold: float = THRESHOLD, *, posting: dict | None = None,
           hours_policy: str = 'standard') -> tuple[Route, GateDecision]:
    from jobwatch.candidate.eligibility import evaluate_eligibility
    job = {**dict(posting or {}), **facts.model_dump(), 'title': title}
    result = evaluate_eligibility(job, ad_text=text)
    if result.status == 'eligible' and not facts.real_job:
        return 'review', GateDecision(passed=False, reason='real_job_unverified', score=score.overall)
    route: Route = {'eligible': 'draft', 'held': 'review', 'excluded': 'archive'}[result.status]
    return route, GateDecision(passed=route == 'draft', reason=result.reason, score=score.overall)
