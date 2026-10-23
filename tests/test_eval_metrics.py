"""Synthetic evaluation arithmetic across the public, pure computation seam."""
from copy import deepcopy

import pytest

from pipeline.agentic.eval_metrics import compute_metrics


def replay_cases(count=12):
    cases = []
    for index in range(1, count + 1):
        cases.append({
            'case_id': f'case-{index}', 'posting_id': index,
            'baseline': {'route': 'draft', 'rank': index if index <= 6 else None,
                         'usage': {'charged_tokens': 10, 'actual_tokens': None, 'latency_seconds': None}},
            'current': {'status': 'replayed', 'route': 'draft',
                        'rank': index if index <= 8 else None, 'label': 'stretch',
                        'coverage': {'unknown': 0, 'contradicted': 0, 'mandatory_unmet': 0},
                        'citation_failures': 0, 'mandatory_conflicts': 0, 'unresolved': 0,
                        'usage': {'charged_tokens': 0, 'actual_tokens': 0, 'latency_seconds': None}},
        })
    return {'status': 'complete', 'requested': count, 'processed': count, 'cases': cases}


def owner_labels(count=12, **fields):
    return {f'case-{index}': {'actor': 'owner', **fields} for index in range(1, count + 1)}


def test_exact_missed_suitable_and_precision_with_frozen_rankings():
    """Break: count only ranked labels in the denominator or infer suitability."""
    replay = replay_cases()
    labels = owner_labels(suitable=False)
    for index in (1, 2, 3, 7, 8):
        labels[f'case-{index}']['suitable'] = True
    metrics = compute_metrics(replay, labels)
    assert metrics['baseline']['missed_suitable']['count'] == 2
    assert metrics['baseline']['missed_suitable']['of'] == 5
    assert metrics['baseline']['missed_suitable']['rate'] == 0.4
    assert metrics['current']['missed_suitable']['count'] == 0
    assert metrics['baseline']['ordering']['precision_at']['5']['value'] == 0.6
    # Precision@10 over 8 ranked cases is 5/10, not 5/8: an arm is not credited for slots it left empty.
    assert metrics['current']['ordering']['precision_at']['10'] == {
        'status': 'short_prefix', 'value': 0.5, 'count': 5, 'of': 10, 'ranked': 8}
    assert metrics['baseline']['ordering']['precision_at']['5']['status'] == 'measured'
    assert metrics['comparison']['missed_suitable'] == {'fixed': 2, 'broke': 0, 'delta': -2}


def test_ndcg_condenses_unlabelled_ranks_and_ideal_includes_unranked_cases():
    """Break: ideal uses only retrieved cases, or raw positions discount labels."""
    replay = replay_cases(14)
    labels = owner_labels(12, relevance=0)
    labels['case-1']['relevance'] = 3
    labels['case-3']['relevance'] = 2
    labels['case-12']['relevance'] = 3
    # An unlabelled case occupies rank 1 but cannot be treated as a negative label.
    replay['cases'][12]['baseline']['rank'] = 1
    replay['cases'][0]['baseline']['rank'] = 2
    metrics = compute_metrics(replay, labels)
    ordering = metrics['baseline']['ordering']
    assert ordering['ndcg_at']['5']['value'] == pytest.approx(8.5 / 12.916508275, abs=1e-10)
    assert ordering['precision_at']['5']['value'] == 0.4
    assert ordering['labelled_ranked'] == 6
    assert ordering['coverage'] == {'labelled_cases': 12, 'common_cases': 14, 'fraction': 12 / 14}


def test_metrics_require_their_own_applicable_owner_labels():
    """Break: relevance or exclusion labels are silently reused as suitability."""
    labels = owner_labels(relevance=2)
    for index in range(1, 10):
        labels[f'case-{index}']['suitable'] = True
    metrics = compute_metrics(replay_cases(), labels)
    assert metrics['current']['missed_suitable'] == {
        'status': 'missing_labels', 'labelled': 9, 'minimum': 10, 'value': None}
    assert metrics['current']['exclusion_violations'] == {
        'status': 'missing_labels', 'labelled': 0, 'minimum': 10, 'value': None}
    assert metrics['current']['ordering']['status'] == 'measured'
    assert metrics['current']['ordering']['precision_at']['5']['value'] == 1
    labels['case-10']['suitable'] = False
    labels['case-1']['exclusion_violation'] = True
    assert compute_metrics(replay_cases(), labels)['current']['missed_suitable']['status'] == 'measured'
    assert compute_metrics(replay_cases(), labels)['current']['exclusion_violations']['labelled'] == 1


def test_partial_replay_censors_comparisons_and_excludes_deferred_cases():
    """Break: favorable first cases are advertised as complete quality results."""
    replay = replay_cases()
    replay.update(status='bounded', processed=11, stop_reason='case_limit')
    replay['cases'][-1]['current']['status'] = 'deferred'
    labels = owner_labels(suitable=True, relevance=3, exclusion_violation=False)
    metrics = compute_metrics(replay, labels)
    assert metrics['status'] == 'partial_replay'
    assert metrics['common_cases'] == 11
    assert metrics['comparison'] == {'status': 'partial_replay', 'value': None}
    assert metrics['current']['ordering']['status'] == 'partial_replay'
    assert metrics['current']['ordering']['value'] is None
    assert metrics['baseline']['missed_suitable']['status'] == 'partial_replay'
    assert metrics['baseline']['exclusion_violations']['status'] == 'partial_replay'
    # Incorrectly claimed completeness is still caught by actual common-case counts.
    replay['status'] = 'complete'
    assert compute_metrics(replay, labels)['status'] == 'partial_replay'


def test_unlabelled_diagnostics_keep_citations_conflicts_unknowns_and_usage_separate():
    """Break: incomplete citation checks become qualification truth or unknown costs zero."""
    replay = replay_cases()
    current = replay['cases'][0]['current']
    current.update(citation_failures=2, mandatory_conflicts=1, unresolved=3, uncertainty_disclosed=True)
    current['coverage'].update(unknown=4, contradicted=2, mandatory_unmet=1)
    current['usage'] = {'charged_tokens': 15, 'actual_tokens': None, 'latency_seconds': 2}
    replay['cases'][1]['current']['usage']['latency_seconds'] = 4
    metrics = compute_metrics(replay, {})
    assert metrics['current']['missed_suitable']['status'] == 'missing_labels'
    assert metrics['current']['deterministic_indicators'] == {
        'basis': 'citation_checks_not_independent_qualification', 'citation_failures': 2,
        'cases_with_citation_failures': 1, 'mandatory_conflicts': 1,
        'cases_with_mandatory_conflicts': 1, 'mandatory_unmet': 1}
    assert metrics['current']['uncertainty'] == {
        'unknown': 4, 'contradicted': 2, 'unresolved': 3,
        'cases_with_unknowns': 1, 'cases_with_contradictions': 1,
        'unresolved_shortlisted': 1, 'disclosed': 1, 'disclosure_recorded': 1,
        'disclosure_missing': 11}
    assert metrics['baseline']['usage']['charged_tokens'] == {'total': 120, 'recorded': 12, 'missing': 0}
    assert metrics['baseline']['usage']['actual_tokens'] == {'total': None, 'recorded': 0, 'missing': 12}
    assert metrics['current']['usage']['actual_tokens'] == {'total': 0, 'recorded': 11, 'missing': 1}
    assert metrics['current']['usage']['latency_seconds'] == {
        'basis': 'recorded', 'recorded': 2, 'missing': 10, 'total': 6,
        'mean': 3, 'median': 3, 'p95': 4}
    assert metrics['baseline']['usage']['latency_seconds']['basis'] == 'not_measured'


def test_exclusion_comparison_uses_human_labels_separately_from_mandatory_conflicts():
    """Break: mandatory contradictions are substituted for owner exclusions."""
    replay = replay_cases()
    labels = owner_labels(exclusion_violation=False)
    labels['case-1']['exclusion_violation'] = True
    labels['case-7']['exclusion_violation'] = True
    replay['cases'][0]['current']['rank'] = None
    replay['cases'][1]['current']['mandatory_conflicts'] = 1
    result = compute_metrics(replay, labels)
    assert result['baseline']['exclusion_violations']['count'] == 1
    assert result['current']['exclusion_violations']['count'] == 1
    assert result['comparison']['exclusion_violations'] == {'fixed': 1, 'broke': 1, 'delta': 0}


def test_invalid_or_nonhuman_labels_cannot_unlock_quality_metrics():
    """Break: arbitrary or model-authored dictionaries count toward human support."""
    replay = replay_cases()
    labels = owner_labels(relevance=4)
    labels['case-1'] = {'actor': 'model', 'suitable': True, 'relevance': 3}
    labels['case-2'] = {'actor': 'owner', 'relevance': True}
    metrics = compute_metrics(replay, labels)
    assert metrics['current']['ordering']['status'] == 'missing_labels'
    assert metrics['current']['ordering']['labelled'] == 0


def test_zero_ideal_and_pending_outcomes_never_manufacture_ranking_quality():
    replay = replay_cases()
    labels = owner_labels(suitable=True, relevance=0)
    for case in replay['cases']:
        case['outcome'] = 'pending'
        case['propensity'] = 1
    metrics = compute_metrics(replay, labels)
    assert metrics['current']['ordering']['ndcg_at']['5'] == {'status': 'zero_ideal', 'value': None}
    assert metrics['current']['ordering']['precision_at']['5']['value'] == 0
    clean = deepcopy(replay)
    for case in clean['cases']:
        case.pop('outcome')
        case.pop('propensity')
    assert compute_metrics(clean, labels) == metrics


def test_suitability_fallback_uses_binary_gain_not_grade_three():
    # Grade 3, binary grade 1 and zeros; worked ideal has DCG 7.63092975357.
    labels = owner_labels(suitable=False)
    labels['case-1'] = {'actor': 'owner', 'relevance': 3}
    labels['case-12']['suitable'] = True
    result = compute_metrics(replay_cases(), labels)
    assert result['baseline']['ordering']['ndcg_at']['5']['value'] == pytest.approx(0.9173194127129571)


def test_nonfinite_usage_is_missing_and_label_notes_never_appear():
    import json

    replay = replay_cases()
    replay['cases'][0]['current']['usage'].update(charged_tokens=float('nan'), actual_tokens=float('inf'))
    labels = owner_labels(suitable=True, note='PRIVATE-SYNTHETIC-NOTE')
    result = compute_metrics(replay, labels)
    assert result['current']['usage']['charged_tokens']['missing'] == 1
    assert result['current']['usage']['actual_tokens']['missing'] == 1
    assert 'PRIVATE-SYNTHETIC-NOTE' not in json.dumps(result, allow_nan=False)


def test_precision_at_k_stays_comparable_between_arms_of_different_depth():
    """Break: divide by the number of ranked cases, and a shallow shortlist outscores a deeper, better one."""
    replay = replay_cases(12)
    for index, case in enumerate(replay['cases'], 1):
        case['baseline']['rank'] = index if index <= 3 else None        # 3 ranked, all relevant
        case['current']['rank'] = index if index <= 10 else None        # 10 ranked, 9 relevant
    labels = owner_labels(12, relevance=3)
    labels['case-10']['relevance'] = 0
    for index in range(11, 13):
        labels[f'case-{index}']['relevance'] = 0
    metrics = compute_metrics(replay, labels)
    shallow = metrics['baseline']['ordering']['precision_at']['10']
    deep = metrics['current']['ordering']['precision_at']['10']
    assert shallow == {'status': 'short_prefix', 'value': 0.3, 'count': 3, 'of': 10, 'ranked': 3}
    assert deep == {'status': 'measured', 'value': 0.9, 'count': 9, 'of': 10, 'ranked': 10}
    assert deep['value'] > shallow['value']
