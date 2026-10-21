"""Node 4: quality gate and routing. Plain code; the order of the checks is fixed.

Legal and owner rules come first (they are absolute, whatever the score), then the score threshold:
  not a real job -> archive | work rights that exclude a student-visa holder (quote checked in the ad) -> archive |
  a NOT WANTED family -> archive | senior or 4+ years -> archive | full-time only and not a program -> archive |
  score < threshold (3.8) -> archive | otherwise -> drafting.
A rights claim the ad's words do not back, or a word rule that contradicts the model's reading of the same sentence,
is never guessed: remaining non-rights checks may archive it; only an otherwise-passing job goes to the dead
letter queue for review. Blocking quotes may be corroborated by an overlapping deterministic rule, or by
rejoining a split-off first letter of an allowlisted rights keyword.
"""
from __future__ import annotations

import re
from typing import Literal

from jobwatch.reader import _overlaps, blocking_quote, quote_in_text, rights_backstop, unrestricted_backstop

from ..schemas import BLOCKING_RIGHTS, GateDecision, JobFacts, MatchScore

THRESHOLD = 3.8
HIDE_MIN_YEARS = 4
Route = Literal["draft", "archive", "review"]


def _rejoin_rights_keyword(quote: str) -> str:
    """Repair split first letters only for known rights words, not arbitrary ad text."""
    # Match only valid repairs so an article such as "a P" cannot consume the
    # first letter of a following "P ermanent" match.
    return re.sub(
        r"\b(?:f\s+ull|u\s+nrestricted|u\s+nlimited|p\s+ermanent|c\s+itizen(?:s|ship)?)\b",
        lambda match: re.sub(r"\s+", "", match[0]), quote, flags=re.IGNORECASE,
    )


def decide(facts: JobFacts, score: MatchScore, text: str, title: str = "",
           threshold: float = THRESHOLD) -> tuple[Route, GateDecision]:
    overall = score.overall
    hay = f"{title}\n{text}"

    def stop(reason: str, route: Route = "archive"):
        return route, GateDecision(passed=False, reason=reason, score=overall)

    if not facts.real_job:
        return stop("not_a_real_job")
    rights, quote = facts.work_rights.requirement, facts.work_rights.quote
    rule = rights_backstop(text, title) or unrestricted_backstop(text, title)
    hold = None
    if rights in BLOCKING_RIGHTS:
        if (quote and quote_in_text(quote, hay, fuzzy=True) and
                (blocking_quote(quote) or blocking_quote(_rejoin_rights_keyword(quote)) or
                 (rule and _overlaps(quote, rule)))):
            return stop(f"work_rights:{rights}")
        hold = "rights_claim_unverified"
    elif rule:
        if quote and _overlaps(quote, rule):
            hold = "rights_rule_disagrees"
        else:
            return stop("work_rights:found_by_rule")
    if score.wanted == "not_wanted":
        return stop("not_target")
    if facts.seniority == "senior" or (facts.min_years or 0) >= HIDE_MIN_YEARS:
        return stop("too_senior")
    if facts.hours == "full_time_only" and not facts.program:
        return stop("full_time_only")
    if overall < threshold:
        return stop("low_score")
    if hold:
        return stop(hold, "review")
    return "draft", GateDecision(passed=True, reason="passed", score=overall)
