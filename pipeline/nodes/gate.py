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
           threshold: float = THRESHOLD, *, posting: dict | None = None) -> tuple[Route, GateDecision]:
    if not facts.real_job:
        return 'archive', GateDecision(passed=False, reason='not_a_real_job', score=score.overall)
    from jobwatch.candidate.eligibility import evaluate_eligibility
    job = {**dict(posting or {}), **facts.model_dump(), 'title': title}
    result = evaluate_eligibility(job, ad_text=text)
    if (posting or {}).get('track') == 'undergraduate' and result.status != 'eligible':
        # Programs may be full-time: hours alone never hide one. Shown with a note to check visa hours.
        from pipeline.tracks import HOURS_REASONS
        hours_only = result.reason in HOURS_REASONS or (result.reason == 'eligibility_unknown'
                                                         and set(result.questions) <= HOURS_REASONS)
        if hours_only:
            return 'draft', GateDecision(passed=True, reason='eligible_check_hours', score=score.overall)
    route: Route = {'eligible': 'draft', 'held': 'review', 'excluded': 'archive'}[result.status]
    return route, GateDecision(passed=route == 'draft', reason=result.reason, score=score.overall)
