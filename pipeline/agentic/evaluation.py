"""Offline tool-trajectory evaluation; no candidate text or model judge."""
from __future__ import annotations

import random

from pydantic import Field
from typing import Literal

from pipeline.agentic.contracts import AgenticError, AgenticEvaluation, AgenticGateDecision, StrictFrozen


class MatchingPrediction(StrictFrozen):
    evaluation: AgenticEvaluation
    decision: AgenticGateDecision
    latency_seconds: float = Field(ge=0, allow_inf_nan=False)
    charged_tokens: int = Field(ge=0)
    actual_tokens: int | None = Field(default=None, ge=0)


class MatchingReview(StrictFrozen):
    actor: Literal['owner']
    suitable: bool
    requirement_status: dict[str, Literal['demonstrated', 'partial', 'unknown', 'contradicted', 'not_applicable']]


class MatchingCase(StrictFrozen):
    case_id: str = Field(min_length=1, max_length=128)
    group_id: str = Field(min_length=1, max_length=128, description='Keep company/ad variants in one split.')
    split: Literal['development', 'holdout']
    predictions: dict[str, MatchingPrediction]
    review: MatchingReview | None = None


def _matching_cases(raw):
    from pipeline.agentic.runtime import validate_model_payload
    if type(raw) is not list or not raw or len(raw) > 1000:
        raise AgenticError('invalid_comparison')
    cases = [validate_model_payload(MatchingCase, item) for item in raw]
    seen, groups, arms = set(), {}, set(cases[0].predictions)
    if not 2 <= len(arms) <= 4:
        raise AgenticError('comparison_arms_required')
    for case in cases:
        if case.case_id in seen or set(case.predictions) != arms:
            raise AgenticError('inconsistent_comparison')
        seen.add(case.case_id)
        if case.group_id in groups and groups[case.group_id] != case.split:
            raise AgenticError('comparison_split_leakage')
        groups[case.group_id] = case.split
        identities = set()
        for prediction in case.predictions.values():
            ev = prediction.evaluation
            if prediction.decision.run_key != ev.run_key:
                raise AgenticError('comparison_identity_mismatch')
            identities.add((ev.run_key.posting_id, ev.run_key.ad_hash, ev.run_key.evidence_hash, ev.requirements.requirement_hash))
        if len(identities) != 1:
            raise AgenticError('comparison_identity_mismatch')
        ids = {r.id for r in next(iter(case.predictions.values())).evaluation.requirements.requirements}
        if case.review and set(case.review.requirement_status) != ids:
            raise AgenticError('comparison_review_incomplete')
    return cases, sorted(arms)


def blind_matching_packet(raw, *, seed):
    """Private packet and separate arm key; no model calls or automatic labels."""
    cases, arms = _matching_cases(raw)
    rng = random.Random(seed)
    rng.shuffle(cases)
    packet, key = [], {}
    for number, case in enumerate(cases, 1):
        versions = list(arms)
        rng.shuffle(versions)
        case_key, alternatives = f'case-{number}', {}
        key[case_key] = {'case_id': case.case_id, 'arms': {}}
        for index, version in enumerate(versions):
            alias = chr(ord('A') + index)
            ev = case.predictions[version].evaluation
            # Omit score, route, latency, diagnostics and implementation names.
            legacy = {'strong': 'demonstrated', 'partial': 'partial', 'missing': 'unknown', 'not_applicable': 'not_applicable'}
            alternatives[alias] = {'matches': [{
                'requirement_id': m.requirement_id,
                'status': m.judgment.status if m.judgment else legacy[m.match],
                'supporting_evidence': [c.model_dump(mode='json') for c in m.evidence],
                'contradiction_evidence': [c.model_dump(mode='json') for c in m.judgment.contradiction_evidence] if m.judgment else [],
                'rationale': m.judgment.rationale if m.judgment else m.risk,
                'open_question': m.judgment.open_question if m.judgment else '',
            } for m in ev.matches]}
            key[case_key]['arms'][alias] = version
        first = next(iter(case.predictions.values())).evaluation
        packet.append({'case': case_key, 'requirements': first.requirements.model_dump(mode='json'),
            'evidence_hash': first.run_key.evidence_hash, 'alternatives': alternatives,
            'review': {'suitable': None, 'requirement_status': {r.id: None for r in first.requirements.requirements}}})
    return {'schema_version': 1, 'cases': packet}, key


def compare_matching_runs(raw):
    """Aggregate independently reviewed saved outputs; never dispatch paid work."""
    cases, arms = _matching_cases(raw)
    reports = {}
    legacy = {'strong': 'demonstrated', 'partial': 'partial', 'missing': 'unknown', 'not_applicable': 'not_applicable'}
    for split in ('development', 'holdout'):
        selected = [case for case in cases if case.split == split and case.review is not None]
        result = {}
        for arm in arms:
            counts = dict.fromkeys(('cases', 'suitable_cases', 'false_exclusions', 'suitable_held',
                'unsuitable_drafted', 'requirement_judgments', 'unsupported_strong',
                'status_disagreements', 'unknown_contradiction_errors', 'charged_tokens',
                'actual_tokens', 'unknown_usage_cases'), 0)
            elapsed = 0.0
            for case in selected:
                prediction, review = case.predictions[arm], case.review
                counts['cases'] += 1
                counts['suitable_cases'] += review.suitable
                counts['false_exclusions'] += review.suitable and prediction.decision.route == 'archive'
                counts['suitable_held'] += review.suitable and prediction.decision.route == 'hold'
                counts['unsuitable_drafted'] += not review.suitable and prediction.decision.route == 'draft'
                for match in prediction.evaluation.matches:
                    expected = review.requirement_status[match.requirement_id]
                    status = match.judgment.status if match.judgment else legacy[match.match]
                    counts['requirement_judgments'] += 1
                    counts['unsupported_strong'] += status == 'demonstrated' and expected != 'demonstrated'
                    counts['status_disagreements'] += status != expected
                    counts['unknown_contradiction_errors'] += {status, expected} == {'unknown', 'contradicted'}
                elapsed += prediction.latency_seconds
                counts['charged_tokens'] += prediction.charged_tokens
                if prediction.actual_tokens is None:
                    counts['unknown_usage_cases'] += 1
                else:
                    counts['actual_tokens'] += prediction.actual_tokens
            result[arm] = {**counts, 'mean_latency_seconds': elapsed / len(selected) if selected else None}
        reports[split] = {'reviewed_cases': len(selected), 'arms': result}
    return {'status': 'descriptive_comparison' if reports['holdout']['reviewed_cases'] else 'owner_holdout_labels_required',
        'schema_version': 1, 'reports': reports, 'unreviewed_cases': sum(c.review is None for c in cases),
        'limits': 'Imported owner attribution is not authentication. Review quotes against private canonical sources. No calibration or promotion established; legacy missing is compared as unknown. Group labels and independent review need human confirmation.'}


def evaluate_tools(events, expected):
    from agentevals.trajectory.match import create_trajectory_match_evaluator
    from langsmith import tracing_context
    def messages(names):
        return [{'role': 'assistant', 'content': '', 'tool_calls': [
            {'id': f'step-{i}', 'name': name, 'args': {}}]} for i, name in enumerate(names)]
    actual = [e['data']['tool'] for e in events if e['type'] == 'tool_started']
    evaluator = create_trajectory_match_evaluator(trajectory_match_mode='strict', tool_args_match_mode='ignore')
    with tracing_context(enabled=False):
        return evaluator(outputs={'messages': messages(actual)}, reference_outputs={'messages': messages(expected)})
