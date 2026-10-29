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


def native_acceptance_report(*, usage, native_counts, digest_counts, classifier_calls,
                             checks, gate_route, ledger_charged, seconds, resume_usage=None):
    """Count-only evidence from invocation deltas after canonical validation."""
    def required_count(value):
        if type(value) is not int or value < 0:
            raise ValueError('invalid_acceptance_counts')
        return value

    total = required_count(usage.get('model_calls'))  # Execution names all paid operations model_calls.
    actual = required_count(usage.get('actual_tokens'))
    charged = required_count(usage.get('charged_tokens'))
    unknown = required_count(usage.get('unknown_usage_calls'))
    if ledger_charged is not None:
        required_count(ledger_charged)
    native = required_count(native_counts.get('calls'))
    embedding = required_count(native_counts.get('purposes', {}).get('evidence_embeddings', 0))
    classifiers = required_count(classifier_calls)
    digest_calls = required_count(digest_counts.get('calls'))
    digest_charged = required_count(digest_counts.get('charged_tokens'))
    if embedding > native or not _number(seconds):
        raise ValueError('invalid_acceptance_counts')
    unattributed = total - native - classifiers - digest_calls
    model_calls = total - embedding - digest_calls
    attribution_complete = unattributed == 0 and model_calls >= 0
    reconciled = (type(ledger_charged) is int and ledger_charged == charged
                  and actual <= charged and attribution_complete)
    required_checks = ('canonical_evaluation', 'coverage', 'citations', 'judgments',
                       'gate', 'identity', 'protocol', 'digest_current')
    safe_checks = {name: checks.get(name) is True for name in required_checks}
    safe_checks['fresh_native_generation'] = native > embedding
    safe_route = gate_route if gate_route in {'draft', 'archive', 'hold'} else None
    quality = all(safe_checks.values()) and safe_route is not None
    warm = digest_counts.get('reused') is True and digest_calls == digest_charged == 0
    efficiency = attribution_complete and warm and 1 <= model_calls <= 6
    reuse_verified = (isinstance(resume_usage, Mapping) and all(
        type(resume_usage.get(key)) is int and resume_usage[key] == 0
        for key in ('model_calls', 'charged_tokens', 'actual_tokens', 'unknown_usage_calls')))
    cold = digest_counts.get('cold') or {}
    details = native_counts.get('details') or []
    def detail_sum(section, key):
        return sum(_count(item.get(section, {}).get(key)) for item in details if isinstance(item, Mapping))
    return {
        'accepted': quality and warm and reconciled and reuse_verified,
        'quality': {'passed': quality, 'checks': safe_checks, 'gate_route': safe_route},
        'efficiency': {'passed': efficiency, 'per_job_model_calls': model_calls,
                       'target_max_model_calls': 6},
        'paid_operations': {'native_model': native - embedding, 'classifier_model': classifiers,
            'embedding': embedding, 'digest_model': digest_calls, 'other_model': max(0, unattributed),
            'total': total},
        'tokens': {'known_actual': actual, 'charged': charged, 'unknown_usage_calls': unknown,
            'native_prompt': _count(native_counts.get('prompt_tokens')),
            'native_completion': _count(native_counts.get('completion_tokens')),
            'reasoning': detail_sum('completion_tokens_details', 'reasoning_tokens'),
            'cached_prompt': detail_sum('prompt_tokens_details', 'cached_tokens')},
        'digest': {'reused': warm, 'new_calls': digest_calls, 'new_charged_tokens': digest_charged,
            'historical_cold_calls': cold.get('calls') if type(cold.get('calls')) is int else None,
            'historical_cold_known_tokens': cold.get('tokens') if type(cold.get('tokens')) is int else None,
            'historical_cold_charged_tokens': cold.get('charged_tokens') if type(cold.get('charged_tokens')) is int else None},
        'accounting': {'reconciled': reconciled, 'ledger_charged': ledger_charged,
                      'unattributed_paid_operations': unattributed},
        'completed_reuse': {'verified': reuse_verified,
            'additional_paid_operations': (resume_usage['model_calls']
                if isinstance(resume_usage, Mapping) and type(resume_usage.get('model_calls')) is int
                and resume_usage['model_calls'] >= 0 else None)},
        'wall_seconds': seconds,
    }


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
