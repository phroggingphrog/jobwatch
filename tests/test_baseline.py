"""Synthetic tests for the frozen-baseline models, gate version, grouping and tags."""
import random
import re
from pathlib import Path

import pytest

from pipeline.agentic import baseline
from tests.baseline_support import synthetic_case

ROOT = Path(__file__).resolve().parent.parent


def test_tags_are_the_six_contract_tags():
    assert baseline.TAGS == ('previously_rejected', 'transferable_skills', 'unknown_facts',
                             'misleading_title', 'stretch', 'explicit_exclusion')


@pytest.mark.parametrize('kwargs, tag, expected', [
    ({'route': 'archive', 'reason': 'hard_gate'}, 'previously_rejected', True),
    ({'stored': {'run_status': 'archived'}}, 'previously_rejected', True),
    ({'stored': {'application_status': 'skipped'}}, 'previously_rejected', True),
    ({}, 'previously_rejected', False),
    ({'requirements': (('r1', 'high', 'partial'),)}, 'transferable_skills', True),
    ({'requirements': (('r1', 'high', 'demonstrated'),)}, 'transferable_skills', False),
    ({'requirements': (('r1', 'high', 'unknown'),)}, 'unknown_facts', True),
    ({'requirements': (('r1', 'high', 'legacy_missing'),)}, 'unknown_facts', True),
    ({'uncertainties': ('hours',)}, 'unknown_facts', True),
    ({'location_fit': 'unknown'}, 'unknown_facts', True),
    ({}, 'unknown_facts', False),
    ({'title': 'Junior Analyst', 'seniority': 'senior'}, 'misleading_title', True),
    ({'title': 'Junior Analyst', 'min_years': 3}, 'misleading_title', True),
    ({'title': 'Senior Analyst', 'seniority': 'entry'}, 'misleading_title', True),
    ({'title': 'Senior Analyst', 'seniority': 'senior'}, 'misleading_title', False),
    ({'title': 'Analyst', 'seniority': 'mid'}, 'misleading_title', False),
    ({'requirements': (('r1', 'high', 'partial'), ('r2', 'preferred', 'demonstrated'))}, 'stretch', True),
    ({'requirements': (('r1', 'high', 'contradicted'), ('r2', 'preferred', 'demonstrated'))}, 'stretch', False),
    ({'requirements': (('r1', 'preferred', 'partial'), ('r2', 'high', 'demonstrated'))}, 'stretch', False),
    ({'requirements': (('r1', 'high', 'demonstrated'),)}, 'stretch', False),
    ({'route': 'archive', 'reason': 'policy_excluded'}, 'explicit_exclusion', True),
    ({'route': 'archive', 'reason': 'hard_gate'}, 'explicit_exclusion', False),
])
def test_tag_rules(kwargs, tag, expected):
    assert (tag in baseline.tag_case(synthetic_case(**kwargs))) is expected


def test_tags_come_back_in_contract_order():
    case = synthetic_case(route='archive', reason='policy_excluded', location_fit='unknown',
                          requirements=(('r1', 'high', 'partial'),))
    tags = baseline.tag_case(case)
    assert tags == tuple(t for t in baseline.TAGS if t in tags)
    assert {'previously_rejected', 'transferable_skills', 'unknown_facts', 'explicit_exclusion'} <= set(tags)


def test_gate_sources_are_the_reconciled_gate_files():      # contract decision 5
    assert set(baseline.gate_sources()) == {
        'pipeline.agentic.gate', 'pipeline.agentic.location', 'jobwatch.candidate.person',
        'jobwatch.reader', 'jobwatch.candidate.contracts', 'jobwatch.candidate.policy',
        'pipeline.agentic/data/vic-geo.json', 'pipeline.agentic/data/metro-localities.json'}
    assert re.fullmatch(r'[0-9a-f]{64}', baseline.GATE_VERSION)
    assert baseline.GATE_VERSION == baseline.current_gate_version()


def _patched_copy(tmp_path, monkeypatch, key, original: Path):
    copy = tmp_path / original.name
    copy.write_bytes(original.read_bytes() + b'\n')
    real = baseline._source_path
    monkeypatch.setattr(baseline, '_source_path', lambda k: copy if k == key else real(k))


def test_gate_version_changes_by_itself_when_a_gate_source_changes(tmp_path, monkeypatch):
    _patched_copy(tmp_path, monkeypatch, 'pipeline.agentic.gate', ROOT / 'pipeline/agentic/gate.py')
    assert baseline.current_gate_version() != baseline.GATE_VERSION


@pytest.mark.parametrize('key, original', [
    ('pipeline.agentic/data/vic-geo.json', 'pipeline/agentic/data/vic-geo.json'),
    ('pipeline.agentic/data/metro-localities.json', 'pipeline/agentic/data/metro-localities.json'),
    ('jobwatch.candidate.policy', 'jobwatch/candidate/policy.py'),
])
def test_a_changed_data_file_or_policy_module_changes_the_gate_version(tmp_path, monkeypatch, key, original):
    _patched_copy(tmp_path, monkeypatch, key, ROOT / original)
    assert baseline.current_gate_version() != baseline.GATE_VERSION


def test_a_missing_policy_module_is_left_out(tmp_path, monkeypatch):
    real = baseline._source_path
    monkeypatch.setattr(baseline, '_source_path',
                        lambda k: tmp_path / 'absent.py' if k == 'jobwatch.candidate.policy' else real(k))
    assert 'jobwatch.candidate.policy' not in baseline.gate_sources()


def test_pre_revision_gate_version_is_a_digest():
    assert re.fullmatch(r'[0-9a-f]{64}', baseline.PRE_REVISION_GATE_VERSION)


def _keys():
    return {'A': ('content:c1', 'employer:acme'), 'B': ('content:c1', 'employer:other'),
            'C': ('content:c2', 'employer:solo')}


def test_duplicate_adverts_share_a_group():
    g = baseline.group_ids(_keys())
    assert g['A'] == g['B'] != g['C']


def test_related_employer_cases_share_a_group():
    g = baseline.group_ids({'A': ('content:c1', 'employer:acme'), 'B': ('content:c2', 'employer:acme')})
    assert g['A'] == g['B']


def test_grouping_is_transitive():
    g = baseline.group_ids({'A': ('content:c1', 'employer:acme'), 'B': ('content:c1', 'employer:beta'),
                            'C': ('content:c9', 'employer:beta'), 'D': ('content:c5', 'employer:delta')})
    assert g['A'] == g['B'] == g['C'] != g['D']


def test_group_id_ignores_input_order_and_fits_the_comparison_limit():
    keys = {**_keys(), 'D': ('content:c5', 'employer:delta')}
    items = list(keys.items())
    random.Random(7).shuffle(items)
    shuffled = baseline.group_ids(dict(items))
    assert shuffled == baseline.group_ids(keys)
    assert all(len(v) <= 128 and v.startswith('group:') for v in shuffled.values())
    reordered = {k: tuple(reversed(v)) for k, v in keys.items()}
    assert baseline.group_ids(reordered) == shuffled


def test_blank_employer_never_merges_strangers():
    k = baseline.group_keys_for({'company': 'Pty Ltd', 'dedupe_key': '|junior analyst|melbourne'}, 'h1')
    assert k == ('content:h1',)


def test_dedupe_key_needs_company_and_title_parts():
    both = baseline.group_keys_for({'company': 'Acme', 'dedupe_key': 'acme|analyst|melbourne'}, 'h1')
    assert both == ('content:h1', 'dedupe:acme|analyst|melbourne', 'employer:acme')
    no_title = baseline.group_keys_for({'company': 'Acme', 'dedupe_key': 'acme||melbourne'}, 'h1')
    assert no_title == ('content:h1', 'employer:acme')


def test_company_spellings_normalise_to_one_employer_key():
    a = baseline.group_keys_for({'company': 'Acme Pty Ltd', 'dedupe_key': ''}, 'h1')
    b = baseline.group_keys_for({'company': 'ACME Group', 'dedupe_key': ''}, 'h2')
    assert 'employer:acme' in a and 'employer:acme' in b


def test_synthetic_case_sets_a_deterministic_group_id():
    one = synthetic_case(group_keys=('employer:acme',))
    two = synthetic_case('c-2', group_keys=('employer:acme',))
    assert one.group_id == two.group_id and len(one.group_id) <= 128
    assert synthetic_case().group_id != one.group_id


def test_models_carry_the_contract_fields():
    case_fields = {'case_id', 'posting_id', 'group_id', 'tags', 'snapshot', 'structural_inputs', 'evaluation',
                   'candidate', 'model_insights', 'decision', 'commute_km', 'usage',
                   'run_key', 'group_keys', 'stored', 'blob_refs'}
    base_fields = {'baseline_id', 'created_at', 'git_commit', 'gate_version', 'implementation_version',
                   'matching_version', 'profile_version', 'profile_files_sha256', 'case_ids', 'gate_dependencies',
                   'person', 'policy', 'runtime_config_sha256', 'evidence_bundle_hash', 'approved_sha256',
                   'decision_policy_sha256', 'case_sha256', 'content_sha256', 'summary'}
    assert case_fields <= set(baseline.FrozenCase.model_fields)
    assert base_fields <= set(baseline.Baseline.model_fields)
    assert baseline.Baseline.model_fields['decision_policy_sha256'].default is None
