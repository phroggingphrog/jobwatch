"""Pure presentation of frozen evidence matches; no eligibility or model calls.

Callers validate current run identity and canonical citations before using these
functions. Labels are versioned evidence conventions, never application gates.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal, Mapping, Sequence

from pydantic import Field

from jobwatch.candidate.projection import _quotes as _profile_quotes
from jobwatch.place import STATES
from pipeline.agentic.contracts import AgenticEvaluation, StrictFrozen
from pipeline.agentic.location import location_verdict

IMPORTANCE_WEIGHTS = {'critical': 4, 'high': 3, 'meaningful': 2, 'preferred': 1, 'low_signal': 0}
STRONG_MIN = 2 / 3
UNRESOLVED_MAX = 1 / 3
PARTIAL_CREDIT = .5
RULES_VERSION = 'ranking-rules-v1'
Label = Literal['stronger_match', 'stretch', 'needs_clarification']
Ordering = Literal['provisional', 'personalised']


class Coverage(StrictFrozen):
    weighted: float
    demonstrated: int
    partial: int
    unknown: int
    contradicted: int
    mandatory_unmet: tuple[str, ...]
    missing_documentation: tuple[str, ...]
    real_gaps: tuple[str, ...]
    conflicts: tuple[str, ...]
    weighted_upper: float
    unresolved_share: float
    weight_total: int
    without_judgment: int
    mandatory_unknown: tuple[str, ...]
    mandatory_partial: tuple[str, ...]
    mandatory_conflicts: tuple[str, ...]


def _status(match):
    if match.judgment is not None:
        return match.judgment.status
    return {'strong': 'demonstrated', 'partial': 'partial', 'missing': 'unknown',
            'not_applicable': 'not_applicable'}[match.match]


def _rows(evaluation):
    matches = {m.requirement_id: m for m in evaluation.matches}
    return [(r, matches[r.id], _status(matches[r.id])) for r in sorted(
        evaluation.requirements.requirements, key=lambda r: (-IMPORTANCE_WEIGHTS[r.importance], r.id))]


def _mandatory(requirement):
    return requirement.blocker or requirement.importance == 'critical'


def coverage(evaluation: AgenticEvaluation) -> Coverage:
    """Weighted lower/upper bounds; absent historical judgments keep their old mapping."""
    counts = dict.fromkeys(('demonstrated', 'partial', 'unknown', 'contradicted'), 0)
    groups = {name: [] for name in ('mandatory_unmet', 'missing_documentation', 'real_gaps',
        'conflicts', 'mandatory_unknown', 'mandatory_partial', 'mandatory_conflicts')}
    total = credit = unknown_weight = without = 0
    for requirement, match, status in _rows(evaluation):
        without += match.judgment is None
        if status == 'not_applicable':
            continue
        weight = IMPORTANCE_WEIGHTS[requirement.importance]
        total += weight
        counts[status] += 1
        credit += weight * (1 if status == 'demonstrated' else PARTIAL_CREDIT if status == 'partial' else 0)
        if status == 'unknown':
            unknown_weight += weight
            if weight:
                groups['missing_documentation'].append(requirement.id)
        if status == 'partial' and weight:
            groups['real_gaps'].append(requirement.id)
        if status == 'contradicted':
            groups['conflicts'].append(requirement.id)
        if _mandatory(requirement) and status != 'demonstrated':
            groups['mandatory_unmet'].append(requirement.id)
            group = {'unknown':'mandatory_unknown', 'partial':'mandatory_partial',
                     'contradicted':'mandatory_conflicts'}[status]
            groups[group].append(requirement.id)
    return Coverage(weighted=credit / total if total else 0.,
        weighted_upper=(credit + unknown_weight) / total if total else 0.,
        unresolved_share=unknown_weight / total if total else 0., weight_total=total,
        without_judgment=without, **counts, **{k:tuple(v) for k,v in groups.items()})


def candidate_status(route: str, reason: str) -> Literal['eligible', 'held'] | None:
    return {('draft','eligible'): 'eligible', ('hold','insufficient_evidence'): 'held'}.get((route,reason))


def _relevance(relevance):
    return getattr(relevance, 'relevant', relevance)


def label_for(cov: Coverage, relevance, policy, *, held: bool = False) -> Label:
    if (held or cov.weight_total == 0 or cov.mandatory_unknown
            or cov.unresolved_share > UNRESOLVED_MAX
            or (_relevance(relevance) == 'uncertain' and getattr(policy,'strategy',None) != 'employment_first')):
        return 'needs_clarification'
    if cov.mandatory_partial or cov.conflicts or cov.weighted < STRONG_MIN:
        return 'stretch'
    return 'stronger_match'


def exclusion_reason(cov: Coverage, relevance=None) -> str | None:
    """Pass relevance only after the caller enforces current relevance:on context."""
    if cov.mandatory_conflicts:
        return 'mandatory_conflict'
    if _relevance(relevance) == 'no':
        return 'relevance_no'
    return None


@dataclass(frozen=True)
class Scored:
    case_id: str
    coverage: Coverage
    relevance: str | None
    label: Label
    similarity: float = 0.
    focus_match: bool = False
    unresolved: tuple[str, ...] = ()
    posting_id: int | None = None


@dataclass(frozen=True)
class Ranked:
    case_id: str
    rank: int
    ordering: Ordering
    rank_reason: str
    uncertainty: str
    unresolved: tuple[str, ...]


def _finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def _posting_order(scored):
    if scored.posting_id is not None:
        return (0, scored.posting_id, scored.case_id)
    if scored.case_id.isdecimal():
        return (0, int(scored.case_id), scored.case_id)
    return (1, 0, scored.case_id)


def rank_candidates(scored: Sequence[Scored], *, strategy: str = 'employment_first',
                    utilities: Mapping[str, float] | None = None, answered: int = 0,
                    minimum: int = 25) -> list[Ranked]:
    """A supplied utility map must be complete and finite; fit trust belongs to caller."""
    items = list(scored)
    personalised = bool(items) and utilities is not None and all(
        item.case_id in utilities and _finite(utilities[item.case_id]) for item in items)
    ordering: Ordering = 'personalised' if personalised else 'provisional'
    tiers = {'stronger_match':0, 'stretch':1, 'needs_clarification':2}

    def key(item):
        provisional = (not (strategy == 'career_focus' and item.focus_match and _relevance(item.relevance) == 'yes'),
                       -item.coverage.weighted, -item.coverage.weighted_upper,
                       -item.similarity if _finite(item.similarity) else 0, _posting_order(item))
        return (tiers[item.label],) + ((-utilities[item.case_id],) if personalised else ()) + provisional

    result = []
    for rank, item in enumerate(sorted(items,key=key),1):
        cov = item.coverage
        interval = f'{cov.weighted:.2f}–{cov.weighted_upper:.2f}'
        basis = 'learned preference within evidence tiers' if personalised else 'evidence coverage and current relevance within evidence tiers'
        uncertainty = ('Learned preference is uncertain; evidence coverage is not a hiring probability.' if personalised
            else f'{answered} of {minimum} answered comparisons; provisional evidence ordering. '
                 'Personalisation requires a valid genuine fit with complete utilities.')
        result.append(Ranked(item.case_id,rank,ordering,
            f'{item.label}; evidence coverage {interval}; {ordering}: {basis}. '
            'Ties use posting id.', uncertainty,item.unresolved))
    return result


class ShortlistEntry(StrictFrozen):
    entry_id: str
    shortlist_id: str
    posting_id: int = Field(ge=1)
    run_key: str
    profile_version: int
    label: Label
    rank: int = Field(ge=1)
    rank_reason: str
    ordering: Ordering
    uncertainty: str
    evidence: tuple[dict, ...]
    transferable_skills: tuple[str, ...]
    objective_fit: str
    conditions: tuple[str, ...]
    mandatory_requirements: tuple[str, ...]
    unresolved: tuple[str, ...]
    holistic_score: float | None
    created_at: str
    posting: dict
    coverage: dict
    requirements: tuple[dict, ...]
    utility: float | None = Field(default=None, allow_inf_nan=False)


def _unique(values):
    return list(dict.fromkeys(value for value in values if value))


def _fact_text(value):
    if isinstance(value,str):
        return value
    if isinstance(value,dict):
        return ', '.join(str(v) for k,v in sorted(value.items()) if isinstance(v,(str,int,float,bool)))
    return ''


def _fact_supported(fact, citations):
    """Link the whole approved source quote through an existing positive match.

    Projected profile sources may use a canonical-file hash different from the
    original upload. The same projection line normalization retains whole quotes;
    token overlap and paraphrases do not establish the link.
    Person-authored facts without document sources project their whole value.
    """
    if not fact.get('sources') and fact.get('actor') != 'person':
        return False
    # Use the projection's full quote derivation, including insertion order of
    # structured person statements and its exact whitespace normalization.
    projected = _profile_quotes(fact)
    return any(quote and quote in citation.quote for quote in projected for citation in citations)


def explain(evaluation: AgenticEvaluation, cov: Coverage, label: Label, *, policy,
            relevance, approved_facts) -> dict:
    """Template explanation using only frozen matches and approved factual links.

    Does not retrieve or newly judge evidence. Inferences remain explicit review
    questions and never become factual citations or qualification support.
    """
    rows = _rows(evaluation)
    supported = [(r,m,status) for r,m,status in rows if status in ('demonstrated','partial') and m.evidence]
    evidence = [dict(requirement_id=r.id, requirement=r.text, status=status,
                     citations=[c.model_dump(mode='json') for c in m.evidence])
                for r,m,status in supported[:6]]
    citations = [c for _,m,_ in supported for c in m.evidence]
    transferable, unresolved = [], []
    for fact in approved_facts or ():
        if not isinstance(fact,dict):
            continue
        value = _fact_text(fact.get('value'))
        if fact.get('basis') in ('unknown','inference') and value:
            unresolved.append(f'Confirm {value} ({fact["basis"]}); it is not established evidence.')
        if (fact.get('section') == 'transferable_skill' and fact.get('basis') == 'evidence'
                and value and _fact_supported(fact,citations)):
            transferable.append(value)
    strategy = getattr(policy,'strategy','balanced')
    strategy_name = {'employment_first':'employment-first', 'career_focus':'career focus', 'balanced':'balanced'}.get(strategy,strategy)
    # These are search objectives, not personal qualification evidence.
    focus = tuple(getattr(policy,'focus',()) or ())
    hypotheses = tuple(getattr(relevance,'matched_hypotheses',()) or ())
    objective = f'{strategy_name}; evidence coverage {cov.weighted:.2f}–{cov.weighted_upper:.2f} ({label}).'
    if focus:
        objective += ' Confirmed focus: ' + '; '.join(focus) + '.'
    if hypotheses:
        objective += ' Current discovery hypotheses: ' + '; '.join(hypotheses) + '.'
    facts = evaluation.facts
    conditions = [f'Hours: {facts.hours}.']
    if facts.hours == 'unstated':
        unresolved.append('What hours does this role require?')
    location = evaluation.location_evidence
    if location is not None:
        regions = frozenset(getattr(policy,'regions',()) or ())
        # Empty regions mean no area restriction, not proof that the ad named a
        # location. Use the canonical geographic reference to check that first.
        verdict = location_verdict(location.quote, regions or frozenset(STATES),
            remote_fit=evaluation.location_fit == 'remote_accessible', remote_ok=getattr(policy,'remote_ok',None))
        if verdict == 'unknown':
            conditions.append(f'Location not stated clearly: {location.quote}')
            unresolved.append('What is the job location?')
        elif not getattr(policy,'regions',()):
            conditions.append(f'Location: {location.quote}; no confirmed region restriction.')
        else:
            wording = {'in':'in your area', 'outside':'outside your confirmed area', 'remote':'remote location'}[verdict]
            conditions.append(f'Location: {location.quote}; {wording}.')
    else:
        conditions.append('Location not stated.')
        unresolved.append('What is the job location?')
    rights = facts.work_rights
    conditions.append(f'Work rights: {rights.quote}' if rights.quote else 'Work rights: not stated in the ad.')
    if not rights.quote:
        unresolved.append('What work rights does this role require?')
    years = f'{facts.min_years} years minimum' if facts.min_years is not None else 'years not stated'
    if facts.min_years is None:
        unresolved.append('How many years of experience does this role require?')
    if evaluation.legitimacy != 'verified':
        unresolved.append('Can the legitimacy of this posting be verified?')
    conditions.extend([f'Level: {facts.seniority}; {years}.',
        f'Programme: {"yes" if facts.program else "no"}.', f'Legitimacy: {evaluation.legitimacy}.'])
    for requirement, match, status in rows:
        if match.judgment is not None and match.judgment.open_question:
            unresolved.append(match.judgment.open_question)
        elif status in ('unknown','partial'):
            unresolved.append(f'Can you clarify the evidence for {requirement.text}?')
    unresolved.extend(evaluation.screening_questions)
    unresolved.extend(facts.screening_questions)
    unresolved.extend(f'Confirm profile question: {q}.' for q in (getattr(policy,'open_questions',()) or ()))
    if _relevance(relevance) == 'uncertain':
        unresolved.append('Does this role fit the confirmed search objective?')
    return dict(evidence=evidence, transferable_skills=sorted(set(transferable)), objective_fit=objective,
        conditions=conditions, mandatory_requirements=[f'{r.text} [{status}]' for r,_,status in rows if _mandatory(r)],
        unresolved=_unique(unresolved))
