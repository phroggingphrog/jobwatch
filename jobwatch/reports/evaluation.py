"""Data-minimised, deterministic private reports for frozen evaluation replays.

Only known numeric fields and closed enums cross this export boundary. In
particular, owner notes, model output, reasons, errors and source text never do.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import secrets
import stat
import re
from pathlib import Path

from pipeline.agentic.contracts import AgenticError

REPORT_VERSION = 'evaluation-report-v1'
LIMITATIONS = (
    'synthetic_checks_do_not_establish_quality',
    'exposure_and_selection_bias',
    'no_propensity_estimation',
    'pending_outcomes_censored',
    'citation_checks_not_independent_qualification',
    'condensed_human_labelled_ordering',
    'frozen_baseline_gate_provenance',
    'cost_not_comparable_reused_outputs',
    'significance_not_assessed',
)
_IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z')
_HASH = re.compile(r'[0-9a-f]{64}\Z')
_COUNT, _NUMBER, _SIGNED = object(), object(), object()
_STATUS = frozenset({'complete', 'partial_replay', 'measured', 'missing_labels', 'zero_ideal'})
_BASIS = frozenset({'condensed_human_labelled_ordering', 'citation_checks_not_independent_qualification',
                    'recorded', 'not_measured'})
_SIMPLE_METRIC = {'status': _STATUS, 'labelled': _COUNT, 'minimum': _COUNT, 'value': _NUMBER,
                  'count': _COUNT, 'of': _COUNT, 'rate': _NUMBER, 'held': _COUNT}
_ORDERING = {
    **_SIMPLE_METRIC, 'basis': _BASIS, 'labelled_ranked': _COUNT,
    'coverage': {'labelled_cases': _COUNT, 'common_cases': _COUNT, 'fraction': _NUMBER},
    'precision_at': {str(k): {'status': frozenset({'measured', 'short_prefix'}), 'value': _NUMBER,
                              'count': _COUNT, 'of': _COUNT, 'ranked': _COUNT} for k in (5, 10)},
    'ndcg_at': {str(k): {'status': _STATUS, 'value': _NUMBER} for k in (5, 10)},
}
_AGGREGATE = {'total': _NUMBER, 'recorded': _COUNT, 'missing': _COUNT}
_USAGE = {'charged_tokens': _AGGREGATE, 'actual_tokens': _AGGREGATE,
          'latency_seconds': {**_AGGREGATE, 'basis': _BASIS, 'mean': _NUMBER, 'median': _NUMBER, 'p95': _NUMBER}}
_ARM = {'missed_suitable': _SIMPLE_METRIC, 'exclusion_violations': _SIMPLE_METRIC,
        'ordering': _ORDERING, 'usage': _USAGE}
_CURRENT = {
    **_ARM,
    'deterministic_indicators': {
        'basis': _BASIS, **{field: _COUNT for field in (
            'citation_failures', 'cases_with_citation_failures', 'mandatory_conflicts',
            'cases_with_mandatory_conflicts', 'mandatory_unmet')}},
    'uncertainty': {field: _COUNT for field in (
        'unknown', 'contradicted', 'unresolved', 'cases_with_unknowns', 'cases_with_contradictions',
        'unresolved_shortlisted', 'disclosed', 'disclosure_recorded', 'disclosure_missing')},
}
_PAIRED = {**_SIMPLE_METRIC, 'fixed': _COUNT, 'broke': _COUNT, 'delta': _SIGNED}
_METRICS = {'version': frozenset({'evaluation-metrics-v1'}), 'status': _STATUS, 'common_cases': _COUNT,
            'baseline': _ARM, 'current': _CURRENT,
            'comparison': {'status': _STATUS, 'value': _NUMBER, 'missed_suitable': _PAIRED,
                           'exclusion_violations': _PAIRED}}
_ROUTES = frozenset({'draft', 'hold', 'archive', 'error'})
_LABELS = frozenset({'stronger_match', 'stretch', 'needs_clarification'})
_CASE_BASELINE = {'route': _ROUTES, 'rank': _COUNT, 'score': _NUMBER}
_CASE_CURRENT = {
    'status': frozenset({'replayed', 'deferred'}), 'route': _ROUTES, 'rank': _COUNT, 'label': _LABELS,
    'coverage': {field: _NUMBER for field in ('weighted', 'weighted_upper', 'unknown', 'contradicted', 'mandatory_unmet')},
    'citation_failures': _COUNT, 'mandatory_conflicts': _COUNT, 'unresolved': _COUNT,
}


def _project(value, schema):
    """Project one known schema; never retain an unknown key or string."""
    if isinstance(schema, dict):
        return {key: _project(value[key], spec) for key, spec in schema.items() if key in value} \
            if type(value) is dict else {}
    if isinstance(schema, frozenset):
        return value if type(value) is str and value in schema else None
    if type(value) not in (int, float):
        return None
    try:
        finite = math.isfinite(value)
    except OverflowError:
        return None
    if not finite or abs(value) > 1e100:
        return None
    if schema is _COUNT and (type(value) is not int or value < 0):
        return None
    if schema is _NUMBER and value < 0:
        return None
    return value


def _identifier(value):
    if type(value) is not str or not _IDENTIFIER.fullmatch(value):
        raise AgenticError('evaluation_report_invalid')
    return value


def _hash(value, *, nullable=False):
    if value is None and nullable:
        return None
    if type(value) is not str or not _HASH.fullmatch(value):
        raise AgenticError('evaluation_report_invalid')
    return value


def report_payload(replay: dict, metrics: dict) -> dict:
    """Return the allowlisted report body, with no paths or current timestamp."""
    if (replay.get('version') != 'evaluation-v1' or replay.get('partition') not in ('development', 'holdout')
            or replay.get('status') not in ('complete', 'bounded') or replay.get('ordering') != 'provisional'
            or replay.get('ranking_rules_version') != 'ranking-rules-v1'):
        raise AgenticError('evaluation_report_invalid')
    provenance = {'baseline_id': _identifier(replay.get('baseline_id')), 'partition': replay['partition']}
    for key in ('data_hash', 'code_hash', 'split_hash', 'inputs_hash', 'labels_hash', 'baseline_gate_version'):
        provenance[key] = _hash(replay.get(key), nullable=key == 'labels_hash')
    provenance['ranking_rules_version'] = replay['ranking_rules_version']
    cases = []
    seen = set()
    for case in replay.get('cases', []):
        ident = _identifier(case.get('case_id'))
        posting_id = case.get('posting_id')
        if ident in seen or type(posting_id) is not int or not 0 < posting_id <= 2 ** 63 - 1:
            raise AgenticError('evaluation_report_invalid')
        seen.add(ident)
        cases.append({'case_id': ident, 'posting_id': posting_id,
                      'baseline': _project(case.get('baseline'), _CASE_BASELINE),
                      'current': _project(case.get('current'), _CASE_CURRENT)})
    cases.sort(key=lambda case: (case['case_id'], case['posting_id']))
    counts = _project(replay, {'requested': _COUNT, 'processed': _COUNT})
    counts.update(replayed=sum(case['current'].get('status') == 'replayed' for case in cases),
                  deferred=sum(case['current'].get('status') == 'deferred' for case in cases))
    fit = _project(replay.get('fit'), {
        'status': frozenset({'not_requested', 'insufficient_data', 'deadline', 'timeout',
                             'fit_unavailable', 'accepted', 'rejected'}),
        'n_train': _COUNT, 'n_holdout': _COUNT, 'activation': frozenset({'evaluation_only'})})
    raw_fit = replay.get('fit')
    if type(raw_fit) is dict:
        if 'dataset_hash' in raw_fit:
            fit['dataset_hash'] = _hash(raw_fit['dataset_hash'], nullable=True)
        if 'fit_id' in raw_fit:
            fit['fit_id'] = _identifier(raw_fit['fit_id']) if raw_fit['fit_id'] is not None else None
    return {'version': REPORT_VERSION, 'provenance': provenance, 'ordering': 'provisional',
            'status': replay['status'],
            'stop_reason': _project(replay.get('stop_reason'), frozenset({'case_limit', 'deadline', 'budget'})),
            'counts': counts, 'cases': [] if replay['partition'] == 'holdout' else cases,
            'metrics': _project(metrics, _METRICS), 'fit': fit,
            'usage': _project(replay.get('usage'), {field: _COUNT for field in (
                'model_calls', 'charged_tokens', 'actual_tokens', 'unknown_usage_calls')}),
            'limitations': list(LIMITATIONS)}


def _json_bytes(payload):
    return (json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + '\n').encode('utf-8')


def _markdown(payload, report_id):
    provenance = payload['provenance']
    lines = ['# Frozen evaluation', '', f'Report: `{report_id}`', '',
             f"Baseline: `{provenance['baseline_id']}`", '',
             f"Partition: {provenance['partition']}; replay: {payload['status']}; ordering: provisional.", '',
             '## Counts', '', '| Measure | Count |', '| --- | ---: |']
    lines.extend(f'| {key} | {value} |' for key, value in sorted(payload['counts'].items()))
    lines.extend(['', '## Provenance', '', '| Input | Version or digest |', '| --- | --- |'])
    lines.extend(f'| {key} | `{value}` |' for key, value in sorted(provenance.items()))
    lines.extend(['', '## Metrics', '', '```json', _json_bytes(payload['metrics']).decode().rstrip(), '```', '',
                  '## Usage', '', '```json', _json_bytes(payload['usage']).decode().rstrip(), '```', '',
                  '## Optional fit', '', '```json', _json_bytes(payload['fit']).decode().rstrip(), '```', '',
                  '## Limitations', ''])
    lines.extend(f'- {limitation}' for limitation in payload['limitations'])
    return ('\n'.join(lines) + '\n').encode('utf-8')


@contextlib.contextmanager
def _private_folder(folder):
    # Do not resolve(): following a symlink here would hide the unsafe component.
    absolute = Path(folder).absolute()
    if '..' in absolute.parts or absolute == Path(absolute.anchor):
        raise AgenticError('evaluation_report_path_invalid')
    descriptor = None
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor = os.open(absolute.anchor, flags)
        for component in absolute.parts[1:]:
            try:
                os.mkdir(component, mode=0o700, dir_fd=descriptor)
            except FileExistsError:
                pass
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        os.fchmod(descriptor, 0o700)
        yield descriptor, absolute
    except OSError:
        raise AgenticError('evaluation_report_path_invalid') from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _matches(directory, name, content):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return False
    except OSError:
        raise AgenticError('evaluation_report_path_invalid') from None
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise AgenticError('evaluation_report_path_invalid')
        if info.st_size != len(content) or stream.read(len(content) + 1) != content:
            raise AgenticError('evaluation_report_conflict')
        os.fchmod(stream.fileno(), 0o600)
    return True


def _publish(directory, name, content):
    # Publish a completed private inode atomically; never truncate an existing file.
    temporary = f'.evaluation-{secrets.token_hex(16)}.tmp'
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        except FileExistsError:
            _matches(directory, name, content)
    finally:
        os.unlink(temporary, dir_fd=directory)


def write_report(folder: Path, replay: dict, metrics: dict) -> dict:
    """Write immutable content-addressed JSON/Markdown in a private directory.

    The caller owns person isolation and holdout-access auditing. This function
    accepts no candidate files, reads no labels, and never starts runtime work.
    """
    payload = report_payload(replay, metrics)
    json_content = _json_bytes(payload)
    report_id = 'eval-' + hashlib.sha256(json_content).hexdigest()
    markdown_content = _markdown(payload, report_id)
    names = {f'{report_id}.json': json_content, f'{report_id}.md': markdown_content}
    with _private_folder(folder) as (directory, absolute):
        existing = {name: _matches(directory, name, content) for name, content in names.items()}
        for name, content in names.items():
            if not existing[name]:
                _publish(directory, name, content)
        os.fsync(directory)
    return {'report_id': report_id, 'json_path': str(absolute / f'{report_id}.json'),
            'markdown_path': str(absolute / f'{report_id}.md')}
