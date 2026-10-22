"""Synthetic private report storage and data-minimisation behavior."""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from jobwatch.reports.evaluation import report_payload, write_report
from pipeline.agentic.contracts import AgenticError
from pipeline.agentic.eval_metrics import compute_metrics


def replay_input():
    return {
        'version': 'evaluation-v1', 'baseline_id': 'bl-synthetic-001', 'partition': 'development',
        'data_hash': 'a' * 64, 'code_hash': 'b' * 64, 'split_hash': 'c' * 64,
        'inputs_hash': 'd' * 64, 'labels_hash': None, 'baseline_gate_version': 'e' * 64,
        'ranking_rules_version': 'ranking-rules-v1', 'ordering': 'provisional',
        'status': 'complete', 'stop_reason': None, 'requested': 1, 'processed': 1,
        'cases': [{'case_id': 'c-1-aabbccdd', 'posting_id': 1,
                   'baseline': {'route': 'archive', 'rank': None, 'score': 42, 'usage': {}},
                   'current': {'status': 'replayed', 'route': 'hold', 'rank': 1, 'label': 'needs_clarification',
                               'coverage': {'weighted': 0.4, 'weighted_upper': 0.8, 'unknown': 1},
                               'citation_failures': 0, 'mandatory_conflicts': 0, 'unresolved': 1,
                               'usage': {}}}], 'usage': {'model_calls': 0, 'charged_tokens': 0,
                                                       'actual_tokens': 0, 'unknown_usage_calls': 0},
        'fit': {'status': 'not_requested'}, 'limitations': [],
    }


def test_payload_keeps_hashes_counts_and_metrics_but_omits_all_free_text():
    """Break: dumping replay/label dictionaries exports candidate or ad text."""
    replay = replay_input()
    replay['candidate'] = {'name': 'SYNTHETIC-PRIVATE-TEXT'}
    replay['cases'][0]['current'].update(reason='SYNTHETIC-PRIVATE-TEXT', error='SYNTHETIC-PRIVATE-TEXT')
    replay['limitations'] = ['SYNTHETIC-PRIVATE-TEXT']
    metrics = compute_metrics(replay, {})
    metrics['candidate'] = 'SYNTHETIC-PRIVATE-TEXT'
    payload = report_payload(replay, metrics)
    assert payload['provenance']['data_hash'] == 'a' * 64
    assert payload['provenance']['labels_hash'] is None
    assert payload['counts'] == {'requested': 1, 'processed': 1, 'replayed': 1, 'deferred': 0}
    assert payload['metrics']['current']['ordering']['status'] == 'missing_labels'
    assert payload['cases'][0]['current']['label'] == 'needs_clarification'
    assert 'SYNTHETIC-PRIVATE-TEXT' not in json.dumps(payload, allow_nan=False)
    assert 'pending_outcomes_censored' in payload['limitations']


def test_report_writes_are_deterministic_private_and_idempotent(tmp_path):
    """Break: timestamps, permissive modes, mutable IDs or overwrite on repeat."""
    replay = replay_input()
    metrics = compute_metrics(replay, {})
    original = deepcopy(replay)
    folder = tmp_path / 'private' / 'evaluation'
    result = write_report(folder, replay, metrics)
    assert set(result) == {'report_id', 'json_path', 'markdown_path'}
    json_path, markdown_path = Path(result['json_path']), Path(result['markdown_path'])
    first_json, first_markdown = json_path.read_bytes(), markdown_path.read_bytes()
    first_stat = json_path.stat()
    assert json.loads(first_json)['provenance']['code_hash'] == 'b' * 64
    assert 'pending_outcomes_censored' in first_markdown.decode()
    assert folder.stat().st_mode & 0o777 == 0o700
    assert folder.parent.stat().st_mode & 0o777 == 0o700
    assert json_path.stat().st_mode & 0o777 == 0o600
    assert markdown_path.stat().st_mode & 0o777 == 0o600
    assert write_report(folder, replay, metrics) == result
    assert json_path.stat().st_mtime_ns == first_stat.st_mtime_ns
    assert json_path.read_bytes() == first_json
    assert markdown_path.read_bytes() == first_markdown
    assert replay == original
    other = write_report(tmp_path / 'second', replay, metrics)
    assert Path(other['json_path']).read_bytes() == first_json
    assert Path(other['markdown_path']).read_bytes() == first_markdown


def test_report_projection_drops_nested_text_and_nonfinite_numeric_fields():
    replay = replay_input()
    replay['cases'][0]['current']['coverage'].update(weighted=float('nan'), unknown='SYNTHETIC-PRIVATE-TEXT')
    replay['cases'][0]['current']['rank'] = True
    metrics = compute_metrics(replay, {})
    metrics['current']['ordering']['status'] = 'SYNTHETIC-PRIVATE-TEXT'
    metrics['current']['usage']['charged_tokens']['total'] = float('inf')
    metrics['current']['usage']['charged_tokens']['candidate'] = 'SYNTHETIC-PRIVATE-TEXT'
    payload = report_payload(replay, metrics)
    assert payload['cases'][0]['current']['coverage']['weighted'] is None
    assert payload['cases'][0]['current']['rank'] is None
    assert payload['metrics']['current']['ordering']['status'] is None
    assert payload['metrics']['current']['usage']['charged_tokens']['total'] is None
    assert 'SYNTHETIC-PRIVATE-TEXT' not in json.dumps(payload, allow_nan=False)


@pytest.mark.parametrize('field,value', [('baseline_id', '../outside'), ('baseline_id', 'private name'),
                                        ('data_hash', 'private-name'), ('code_hash', 'A' * 64)])
def test_unsafe_provenance_is_rejected_without_echoing_input(field, value):
    replay = replay_input()
    replay[field] = value
    with pytest.raises(AgenticError, match='^evaluation_report_invalid$'):
        report_payload(replay, {})


def test_invalid_case_identifiers_are_rejected():
    replay = replay_input()
    replay['cases'][0]['case_id'] = 'SYNTHETIC-PRIVATE-TEXT/..'
    with pytest.raises(AgenticError, match='^evaluation_report_invalid$'):
        report_payload(replay, {})


@pytest.mark.parametrize('link_depth', [0, 1])
def test_private_directory_symlinks_are_refused_without_traversal(tmp_path, link_depth):
    outside = tmp_path / 'outside'
    outside.mkdir()
    if link_depth:
        (tmp_path / 'private').mkdir()
        link = tmp_path / 'private' / 'evaluation'
        target = link
    else:
        link = tmp_path / 'private'
        target = link / 'evaluation'
    link.symlink_to(outside, target_is_directory=True)
    replay = replay_input()
    with pytest.raises(AgenticError, match='^evaluation_report_path_invalid$'):
        write_report(target, replay, compute_metrics(replay, {}))
    assert list(outside.iterdir()) == []


def test_report_file_symlink_is_refused_and_its_target_untouched(tmp_path):
    replay = replay_input()
    metrics = compute_metrics(replay, {})
    result = write_report(tmp_path / 'private', replay, metrics)
    json_path = Path(result['json_path'])
    outside = tmp_path / 'outside.json'
    outside.write_bytes(b'outside content')
    json_path.unlink()
    json_path.symlink_to(outside)
    with pytest.raises(AgenticError, match='^evaluation_report_path_invalid$'):
        write_report(tmp_path / 'private', replay, metrics)
    assert outside.read_bytes() == b'outside content'
    assert json_path.is_symlink()


@pytest.mark.parametrize('field', ['json_path', 'markdown_path'])
def test_existing_changed_report_is_a_safe_conflict_and_is_never_overwritten(tmp_path, field):
    replay = replay_input()
    metrics = compute_metrics(replay, {})
    result = write_report(tmp_path / 'private', replay, metrics)
    target = Path(result[field])
    target.write_bytes(b'preserve changed content')
    before = target.stat().st_mtime_ns
    with pytest.raises(AgenticError, match='^evaluation_report_conflict$'):
        write_report(tmp_path / 'private', replay, metrics)
    assert target.read_bytes() == b'preserve changed content'
    assert target.stat().st_mtime_ns == before


def test_report_identity_changes_with_provenance_and_labels_hash(tmp_path):
    replay = replay_input()
    metrics = compute_metrics(replay, {})
    first = write_report(tmp_path / 'private', replay, metrics)
    changed = deepcopy(replay)
    changed['labels_hash'] = 'f' * 64
    second = write_report(tmp_path / 'private', changed, metrics)
    assert first['report_id'] != second['report_id']
    assert Path(first['json_path']).exists()
    assert Path(second['json_path']).exists()


def test_holdout_reports_export_aggregate_metrics_without_case_review(tmp_path):
    """Break: exporting even IDs and ranks enables individual holdout inspection."""
    replay = replay_input()
    replay['partition'] = 'holdout'
    metrics = compute_metrics(replay, {})
    payload = report_payload(replay, metrics)
    assert payload['cases'] == []
    assert payload['counts'] == {'requested': 1, 'processed': 1, 'replayed': 1, 'deferred': 0}
    assert payload['metrics']['common_cases'] == 1
    result = write_report(tmp_path / 'private', replay, metrics)
    assert 'c-1-aabbccdd' not in Path(result['json_path']).read_text()
    assert 'c-1-aabbccdd' not in Path(result['markdown_path']).read_text()


def test_optional_fit_exports_only_evaluation_metadata():
    replay = replay_input()
    replay['fit'] = {'status': 'accepted', 'n_train': 20, 'n_holdout': 5, 'dataset_hash': 'f' * 64,
                     'fit_id': 'fit-synthetic-001', 'activation': 'evaluation_only',
                     'reason': 'SYNTHETIC-PRIVATE-TEXT', 'model_text': 'SYNTHETIC-PRIVATE-TEXT'}
    payload = report_payload(replay, {})
    assert payload['fit'] == {'status': 'accepted', 'n_train': 20, 'n_holdout': 5, 'dataset_hash': 'f' * 64,
                              'fit_id': 'fit-synthetic-001', 'activation': 'evaluation_only'}
    assert 'SYNTHETIC-PRIVATE-TEXT' not in json.dumps(payload)
    replay['fit']['fit_id'] = '../SYNTHETIC-PRIVATE-TEXT'
    with pytest.raises(AgenticError, match='^evaluation_report_invalid$'):
        report_payload(replay, {})
