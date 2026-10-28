"""Synthetic tests for the frozen-baseline models, gate version, grouping and tags."""
import fcntl
import json
import os
import random
import re
import stat
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from jobwatch.util import adtext as adtext
from jobwatch import users
from jobwatch.apply import paths as apaths
from jobwatch.candidate import intake
from jobwatch.util.llm import LLM
from pipeline.agentic import baseline
from pipeline.agentic.baseline import (
    OwnerLabel, effective_tags, label_case, latest_labels, read_labels, write_label,
)
from pipeline.agentic.contracts import AgenticError
from pipeline.agentic.location import km_from_home
from pipeline.agentic.service import agentic_batch_run
from tests.baseline_support import frozen, synthetic_case, world  # noqa: F401  (fixtures)
from tests.test_agentic_service import SyntheticGateway

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
        'jobwatch.candidate.eligibility', 'jobwatch.candidate.projection', 'jobwatch.models',
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
    ('jobwatch.candidate.eligibility', 'jobwatch/candidate/eligibility.py'),
    ('jobwatch.candidate.projection', 'jobwatch/candidate/projection.py'),
    ('jobwatch.models', 'jobwatch/models.py'),
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


# --------------------------------------------------------------------------- freeze, load and replay-pinning

def _dir(baseline_id):
    return users.user_dir() / 'baselines' / baseline_id


def _code(excinfo):
    return excinfo.value.code


def _profile_yaml(**changes):
    """Edit the live profile.yaml (synthetic) the way a person would: work rights hours limit, home suburb."""
    path = apaths.profile_dir() / 'profile.yaml'
    doc = yaml.safe_load(path.read_text()) if path.exists() else {}
    candidate = doc.setdefault('candidate', {})
    if 'hours' in changes:
        rights = candidate.setdefault('work_rights', {})
        if changes['hours'] is None:
            rights.pop('hours_limit_per_fortnight', None)
        else:
            rights['hours_limit_per_fortnight'] = changes['hours']
    if 'location' in changes:
        candidate['location'] = changes['location']
    path.write_text(yaml.safe_dump(doc))


def _evaluated(world, *ids, long_hours=False):
    """Evaluate synthetic postings and return a read-only connection."""
    import sqlite3
    conn, config, bundle, add = world
    for ident in ids:
        text = add(ident)
        if long_hours:
            adtext.save_text(conn, ident, text.replace('24 hours per week', '38 hours per week'), 'synthetic-full')
    conn.commit()
    agentic_batch_run(list(ids), config, conn, evidence_bundle=bundle,
                      llm=LLM(transport=SyntheticGateway(bundle), keys=['synthetic']), operation='evaluate')
    conn.commit()
    ro = sqlite3.connect(f'file:{config.db_path}?mode=ro', uri=True)
    ro.row_factory = sqlite3.Row
    return ro


def test_freeze_writes_a_private_hash_verified_baseline(frozen):
    b = baseline.freeze_baseline(frozen.ro, frozen.config)
    assert len(b.case_ids) == 3 and all(re.fullmatch(r'c-4[234]-[0-9a-f]{8}', c) for c in b.case_ids)
    assert b.gate_version == baseline.GATE_VERSION and b.person == users.current()
    assert b.profile_version == 2 and set(b.profile_files_sha256) <= set(baseline.PROFILE_FILES)
    root = _dir(b.baseline_id)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    for path in root.rglob('*'):
        assert stat.S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600), path
    loaded, cases = baseline.load_baseline(b.baseline_id)
    assert loaded == b and [c.posting_id for c in cases] == [42, 43, 44]
    by = {c.posting_id: c for c in cases}
    assert (by[42].decision['route'], by[42].decision['reason']) == ('draft', 'eligible')
    assert (by[44].decision['route'], by[44].decision['reason']) == ('draft', 'eligible')
    assert by[44].stored['run_status'] != 'archived'
    assert by[44].stored['run_reason'] == by[42].stored['run_reason'] == 'evaluation_complete'
    assert by[42].evaluation['global_score'] == 4.3 and by[44].evaluation['global_score'] == 2.7
    assert 'previously_rejected' not in by[44].tags and all(c.tags == baseline.tag_case(c) for c in cases)
    assert by[42].usage['charged_tokens'] > 0 and by[42].usage['actual_tokens'] is None and by[42].usage['latency_seconds'] > 0
    assert by[42].group_id == by[43].group_id != by[44].group_id        # 'Synthetic Alpha' and 'Synthetic Alpha Pty Ltd'
    assert by[42].snapshot['full_ad'] and by[42].candidate and by[42].structural_inputs['reference_utf8']
    assert b.summary['cases'] == 3 and b.summary['routes'] == {'draft': 3, 'archive': 0, 'hold': 0, 'error': 0}
    assert set(b.summary['tags']) == set(baseline.TAGS) and b.summary['groups'] == 2
    assert b.summary['largest_group'] == 2 and b.summary['decision_errors'] == 0
    assert re.fullmatch(r'bl-\d{8}T\d{6}Z-[0-9a-f]{8}', b.baseline_id) and b.baseline_id.endswith(b.content_sha256[:8])
    assert baseline.list_baselines() == [b]


def test_freeze_calls_no_model_and_writes_no_database_row(frozen):
    dump = lambda: '\n'.join(frozen.ro.iterdump())          # noqa: E731
    before, calls = dump(), len(frozen.gateway.calls)
    baseline.freeze_baseline(frozen.ro, frozen.config)
    assert dump() == before and len(frozen.gateway.calls) == calls
    with pytest.raises(Exception, match='readonly'):
        frozen.ro.execute("INSERT INTO state(key,value) VALUES('x','y')")


def test_large_shared_artifacts_are_stored_once(frozen):
    b = baseline.freeze_baseline(frozen.ro, frozen.config)
    root = _dir(b.baseline_id)
    assert 0 < len(list((root / 'blobs').iterdir())) <= 3
    assert max(p.stat().st_size for p in (root / 'cases').iterdir()) < 200_000
    _, cases = baseline.load_baseline(b.baseline_id)
    assert cases[0].structural_inputs['reference_utf8'] is cases[1].structural_inputs['reference_utf8']
    assert cases[0].snapshot['contents'] == cases[2].snapshot['contents'] != {}
    assert cases[0].blob_refs and set(cases[0].blob_refs) <= {'candidate', 'structural_inputs.reference_utf8',
                                                              'snapshot.contents'}


def _flip(path):
    raw = bytearray(path.read_bytes())
    raw[len(raw) // 2] ^= 1
    path.write_bytes(bytes(raw))


def test_tampered_baseline_is_refused(frozen):
    b = baseline.freeze_baseline(frozen.ro, frozen.config)
    root = _dir(b.baseline_id)
    victim = next(iter(sorted(root.glob('profile/*.yaml'))), None) or next(iter(sorted(root.glob('profile/*'))))
    _flip(victim)
    with pytest.raises(AgenticError) as err:
        baseline.pinned_profile(b.baseline_id).__enter__()
    assert _code(err) == 'baseline_corrupt'
    _flip(victim)                                                        # restored
    with baseline.pinned_profile(b.baseline_id):
        pass
    _flip(next(iter(sorted((root / 'cases').iterdir()))))
    with pytest.raises(AgenticError) as err:
        baseline.load_baseline(b.baseline_id)
    assert _code(err) == 'baseline_corrupt'


def test_a_tampered_blob_is_refused(frozen):
    b = baseline.freeze_baseline(frozen.ro, frozen.config)
    _flip(next(iter(sorted((_dir(b.baseline_id) / 'blobs').iterdir()))))
    with pytest.raises(AgenticError) as err:
        baseline.load_baseline(b.baseline_id)
    assert _code(err) == 'baseline_corrupt'


def test_loading_historical_source_inventory_never_rewrites_frozen_records(frozen):
    """A historical fingerprint remains historical when new gate sources are tracked."""
    b = baseline.freeze_baseline(frozen.ro, frozen.config)
    root = _dir(b.baseline_id)
    path = root / 'baseline.json'
    record = json.loads(path.read_bytes())
    historical = {key: value for key, value in record['gate_dependencies'].items()
                  if key not in ('jobwatch.candidate.eligibility', 'jobwatch.candidate.projection')}
    record['gate_dependencies'] = historical
    record['gate_version'] = baseline.digest(historical)
    path.write_text(json.dumps(record, sort_keys=True))
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    loaded, cases = baseline.load_baseline(b.baseline_id)
    assert loaded.gate_dependencies == historical
    assert loaded.gate_version != baseline.current_gate_version()
    assert baseline.list_baselines() == [loaded]
    assert baseline.frozen_approved(b.baseline_id)['version'] == loaded.profile_version
    assert cases and baseline.read_labels(b.baseline_id) == []
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()} == before


def test_decision_follows_the_frozen_profile_not_later_edits(world, monkeypatch):
    from jobwatch.candidate.policy import DecisionPolicy
    from tests.candidate.policy_fixtures import fact
    ro = _evaluated(world, 42, long_hours=True)
    config = world[1]
    approved = intake.current_version(users.current())
    limited = {**approved, 'facts': [*approved['facts'], fact('work_rights', {'hours_limit_per_fortnight': 48})]}
    monkeypatch.setattr(intake, 'current_version', lambda person: limited)
    _profile_yaml(hours=48)
    b = baseline.freeze_baseline(ro, config)
    _, (case,) = baseline.load_baseline(b.baseline_id)
    assert case.stored['run_reason'] == 'evaluation_complete'
    assert (case.decision['route'], case.decision['reason']) == ('archive', 'hard_gate')
    assert b.summary['evidence_mismatch'] == 1                           # profile.yaml is in the evidence bundle
    _profile_yaml(hours=None)
    monkeypatch.setattr(intake, 'current_version', lambda person: approved)
    assert baseline.decide_frozen(case.snapshot, case.evaluation, commute_km=None)['route'] == 'draft'    # live profile
    pinned = DecisionPolicy.model_validate(baseline.frozen_decision_policy(b.baseline_id))
    with baseline.pinned_profile(b.baseline_id):
        assert baseline.decide_frozen(case.snapshot, case.evaluation, commute_km=None,
                                      decision_policy=pinned) == case.decision


def test_commute_is_measured_from_the_frozen_home(world, monkeypatch):
    from jobwatch.candidate.policy import DecisionPolicy
    from pipeline.agentic.location import commute_km_for
    from tests.candidate.policy_fixtures import fact
    ro = _evaluated(world, 42)
    config = world[1]
    approved = intake.current_version(users.current())
    homed = {**approved, 'facts': [*approved['facts'], fact('location', {'home': 'Brunswick, VIC'})]}
    monkeypatch.setattr(intake, 'current_version', lambda person: homed)
    _profile_yaml(location='Brunswick, VIC')
    b = baseline.freeze_baseline(ro, config)
    _, (case,) = baseline.load_baseline(b.baseline_id)
    assert case.commute_km == 5.0
    _profile_yaml(location='Geelong, VIC')
    pinned = DecisionPolicy.model_validate(baseline.frozen_decision_policy(b.baseline_id))
    assert commute_km_for('Geelong, VIC', 'Melbourne VIC') != 5
    with baseline.pinned_profile(b.baseline_id):
        assert commute_km_for(pinned.home['place'], 'Melbourne VIC') == 5


def test_the_pinned_profile_version_is_frozen_with_the_baseline(frozen):      # contract decision 1
    b = baseline.freeze_baseline(frozen.ro, frozen.config)
    approved = baseline.frozen_approved(b.baseline_id)
    assert approved == intake.current_version(users.current()) and b.decision_policy_sha256
    assert baseline.frozen_decision_policy(b.baseline_id)['profile_version'] == approved['version']
    assert (_dir(b.baseline_id) / 'decision_policy.json').is_file()
    # a later intake version does not change what frozen_approved returns
    later = {**approved, 'version': approved['version'] + 1}
    intake_current = intake.current_version
    try:
        intake.current_version = lambda person: later
        assert baseline.frozen_approved(b.baseline_id) == approved
    finally:
        intake.current_version = intake_current
    _flip(_dir(b.baseline_id) / 'approved.json')
    with pytest.raises(AgenticError) as err:
        baseline.frozen_approved(b.baseline_id)
    assert _code(err) == 'baseline_corrupt'


def test_the_decision_policy_is_frozen_only_when_the_policy_path_is_active(frozen, monkeypatch):
    class Fake:                                    # stands in for Plan 2's DecisionPolicy
        home = None                                # the freeze measures the commute from the policy's home
        def model_dump(self, mode='json'): return {'profile_version': 2, 'policy_hash': 'f' * 64}
    monkeypatch.setattr(baseline, '_active_decision_policy', lambda config, approved: Fake())
    seen = []
    monkeypatch.setattr(baseline, 'decide_frozen', lambda *a, decision_policy=None, **k: seen.append(decision_policy) or {'route': 'draft', 'reason': 'eligible'})
    b = baseline.freeze_baseline(frozen.ro, frozen.config)
    assert baseline.frozen_decision_policy(b.baseline_id) == {'profile_version': 2, 'policy_hash': 'f' * 64}
    assert b.decision_policy_sha256 and seen and all(isinstance(p, Fake) for p in seen)
    _flip(_dir(b.baseline_id) / 'decision_policy.json')
    with pytest.raises(AgenticError) as err:
        baseline.frozen_decision_policy(b.baseline_id)
    assert _code(err) == 'baseline_corrupt'


def test_the_decision_policy_path_is_inactive_in_this_phase(frozen):
    assert baseline._active_decision_policy(frozen.config, {'version': 2}) is None


def test_decide_frozen_reports_an_unbuildable_snapshot(frozen):
    b = baseline.freeze_baseline(frozen.ro, frozen.config)
    _, (case, *_) = baseline.load_baseline(b.baseline_id)
    assert baseline.decide_frozen({**case.snapshot, 'contents': {}}, case.evaluation, commute_km=None) == {
        'error': 'evidence_snapshot_invalid'}
    assert baseline.decide_frozen(case.snapshot, {'not': 'an evaluation'}, commute_km=None) == {'error': 'invalid_gate_input'}


def test_a_failed_freeze_leaves_no_visible_baseline(frozen, monkeypatch):
    real, calls = baseline.safe_write_bytes, []

    def failing(path, data):
        calls.append(path)
        if len(calls) == 3:
            raise OSError('disk full')
        return real(path, data)
    monkeypatch.setattr(baseline, 'safe_write_bytes', failing)
    with pytest.raises(OSError):
        baseline.freeze_baseline(frozen.ro, frozen.config)
    assert baseline.list_baselines() == []
    assert list((users.user_dir() / 'baselines').iterdir()) == []


def test_baselines_are_per_person_and_ids_cannot_escape(frozen):
    b = baseline.freeze_baseline(frozen.ro, frozen.config)
    users.create_user_dirs('friend')
    with users.use('friend'):
        with pytest.raises(AgenticError) as err:
            baseline.load_baseline(b.baseline_id)
        assert _code(err) == 'baseline_not_found'
        assert baseline.list_baselines() == []
    for bad in ('../x', 'bl-20260101T000000Z-zzzzzzzz', '', b.baseline_id + '\n'):
        for call in (baseline.load_baseline, lambda i: baseline.pinned_profile(i).__enter__(),
                     baseline.frozen_approved, baseline.frozen_decision_policy):
            with pytest.raises(AgenticError) as err:
                call(bad)
            assert _code(err) == 'invalid_baseline_id'
    with pytest.raises(AgenticError) as err:
        baseline.load_baseline('bl-20260101T000000Z-0123abcd')
    assert _code(err) == 'baseline_not_found'


def test_freeze_refuses_without_a_profile_version_or_cases(world):
    conn, config, bundle, add = world
    users.create_user_dirs('friend')
    with users.use('friend'):
        with pytest.raises(AgenticError) as err:
            baseline.freeze_baseline(conn, config)
        assert _code(err) == 'no_profile_version'
    with pytest.raises(AgenticError) as err:
        baseline.freeze_baseline(conn, config)
    assert _code(err) == 'no_cases'
    assert not (users.user_dir() / 'baselines').exists()


def test_unreadable_artifacts_are_skipped_and_counted(frozen, monkeypatch):
    path = Path(frozen.conn.execute("SELECT a.path FROM agentic_artifacts a JOIN agentic_runs r ON r.run_key=a.run_key "
                                    "WHERE r.posting_id=43 AND a.kind='evaluation'").fetchone()[0])
    path.write_bytes(path.read_bytes() + b' ')
    monkeypatch.setattr(baseline, '_utcnow', lambda: '2030-01-01T00:00:00+00:00')
    b = baseline.freeze_baseline(frozen.ro, frozen.config)
    assert len(b.case_ids) == 2 and b.summary['skipped'] == {'artifact_invalid': 1}
    frozen.conn.execute("INSERT INTO agentic_runs(run_key,posting_id,status) VALUES(?,?,?)", ('a' * 64, 99, 'new'))
    frozen.conn.commit()
    with pytest.raises(AgenticError) as err:                 # same content at the same fixed second: same baseline id
        baseline.freeze_baseline(frozen.ro, frozen.config)
    assert _code(err) == 'baseline_exists'
    assert [p.name for p in (users.user_dir() / 'baselines').iterdir()] == [b.baseline_id]   # no .staging-* left
    monkeypatch.setattr(baseline, '_utcnow', lambda: '2030-01-01T00:00:01+00:00')
    other = baseline.freeze_baseline(frozen.ro, frozen.config)
    assert other.summary['skipped'] == {'artifact_invalid': 1, 'no_evaluation': 1}


def test_a_case_with_a_blank_ad_hash_is_skipped_and_never_grouped_under_content(frozen):
    row = frozen.conn.execute("SELECT a.path, a.run_key FROM agentic_artifacts a JOIN agentic_runs r ON r.run_key=a.run_key "
                              "WHERE r.posting_id=43 AND a.kind='snapshot'").fetchone()
    path = Path(row[0])
    snapshot = json.loads(path.read_text())
    snapshot['run_key']['ad_hash'] = ''
    raw = json.dumps(snapshot, ensure_ascii=False, separators=(',', ':')).encode()
    path.write_bytes(raw)
    import hashlib
    frozen.conn.execute("UPDATE agentic_artifacts SET sha256=? WHERE run_key=? AND kind='snapshot'",
                        (hashlib.sha256(raw).hexdigest(), row[1]))
    frozen.conn.commit()
    b = baseline.freeze_baseline(frozen.ro, frozen.config)
    assert b.summary['skipped'] == {'artifact_invalid': 1} and b.summary['cases'] == 2
    _, cases = baseline.load_baseline(b.baseline_id)
    assert [c.posting_id for c in cases] == [42, 44]
    assert all(key != 'content:' and re.fullmatch(r'content:[0-9a-f]{64}', next(k for k in c.group_keys if k.startswith('content:')))
               for c in cases for key in c.group_keys)


def test_selection_by_posting_ids_and_limit(frozen):
    b = baseline.freeze_baseline(frozen.ro, frozen.config, posting_ids=[44, 42, 77])
    assert b.summary['skipped'] == {'no_run': 1} and [c.split('-')[1] for c in b.case_ids] == ['42', '44']
    newest = baseline.freeze_baseline(frozen.ro, frozen.config, limit=2)
    assert len(newest.case_ids) == 2 and all(c.split('-')[1] in ('43', '44') for c in newest.case_ids)


@pytest.mark.parametrize('limit', [0, 1001, True, '5'])
def test_limit_is_validated(frozen, limit):
    with pytest.raises(AgenticError) as err:
        baseline.freeze_baseline(frozen.ro, frozen.config, limit=limit)
    assert _code(err) == 'invalid_limit'


@pytest.mark.parametrize('ids', [[0], [True], ['4'], (42,), list(range(1, 1002))])
def test_posting_ids_are_validated(frozen, ids):
    with pytest.raises(AgenticError) as err:
        baseline.freeze_baseline(frozen.ro, frozen.config, posting_ids=ids)
    assert _code(err) == 'invalid_limit'


def test_git_commit_is_unknown_outside_a_checkout(tmp_path):
    assert baseline._git_commit(tmp_path) == 'unknown'


def test_git_commit_reads_the_checkout_head():
    assert re.fullmatch(r'[0-9a-f]{40}', baseline._git_commit(ROOT))


def test_utcnow_is_iso_seconds_in_utc():
    assert re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\+00:00|Z)', baseline._utcnow())


# --------------------------------------------------------------------------- owner labels

def _first_case(b):
    return min(b.case_ids)


def _tree_bytes(folder):
    return {str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob('*'))
            if p.is_file() and p.name not in ('labels.jsonl', 'labels.lock')}


def test_label_requires_the_owner_actor(frozen):
    b = baseline.freeze_baseline(frozen.ro, frozen.config)
    cid = _first_case(b)
    for actor in ('agent', 'person', '', None):
        with pytest.raises(AgenticError, match='owner_required'):
            label_case(b.baseline_id, cid, actor=actor, suitable=True)
    assert read_labels(b.baseline_id) == []


def test_label_is_private_append_only_and_latest_wins(frozen):
    b = baseline.freeze_baseline(frozen.ro, frozen.config)
    bid, cid = b.baseline_id, _first_case(b)
    folder = users.user_dir() / 'baselines' / bid
    before = _tree_bytes(folder)
    first = label_case(bid, cid, actor='owner', suitable=False, note='first')
    second = label_case(bid, cid, actor='owner', suitable=True, relevance=3, exclusion_violation=False)
    assert read_labels(bid) == [first, second] and latest_labels(read_labels(bid))[cid] == second
    assert stat.S_IMODE((folder / 'labels.jsonl').stat().st_mode) == 0o600
    assert stat.S_IMODE((folder / 'labels.lock').stat().st_mode) == 0o600
    assert len((folder / 'labels.jsonl').read_bytes().splitlines()) == 2
    assert _tree_bytes(folder) == before                      # baseline.json and every case file are untouched
    assert baseline.load_baseline(bid)[0].content_sha256 == b.content_sha256


def test_write_label_appends_a_prebuilt_owner_label_and_refuses_other_actors(frozen, monkeypatch):   # decision 13
    b = baseline.freeze_baseline(frozen.ro, frozen.config)
    bid, cid = b.baseline_id, _first_case(b)
    write_label(bid, OwnerLabel(case_id=cid, actor='owner', suitable=True, labelled_at='2026-10-21T00:00:00Z'))
    assert read_labels(bid)[0].suitable is True
    with pytest.raises(AgenticError, match='unknown_case'):
        write_label(bid, OwnerLabel(case_id='c-nope', actor='owner', suitable=True, labelled_at='t'))
    with pytest.raises(ValidationError):
        OwnerLabel(case_id=cid, actor='person', suitable=True, labelled_at='t')
    forged = OwnerLabel.model_construct(case_id=cid, actor='agent', suitable=True, labelled_at='t', tags=(), note='')
    with pytest.raises(AgenticError, match='owner_required'):
        write_label(bid, forged)
    assert len(read_labels(bid)) == 1
    # a failed write leaves the file as it was and releases the lock
    path = users.user_dir() / 'baselines' / bid / 'labels.jsonl'
    kept = path.read_bytes()

    def failing(target, data):
        raise OSError('disk full')

    with monkeypatch.context() as patch:
        patch.setattr(baseline, 'safe_write_bytes', failing)
        with pytest.raises(OSError):
            write_label(bid, OwnerLabel(case_id=cid, actor='owner', note='x', suitable=False, labelled_at='t'))
    assert path.read_bytes() == kept
    fd = os.open(path.parent / 'labels.lock', os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)         # raises BlockingIOError if the lock leaked
    finally:
        os.close(fd)


def test_a_malformed_label_line_is_an_error_not_a_skip(frozen):
    b = baseline.freeze_baseline(frozen.ro, frozen.config)
    bid, cid = b.baseline_id, _first_case(b)
    label_case(bid, cid, actor='owner', suitable=True)
    path = users.user_dir() / 'baselines' / bid / 'labels.jsonl'
    good = path.read_bytes()
    for bad in (b'{not json\n', b'[]\n', b'\n', b'\xff\n',
                json.dumps({'case_id': cid, 'actor': 'agent', 'suitable': True, 'labelled_at': 't'}).encode() + b'\n',
                json.dumps({'case_id': cid, 'actor': 'owner', 'relevance': 9, 'labelled_at': 't'}).encode() + b'\n',
                json.dumps({'case_id': cid, 'actor': 'owner', 'tags': ['nope'], 'labelled_at': 't'}).encode() + b'\n'):
        path.write_bytes(good + bad)
        with pytest.raises(AgenticError, match='labels_invalid'):
            read_labels(bid)
        with pytest.raises(AgenticError, match='labels_invalid'):     # a corrupt file is never extended
            label_case(bid, cid, actor='owner', suitable=False)
        assert path.read_bytes() == good + bad
    path.write_bytes(good + b'{not json')                              # no trailing newline
    with pytest.raises(AgenticError, match='labels_invalid'):
        read_labels(bid)


def test_bad_labels_are_refused(frozen):
    b = baseline.freeze_baseline(frozen.ro, frozen.config)
    bid, cid = b.baseline_id, _first_case(b)
    cases = [({'relevance': 4}, 'invalid_label'), ({'relevance': -1}, 'invalid_label'),
             ({'relevance': True}, 'invalid_label'), ({'suitable': 'yes'}, 'invalid_label'),
             ({}, 'empty_label'), ({'note': 'only a note'}, 'empty_label'),
             ({'tags': ('not_a_tag',)}, 'invalid_tag'), ({'tags': ('stretch', 'x'), 'relevance': 9}, 'invalid_tag'),
             ({'note': 'x' * 2001, 'suitable': True}, 'invalid_label')]
    for kwargs, code in cases:
        with pytest.raises(AgenticError) as err:
            label_case(bid, cid, actor='owner', **kwargs)
        assert _code(err) == code, kwargs
    with pytest.raises(AgenticError) as err:                   # the actor is checked before anything else
        label_case(bid, cid, actor='agent', tags=('not_a_tag',))
    assert _code(err) == 'owner_required'
    with pytest.raises(AgenticError) as err:
        label_case(bid, cid, actor='owner')
    assert _code(err) == 'empty_label'
    assert read_labels(bid) == []
    assert not (users.user_dir() / 'baselines' / bid / 'labels.jsonl').exists()
    ok = label_case(bid, cid, actor='owner', relevance=0, note='x' * 2000)      # the limits themselves are fine
    assert ok.relevance == 0 and len(ok.note) == 2000
    ok = label_case(bid, cid, actor='owner', tags=['stretch', 'stretch'])
    assert ok.tags == ('stretch',)


def test_unknown_case_and_unknown_baseline_are_refused(frozen):
    b = baseline.freeze_baseline(frozen.ro, frozen.config)
    bid = b.baseline_id
    for case_id in ('c-nope', '', '../baseline', '../cases/' + _first_case(b), _first_case(b) + '/..'):
        with pytest.raises(AgenticError) as err:
            label_case(bid, case_id, actor='owner', suitable=True)
        assert _code(err) == 'unknown_case', case_id
    ghost = 'bl-20260101T000000Z-0123abcd'
    with pytest.raises(AgenticError) as err:
        label_case(ghost, _first_case(b), actor='owner', suitable=True)
    assert _code(err) == 'baseline_not_found'
    with pytest.raises(AgenticError) as err:
        read_labels(ghost)
    assert _code(err) == 'baseline_not_found'
    assert read_labels(bid) == []


def test_labelling_validates_the_baseline_id_before_any_path_is_joined(frozen, monkeypatch):
    b = baseline.freeze_baseline(frozen.ro, frozen.config)
    cid = _first_case(b)
    label = OwnerLabel(case_id=cid, actor='owner', suitable=True, labelled_at='t')
    touched = []
    real = os.open
    with monkeypatch.context() as patch:
        patch.setattr(os, 'open', lambda path, *a, **k: touched.append(path) or real(path, *a, **k))
        _refuse_bad_ids(b, cid, label)
    assert touched == []
    users.create_user_dirs('friend')
    with users.use('friend'):                                    # another person's baseline is not visible
        with pytest.raises(AgenticError) as err:
            label_case(b.baseline_id, cid, actor='owner', suitable=True)
        assert _code(err) == 'baseline_not_found'
        with pytest.raises(AgenticError) as err:
            read_labels(b.baseline_id)
        assert _code(err) == 'baseline_not_found'
    assert read_labels(b.baseline_id) == []


def _refuse_bad_ids(b, cid, label):
    for bad in ('../x', '../../etc', 'bl-20260101T000000Z-zzzzzzzz', '', b.baseline_id + '\n', None, 7,
                b.baseline_id + '/../' + b.baseline_id):
        for call in (lambda i: write_label(i, label), read_labels,
                     lambda i: label_case(i, cid, actor='owner', suitable=True)):
            with pytest.raises(AgenticError) as err:
                call(bad)
            assert _code(err) == 'invalid_baseline_id', bad


def test_owner_tags_extend_the_deterministic_tags(frozen):
    b = baseline.freeze_baseline(frozen.ro, frozen.config)
    bid = b.baseline_id
    _, cases = baseline.load_baseline(bid)
    case = next(c for c in cases if 'misleading_title' not in c.tags)
    label_case(bid, case.case_id, actor='owner', tags=('misleading_title',))
    assert 'misleading_title' in effective_tags(case, latest_labels(read_labels(bid)))
    assert 'misleading_title' not in case.tags                   # the frozen case itself is unchanged


def test_effective_tags_are_a_union_in_contract_order_and_latest_labels_is_pure():
    case = synthetic_case('c-1', route='archive', reason='policy_excluded')
    assert case.tags == ()
    case = case.model_copy(update={'tags': ('explicit_exclusion', 'previously_rejected')})

    def lab(cid, **kw):
        return OwnerLabel(case_id=cid, actor='owner', labelled_at='t', **kw)

    first = lab('c-1', tags=('stretch', 'previously_rejected'))
    second = lab('c-1', suitable=True)
    other = lab('c-2', tags=('unknown_facts',))
    labels = [first, other, second]
    snapshot = list(labels)
    latest = latest_labels(iter(labels))
    assert latest == {'c-1': second, 'c-2': other} and labels == snapshot and latest_labels([]) == {}
    assert effective_tags(case, {'c-1': first}) == ('previously_rejected', 'stretch', 'explicit_exclusion')
    assert effective_tags(case, latest) == ('previously_rejected', 'explicit_exclusion')
    assert effective_tags(case, {}) == ('previously_rejected', 'explicit_exclusion')
    assert effective_tags(case, {'c-2': other}) == ('previously_rejected', 'explicit_exclusion')


def test_owner_label_model_limits():
    for kwargs in ({'relevance': 4}, {'relevance': -1}, {'note': 'x' * 2001}, {'tags': ('nope',)}, {'actor': 'agent'}):
        base = {'case_id': 'c-1', 'actor': 'owner', 'labelled_at': 't'}
        with pytest.raises(ValidationError):
            OwnerLabel(**{**base, **kwargs})
    label = OwnerLabel(case_id='c-1', actor='owner', labelled_at='t')
    assert (label.suitable, label.relevance, label.exclusion_violation, label.note, label.tags) == \
        (None, None, None, '', ())


def test_label_writer_is_not_reachable_from_agent_surfaces():
    for name in ('api', 'chat', 'profile_api', 'mcp_server', 'deepagents_runtime', 'api_store'):
        text = (ROOT / 'pipeline' / 'agentic' / f'{name}.py').read_text()
        assert 'pipeline.agentic.baseline' not in text and 'from .baseline' not in text
        assert 'label_case' not in text and 'write_label' not in text


# --------------------------------------------------------------------------- the one live gate call (decision policy, Task 6)

def test_decide_frozen_goes_through_gate_current(frozen, monkeypatch):                    # contract decision 2
    from pipeline.agentic import service
    from pipeline.agentic.contracts import AgenticEvaluation, RunKey
    from pipeline.agentic.gate import decide
    from pipeline.agentic.runtime import validate_model_payload
    from jobwatch.candidate.evidence import bundle_from_contents
    from jobwatch.candidate.policy import default_policy
    b = baseline.freeze_baseline(frozen.ro, frozen.config)
    _, (case, *_) = baseline.load_baseline(b.baseline_id)
    seen = []
    real = service.gate_current
    monkeypatch.setattr(service, 'gate_current', lambda *a, **k: seen.append((a, k)) or real(*a, **k))
    with baseline.pinned_profile(b.baseline_id):
        got = baseline.decide_frozen(case.snapshot, case.evaluation, commute_km=None)
        # the call as it was written before the switch: the gate itself, with no decision policy
        before = decide(validate_model_payload(AgenticEvaluation, case.evaluation), ad_text=case.snapshot['full_ad'],
                        title=case.snapshot['posting']['title'], policy=default_policy(), captured_complete=True,
                        expected_run_key=RunKey.model_validate(case.snapshot['run_key']),
                        evidence_bundle=bundle_from_contents({n: t.encode() for n, t in case.snapshot['contents'].items()}),
                        commute_km=None).model_dump(mode='json')
    assert len(seen) == 1
    _, kwargs = seen[0]
    assert kwargs['decision_policy'] is None and kwargs['posting'] == {
        'title': case.snapshot['posting']['title'], 'company': case.snapshot['posting']['company'],
        'location': case.snapshot['posting']['location']}
    assert kwargs['commute_km'] is None and kwargs['ad_text'] == case.snapshot['full_ad']
    assert got == before and 'error' not in got


def test_freeze_stores_the_confirmed_policy_even_for_retained_legacy_configuration(frozen, monkeypatch):
    from jobwatch.candidate.policy import policy_for
    from pipeline.agentic import service
    settings = frozen.config.settings['pipeline']['agentic']
    settings['decision_policy'] = 'legacy'
    seen = []
    real = service.gate_current
    monkeypatch.setattr(service, 'gate_current', lambda *a, **k: seen.append(k['decision_policy']) or real(*a, **k))
    b = baseline.freeze_baseline(frozen.ro, frozen.config)
    expected = policy_for(users.current(), approved=baseline.frozen_approved(b.baseline_id))
    assert expected is not None
    assert baseline.frozen_decision_policy(b.baseline_id) == expected.model_dump(mode='json')
    assert b.decision_policy_sha256
    assert seen and all(p == expected for p in seen)                                  # the decisions are gate_current's
    _, cases = baseline.load_baseline(b.baseline_id)
    with baseline.pinned_profile(b.baseline_id):
        for case in cases:
            assert case.decision == baseline.decide_frozen(case.snapshot, case.evaluation, commute_km=case.commute_km,
                                                           decision_policy=expected)


def test_profile_mode_freeze_measures_the_commute_from_the_policy_home(world, monkeypatch):    # contract decision 2
    from pipeline.agentic.location import commute_km_for
    from tests.candidate.policy_fixtures import fact, policy_of
    conn, config, bundle, add = world
    add(42)
    conn.execute("UPDATE postings SET location='Carlton VIC' WHERE id=42")
    conn.commit()
    agentic_batch_run([42], config, conn, evidence_bundle=bundle,
                      llm=LLM(transport=SyntheticGateway(bundle), keys=['synthetic']), operation='evaluate')
    conn.commit()
    import sqlite3
    ro = sqlite3.connect(f'file:{config.db_path}?mode=ro', uri=True)
    ro.row_factory = sqlite3.Row
    config.settings['pipeline']['agentic']['decision_policy'] = 'profile'
    homed = policy_of(fact('location', 'I live in Box Hill, VIC'))
    homeless = policy_of(fact('experience', 'x'))
    monkeypatch.setattr(baseline, '_active_decision_policy', lambda cfg, approved: homed)
    b = baseline.freeze_baseline(ro, config)
    _, (case,) = baseline.load_baseline(b.baseline_id)
    expected = commute_km_for('Box Hill, VIC', 'Carlton VIC')
    assert case.snapshot['posting']['location'] == 'Carlton VIC'
    assert type(expected) is int and case.commute_km == float(expected)
    monkeypatch.setattr(baseline, '_active_decision_policy', lambda cfg, approved: homeless)
    other = baseline.freeze_baseline(ro, config)
    _, (case,) = baseline.load_baseline(other.baseline_id)
    assert case.commute_km is None
    ro.close()
