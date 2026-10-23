"""Pure diagnostics for frozen replays, with human-label missingness explicit.

Ranks are the replay's canonical shortlist membership, including evidence holds.
Unranked cases stay in human-label denominators and the nDCG ideal ordering.
"""
from __future__ import annotations

from collections.abc import Mapping
from math import ceil, isfinite, log2
from statistics import median

MIN_LABELS = 10
K_VALUES = (5, 10)
METRICS_VERSION = 'evaluation-metrics-v2'


def _label_value(label, field):
    return label.get(field) if isinstance(label, Mapping) else getattr(label, field, None)


def _owner_label(label):
    return _label_value(label, 'actor') == 'owner'


def _valid_relevance(value):
    return type(value) is int and 0 <= value <= 3


def _ranked(arm):
    rank = arm.get('rank')
    return type(rank) is int and rank > 0


def _missing(labelled):
    return {'status': 'missing_labels', 'labelled': labelled, 'minimum': MIN_LABELS, 'value': None}


def _suitable(arm, labelled):
    if len(labelled) < MIN_LABELS:
        return _missing(len(labelled))
    positive = [case for case, label in labelled if _label_value(label, 'suitable') is True]
    missed = [case for case in positive if not _ranked(case[arm])]
    return {'status': 'measured', 'labelled': len(labelled), 'count': len(missed), 'of': len(positive),
            'rate': len(missed) / len(positive) if positive else None,
            'held': sum(case[arm].get('route') == 'hold' for case in missed)}


def _ordering(arm, labelled):
    if len(labelled) < MIN_LABELS:
        return _missing(len(labelled))
    ordered = sorted(((case, label) for case, label in labelled if _ranked(case[arm])),
                     key=lambda item: (item[0][arm]['rank'], item[0]['posting_id']))
    def grade(label):
        relevance = _label_value(label, 'relevance')
        return relevance if _valid_relevance(relevance) else int(_label_value(label, 'suitable') is True)

    def dcg(grades):
        return sum((2 ** relevance - 1) / log2(position + 2)
                   for position, relevance in enumerate(grades))

    ideal = sorted((grade(label) for _, label in labelled), reverse=True)
    ndcg = {}
    precision = {}
    for k in K_VALUES:
        selected = ordered[:k]
        ideal_value = dcg(ideal[:k])
        ndcg[str(k)] = {'status': 'measured' if ideal_value else 'zero_ideal',
                        'value': dcg([grade(label) for _, label in selected]) / ideal_value
                        if ideal_value else None}
        positives = sum((_label_value(label, 'relevance') >= 2)
                        if _valid_relevance(_label_value(label, 'relevance'))
                        else _label_value(label, 'suitable') is True for _, label in selected)
        # Standard precision@k: the denominator is k, so an arm that ranked fewer than k cases does not
        # score as if it had ranked k. Dividing by len(selected) made a 3-item shortlist of 3 relevant
        # cases beat a 10-item shortlist of 9, which is the opposite of the comparison this serves.
        precision[str(k)] = {'status': 'measured' if len(selected) >= k else 'short_prefix',
                             'value': positives / k, 'count': positives, 'of': k, 'ranked': len(selected)}
    return {'status': 'measured', 'labelled': len(labelled), 'labelled_ranked': len(ordered),
            'basis': 'condensed_human_labelled_ordering', 'precision_at': precision, 'ndcg_at': ndcg}



def _number(value):
    return type(value) in (int, float) and isfinite(value) and value >= 0


def _count(value):
    return value if type(value) is int and value >= 0 else 0


def _usage(cases, arm):
    result = {}
    for field in ('charged_tokens', 'actual_tokens', 'latency_seconds'):
        values = [case[arm].get('usage', {}).get(field) for case in cases]
        values = [value for value in values if _number(value)]
        entry = {'total': sum(values) if values else None, 'recorded': len(values),
                 'missing': len(cases) - len(values)}
        if field == 'latency_seconds':
            entry.update(basis='recorded' if values else 'not_measured',
                         mean=sum(values) / len(values) if values else None,
                         median=median(values) if values else None,
                         p95=sorted(values)[ceil(len(values) * 0.95) - 1] if values else None)
        result[field] = entry
    return result


def _diagnostics(cases):
    current = [case['current'] for case in cases]
    citations = [_count(case.get('citation_failures')) for case in current]
    conflicts = [_count(case.get('mandatory_conflicts')) for case in current]
    indicators = {'basis': 'citation_checks_not_independent_qualification',
                  'citation_failures': sum(citations),
                  'cases_with_citation_failures': sum(value > 0 for value in citations),
                  'mandatory_conflicts': sum(conflicts),
                  'cases_with_mandatory_conflicts': sum(value > 0 for value in conflicts),
                  'mandatory_unmet': sum(_count(case.get('coverage', {}).get('mandatory_unmet'))
                                         for case in current)}
    unknown = [_count(case.get('coverage', {}).get('unknown')) for case in current]
    contradicted = [_count(case.get('coverage', {}).get('contradicted')) for case in current]
    disclosure = [case.get('uncertainty_disclosed') for case in current]
    uncertainty = {'unknown': sum(unknown), 'contradicted': sum(contradicted),
                   'unresolved': sum(_count(case.get('unresolved')) for case in current),
                   'cases_with_unknowns': sum(value > 0 for value in unknown),
                   'cases_with_contradictions': sum(value > 0 for value in contradicted),
                   'unresolved_shortlisted': sum(_ranked(case) and _count(case.get('unresolved')) > 0
                                                for case in current),
                   'disclosed': sum(value is True for value in disclosure),
                   'disclosure_recorded': sum(type(value) is bool for value in disclosure),
                   'disclosure_missing': sum(type(value) is not bool for value in disclosure)}
    return indicators, uncertainty


def compute_metrics(replay: dict, labels: Mapping) -> dict:
    """Compute a JSON-safe diagnostic comparison over common replayed cases only."""
    cases = [case for case in replay.get('cases', []) if case['current'].get('status') == 'replayed']
    suitability = [(case, labels[case['case_id']]) for case in cases
                   if case['case_id'] in labels and _owner_label(labels[case['case_id']])
                   and type(_label_value(labels[case['case_id']], 'suitable')) is bool]
    ordering = [(case, labels[case['case_id']]) for case in cases
                if case['case_id'] in labels and _owner_label(labels[case['case_id']])
                and (type(_label_value(labels[case['case_id']], 'suitable')) is bool
                     or _valid_relevance(_label_value(labels[case['case_id']], 'relevance')))]
    exclusions = [(case, labels[case['case_id']]) for case in cases
                  if case['case_id'] in labels and _owner_label(labels[case['case_id']])
                  and type(_label_value(labels[case['case_id']], 'exclusion_violation')) is bool]
    partial = (replay.get('status') != 'complete' or len(cases) != replay.get('requested')
               or len(cases) != replay.get('processed'))
    result = {'version': METRICS_VERSION, 'status': 'partial_replay' if partial else 'complete',
              'common_cases': len(cases)}
    for arm in ('baseline', 'current'):
        result[arm] = {'missed_suitable': _suitable(arm, suitability), 'ordering': _ordering(arm, ordering)}
        result[arm]['exclusion_violations'] = _missing(len(exclusions))
        if len(exclusions) >= MIN_LABELS:
            result[arm]['exclusion_violations'] = {
                'status': 'measured', 'labelled': len(exclusions),
                'count': sum(_label_value(label, 'exclusion_violation') is True and _ranked(case[arm])
                             for case, label in exclusions), 'of': len(exclusions)}
        result[arm]['ordering']['coverage'] = {
            'labelled_cases': len(ordering), 'common_cases': len(cases),
            'fraction': len(ordering) / len(cases) if cases else None}

    for arm in ('baseline', 'current'):
        result[arm]['usage'] = _usage(cases, arm)
    indicators, uncertainty = _diagnostics(cases)
    result['current'].update(deterministic_indicators=indicators, uncertainty=uncertainty)
    comparison = _missing(len(suitability))
    if len(suitability) >= MIN_LABELS:
        positive = [case for case, label in suitability if _label_value(label, 'suitable') is True]
        fixed = sum(not _ranked(case['baseline']) and _ranked(case['current']) for case in positive)
        broke = sum(_ranked(case['baseline']) and not _ranked(case['current']) for case in positive)
        comparison = {'fixed': fixed, 'broke': broke, 'delta': broke - fixed}
    result['comparison'] = {'missed_suitable': comparison}
    exclusion_comparison = _missing(len(exclusions))
    if len(exclusions) >= MIN_LABELS:
        violations = [case for case, label in exclusions if _label_value(label, 'exclusion_violation') is True]
        fixed = sum(_ranked(case['baseline']) and not _ranked(case['current']) for case in violations)
        broke = sum(not _ranked(case['baseline']) and _ranked(case['current']) for case in violations)
        exclusion_comparison = {'fixed': fixed, 'broke': broke, 'delta': broke - fixed}
    result['comparison']['exclusion_violations'] = exclusion_comparison
    if partial:
        result['comparison'] = {'status': 'partial_replay', 'value': None}
        for arm in ('baseline', 'current'):
            for metric in ('missed_suitable', 'ordering', 'exclusion_violations'):
                entry = result[arm][metric]
                if entry['status'] != 'missing_labels':
                    result[arm][metric] = {'status': 'partial_replay', 'value': None,
                                           'labelled': entry['labelled']}
    return result
