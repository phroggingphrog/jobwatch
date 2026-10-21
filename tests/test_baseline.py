"""Synthetic tests for the frozen-baseline models, gate version, grouping and tags."""
import json
import os
import random
import re
import stat
from pathlib import Path

import pytest
import yaml

from jobwatch import adtext, users
from jobwatch.apply import paths as apaths
from jobwatch.candidate import intake
from jobwatch.llm import LLM
from pipeline.agentic import baseline
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
            adtext.save_text(conn, ident, text + ' Full-time position, 38 hours per week. ', 'synthetic-full')
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
    assert (by[44].decision['route'], by[44].decision['reason']) == ('archive', 'score_below_threshold')
    assert by[44].stored['run_status'] == 'archived' and by[42].stored['run_reason'] == 'evaluation_complete'
    assert by[42].evaluation['global_score'] == 4.3 and by[44].evaluation['global_score'] == 2.7
    assert 'previously_rejected' in by[44].tags and all(c.tags == baseline.tag_case(c) for c in cases)
    assert by[42].usage['charged_tokens'] > 0 and by[42].usage['actual_tokens'] is None and by[42].usage['latency_seconds'] > 0
    assert by[42].group_id == by[43].group_id != by[44].group_id        # 'Synthetic Alpha' and 'Synthetic Alpha Pty Ltd'
    assert by[42].snapshot['full_ad'] and by[42].candidate and by[42].structural_inputs['reference_utf8']
    assert b.summary['cases'] == 3 and b.summary['routes'] == {'draft': 2, 'archive': 1, 'hold': 0, 'error': 0}
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


def test_decision_follows_the_frozen_profile_not_later_edits(world):
    ro = _evaluated(world, 42, long_hours=True)
    config = world[1]
    _profile_yaml(hours=48)
    b = baseline.freeze_baseline(ro, config)
    _, (case,) = baseline.load_baseline(b.baseline_id)
    assert case.stored['run_reason'] == 'evaluation_complete'
    assert (case.decision['route'], case.decision['reason']) == ('archive', 'hard_gate')
    assert b.summary['evidence_mismatch'] == 1                           # profile.yaml is in the evidence bundle
    _profile_yaml(hours=None)
    assert baseline.decide_frozen(case.snapshot, case.evaluation, commute_km=None)['route'] == 'draft'    # live profile
    with baseline.pinned_profile(b.baseline_id):
        assert baseline.decide_frozen(case.snapshot, case.evaluation, commute_km=None) == case.decision   # frozen profile


def test_commute_is_measured_from_the_frozen_home(world):
    ro = _evaluated(world, 42)
    config = world[1]
    _profile_yaml(location='Brunswick, VIC')
    b = baseline.freeze_baseline(ro, config)
    _, (case,) = baseline.load_baseline(b.baseline_id)
    assert case.commute_km == 5.0
    _profile_yaml(location='Geelong, VIC')
    assert km_from_home('Melbourne VIC') != 5
    with baseline.pinned_profile(b.baseline_id):
        assert km_from_home('Melbourne VIC') == 5


def test_the_pinned_profile_version_is_frozen_with_the_baseline(frozen):      # contract decision 1
    b = baseline.freeze_baseline(frozen.ro, frozen.config)
    approved = baseline.frozen_approved(b.baseline_id)
    assert approved == intake.current_version(users.current()) and b.decision_policy_sha256 is None
    assert baseline.frozen_decision_policy(b.baseline_id) is None
    assert not (_dir(b.baseline_id) / 'decision_policy.json').exists()
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
