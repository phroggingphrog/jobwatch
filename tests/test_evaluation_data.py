"""Invented frozen records only; no real person or model calls."""
import json
import pytest
from pipeline.agentic import baseline, eval_data
from pipeline.agentic.contracts import AgenticError
from tests.baseline_support import world, frozen  # noqa:F401


def test_write_once_grouped_split_and_selected_loading(frozen, monkeypatch):
    record = eval_data.freeze_cases(frozen.ro, frozen.config)
    split = eval_data.create_split(record.baseline_id, seed=41)
    assert split == eval_data.create_split(record.baseline_id, seed=41)
    assert split['development'] and split['holdout']
    assert not set(split['development']) & set(split['holdout'])
    _, cases = baseline.load_baseline(record.baseline_id)
    parts = {c.case_id: 'development' if c.case_id in split['development'] else 'holdout' for c in cases}
    assert len({parts[c.case_id] for c in cases if c.posting_id in (42,43)}) == 1
    with pytest.raises(AgenticError, match='split_conflict'):
        eval_data.create_split(record.baseline_id, seed=42)
    original = baseline._read_verified
    def guard(path, sha):
        assert path.stem not in split['holdout'], 'development read holdout case'
        return original(path, sha)
    monkeypatch.setattr(baseline, '_read_verified', guard)
    record2, selected = eval_data.load_partition(record.baseline_id, 'development')
    assert {c.case_id for c in selected} == set(split['development'])
    assert record2 == record
    with pytest.raises(AgenticError, match='holdout_approval_required'):
        eval_data.load_partition(record.baseline_id, 'holdout')


def test_context_and_profile_tampering_refused(frozen):
    record = eval_data.freeze_cases(frozen.ro, frozen.config)
    eval_data.create_split(record.baseline_id)
    context = eval_data.load_inputs(record.baseline_id)
    assert context['runtime'] and context['discovery']['relevance'] == 'shadow'
    folder = baseline._baseline_dir(record.baseline_id)
    (folder/'evaluation_inputs.json').write_text('{}')
    with pytest.raises(AgenticError, match='baseline_corrupt'):
        eval_data.load_inputs(record.baseline_id)


def test_holdout_access_is_audited_before_cases(frozen):
    record = eval_data.freeze_cases(frozen.ro, frozen.config)
    split = eval_data.create_split(record.baseline_id)
    eval_data.load_partition(record.baseline_id, 'holdout', allow_holdout=True)
    audit = baseline._baseline_dir(record.baseline_id)/'evaluation'/'holdout_access.jsonl'
    rows = [json.loads(x) for x in audit.read_text().splitlines()]
    assert rows[-1]['operation']=='replay' and rows[-1]['split_hash']==split['split_hash']
    assert rows[-1]['code_hash'] and rows[-1]['data_hash']


def test_single_group_has_explicit_split_unavailable(frozen):
    record = eval_data.freeze_cases(frozen.ro,frozen.config,posting_ids=[42,43])
    with pytest.raises(AgenticError, match='insufficient_groups'):
        eval_data.create_split(record.baseline_id)


def test_detected_cross_split_leakage_refused_even_with_valid_checksum(frozen):
    from jobwatch.candidate.contracts import digest
    record=eval_data.freeze_cases(frozen.ro,frozen.config)
    split=eval_data.create_split(record.baseline_id)
    # Move only one member of the related-employer group, re-sealing the metadata.
    _,cases=baseline.load_baseline(record.baseline_id)
    related=[c.case_id for c in cases if c.posting_id in (42,43)]
    source='development' if related[0] in split['development'] else 'holdout'
    destination='holdout' if source=='development' else 'development'
    split[source].remove(related[0]);split[destination].append(related[0])
    split['split_hash']=digest({k:v for k,v in split.items() if k!='split_hash'})
    path=baseline._baseline_dir(record.baseline_id)/'evaluation'/'split.json'
    path.write_text(json.dumps(split))
    with pytest.raises(AgenticError,match='split_leakage'):
        eval_data.load_split(record.baseline_id)


def test_private_directory_symlink_refused(frozen,tmp_path):
    record=eval_data.freeze_cases(frozen.ro,frozen.config)
    folder=baseline._baseline_dir(record.baseline_id)
    outside=tmp_path/'outside';outside.mkdir()
    (folder/'evaluation').symlink_to(outside,target_is_directory=True)
    with pytest.raises(AgenticError,match='unsafe_evaluation_path'):
        eval_data.create_split(record.baseline_id)
    assert not list(outside.iterdir())


def test_config_drift_rejects_staging_before_publication(frozen,monkeypatch):
    original=eval_data.capture_inputs
    def changed(conn,config,cases,approved,**kwargs):
        config.settings['pipeline']['agentic']['job_token_ceiling']+=1
        return original(conn,config,cases,approved,**kwargs)
    monkeypatch.setattr(eval_data,'capture_inputs',changed)
    with pytest.raises(AgenticError,match='snapshot_changed'):
        eval_data.freeze_cases(frozen.ro,frozen.config)
    assert baseline.list_baselines()==[]
    assert not list(baseline._baselines_root().glob('.staging-*'))
    assert not frozen.ro.in_transaction
