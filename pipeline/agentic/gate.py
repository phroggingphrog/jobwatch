"""Deterministic safety and policy admission for agentic evaluations."""
from __future__ import annotations

import hashlib
import re

from jobwatch.candidate.contracts import TargetPolicy
from jobwatch.candidate.policy import DecisionPolicy
from pipeline.agentic.contracts import (
    AgenticError, AgenticEvaluation, AgenticGateDecision, RunKey, SourceCitation,
)


def _hold(evaluation: AgenticEvaluation, reason: str) -> AgenticGateDecision:
    return AgenticGateDecision(route="hold", reason=reason,
                               global_score=evaluation.global_score, run_key=evaluation.run_key)




def _archive(evaluation: AgenticEvaluation, reason: str) -> AgenticGateDecision:
    return AgenticGateDecision(route="archive", reason=reason,
                               global_score=evaluation.global_score, run_key=evaluation.run_key)


def _draft(evaluation: AgenticEvaluation) -> AgenticGateDecision:
    return AgenticGateDecision(route="draft", reason="eligible",
                               global_score=evaluation.global_score, run_key=evaluation.run_key)


def _verified(citation: SourceCitation | None, ad_text: str, ad_hash: str) -> bool:
    if citation is None:
        return False
    try:
        checked = SourceCitation.model_validate(citation.model_dump())
        actual = hashlib.sha256(ad_text.encode("utf-8")).hexdigest()
        return (checked.source_id in {"ad", "jd"} and checked.content_hash == actual == ad_hash
                and checked.quote in ad_text)
    except Exception:
        return False


def _logistics(requirement, hours_exempt: bool = False) -> bool:
    """A requirement about how to apply, where or when to work, rather than what the candidate can do or is
    eligible for. Work rights, citizenship, clearances, licences and qualifications are never logistics."""
    text = " ".join(filter(None, [requirement.id, requirement.text,
                                  requirement.jd_signal.quote if requirement.jd_signal else ""]))
    if re.search(r"citizen|permanent[ _-]resid|right[ _-]to[ _-]work|work(?:ing)?[ _-]rights|visa|clearance|licen[cs]e|"
                 r"degree|qualif|certif|registration|police|working with children|WWCC", text, re.I):
        return False
    if re.search(r"\b(?:application[ _-]documents?|resume|r[ée]sum[ée]|\bCV\b|cover[ _-]letter|apply via|"
                 r"no[ _-]agency|agencies)\b", text, re.I):
        return True
    if re.search(r"\b(?:location|located|commute|office|hybrid|on[ _-]?site|in[ _-]office|based in)\b", text, re.I):
        return True
    # Canonical eligibility handles hours separately; generic traits are not proof gaps.
    if re.search(r"(?:part|full)[ _-]?time|hours|availability|professionalism|integrity|adaptab|attitude|"
                 r"openness to learn|willing(?:ness)? to learn|temporary|contract (?:term|length)|assignment|commenc|start[ _-]date",
                 text, re.I):
        return True
    return hours_exempt and bool(re.search(r"full[ _-]?time|hours|availability|start[ _-]date|intake", text, re.I))


def decide(
    evaluation: AgenticEvaluation,
    *,
    ad_text: str,
    title: str = "",
    policy: TargetPolicy,
    captured_complete: bool = True,
    expected_run_key: RunKey | None = None,
    evidence_bundle=None,
    commute_km: int | None = None,
    decision_policy: DecisionPolicy | None = None,
    company: str = "",
) -> AgenticGateDecision:
    """Validate and route an evaluation using deterministic checks only.

    Public errors intentionally carry only fixed codes; malformed nested inputs never leak
    validation payloads or source text.
    """
    valid = True
    try:
        if type(evaluation) is not AgenticEvaluation or type(policy) is not TargetPolicy:
            valid = False
        else:
            evaluation = AgenticEvaluation.model_validate(evaluation.model_dump())
            policy = TargetPolicy.model_validate(policy.model_dump())
            if expected_run_key is not None:
                if type(expected_run_key) is not RunKey:
                    valid = False
                else:
                    expected_run_key = RunKey.model_validate(expected_run_key.model_dump())
        if decision_policy is not None:
            if type(decision_policy) is not DecisionPolicy:
                valid = False
            else:
                decision_policy = DecisionPolicy.model_validate(decision_policy.model_dump())
        if (type(ad_text) is not str or type(title) is not str or type(company) is not str
                or type(captured_complete) is not bool):
            valid = False
    except Exception:
        valid = False
    if not valid:
        raise AgenticError("invalid_gate_input") from None

    if not captured_complete or not ad_text:
        return _hold(evaluation, "insufficient_evidence")

    ad_hash = hashlib.sha256(ad_text.encode("utf-8")).hexdigest()
    if ad_hash != evaluation.run_key.ad_hash or ad_hash != evaluation.requirements.ad_hash:
        return _hold(evaluation, "verification_required")
    if expected_run_key is not None and expected_run_key != evaluation.run_key:
        return _hold(evaluation, "verification_required")

    for requirement in evaluation.requirements.requirements:
        if requirement.jd_signal and not _verified(requirement.jd_signal, ad_text, ad_hash):
            return _hold(evaluation, "verification_required")
    requirements = {r.id: r for r in evaluation.requirements.requirements}
    unverified_blocker = False
    for match in evaluation.matches:
        if any(c.source_id not in {"master_resume.md", "cv.md", "profile.yaml"} for c in match.evidence):
            return _hold(evaluation, "verification_required")
        if match.match == "partial" and not match.evidence:
            return _hold(evaluation, "verification_required")
        if match.match in {"missing", "not_applicable"} and match.evidence:
            return _hold(evaluation, "verification_required")
        if match.match == "not_applicable" and requirements[match.requirement_id].importance in {"critical", "high"}:
            return _hold(evaluation, "verification_required")
        if requirements[match.requirement_id].blocker and match.match != "strong":
            # "missing" means not demonstrated, not proven incompatible.
            # Preserve confirmed policy exclusions below before holding unknowns.
            if _logistics(requirements[match.requirement_id]):
                # Documents, location and hours have dedicated operations/checks.
                continue
            unverified_blocker = True
    missing_candidate_evidence = bool(evaluation.matches) and not any(
        m.match in {"strong", "partial"} and m.evidence for m in evaluation.matches
    )
    if evidence_bundle is not None:
        try:
            from jobwatch.candidate.evidence import verify_evidence_snapshot
            from jobwatch.candidate.assessment import verify_candidate_citations
            verify_evidence_snapshot(evidence_bundle)
            if evidence_bundle.bundle_hash != evaluation.run_key.evidence_hash:
                raise ValueError
            for match in evaluation.matches:
                verify_candidate_citations(match.evidence, evidence_bundle)
                if match.judgment is not None:
                    verify_candidate_citations(match.judgment.contradiction_evidence, evidence_bundle)
                    if not set(match.judgment.reviewed_evidence_ids) <= {item.id for item in evidence_bundle.items}:
                        raise ValueError
        except Exception:
            return _hold(evaluation, "verification_required")

    if not evaluation.facts.real_job:
        return _archive(evaluation, 'hard_gate')
    verified_location = _verified(evaluation.location_evidence, ad_text, ad_hash)
    location = evaluation.location_evidence.quote if verified_location else ''
    remote_claimed = evaluation.location_fit == 'remote_accessible'
    if remote_claimed and not (verified_location and re.search(r'\bremote\b|work from home', location, re.I)):
        return _hold(evaluation, 'verification_required')
    from jobwatch.candidate.eligibility import evaluate_eligibility
    facts = evaluation.facts.model_dump(mode='json')
    if any('seniority unknown' in str(u).casefold() for u in (evaluation.matching_diagnostics or {}).get('ad_uncertainties', ())):
        facts['seniority'] = None
    eligibility = evaluate_eligibility({**facts,
        'title': title, 'company': company, 'location': location,
        'remote': remote_claimed},
        policy=decision_policy, ad_text=ad_text, commute_km=commute_km)
    if eligibility.status == 'excluded':
        return _archive(evaluation, 'policy_excluded' if eligibility.reason == 'policy_excluded' else 'hard_gate')
    if eligibility.status == 'held':
        return _hold(evaluation, 'verification_required' if eligibility.reason == 'verification_required' else 'insufficient_evidence')

    if unverified_blocker or missing_candidate_evidence:
        return _hold(evaluation, "insufficient_evidence")

    # Owner 2026-10-19: an employer the AI could not verify is shown with an "employer not verified" note, not held.
    if evaluation.legitimacy == "suspicious":
        return _hold(evaluation, "verification_required")

    # Scores remain an advisory baseline; evidence and confirmed policy decide eligibility.
    return _draft(evaluation)
