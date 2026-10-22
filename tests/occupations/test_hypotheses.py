import json
import stat

import pytest
from pydantic import ValidationError

from jobwatch import users
from jobwatch.candidate.policy import ExclusionRule
from jobwatch.occupations import DiscoveryError
from jobwatch.occupations import hypotheses, loaders
from jobwatch.occupations.embeddings import VectorStore
from jobwatch.occupations.hypotheses import FieldHypothesis, cached_doc_keys, cached_hypotheses, field_hypotheses, select
from .fixtures import approved_llm, hash_transport, fact, make_config, make_policy, toy_reference, write_approved

LEDGER = fact('experience', 'Reconciled supplier ledgers prepared journals', fid='f1')


@pytest.fixture
def person(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setattr(loaders, 'load_reference_records', lambda **k: toy_reference())
    monkeypatch.setattr(hypotheses, 'reference_store', lambda model=None: VectorStore(tmp_path / 'reference', model or 'synthetic'))
    monkeypatch.setattr(hypotheses, 'policy_for', lambda p: make_policy(profile_version=hypotheses.intake.current_version(p)['version']) if hypotheses.intake.current_version(p) else None)
    monkeypatch.setattr(hypotheses, 'load_config', make_config)
    return 'synthetic'


def compute(person, calls=None, **kwargs):
    return field_hypotheses(person, llm=approved_llm(hash_transport(calls)), config=make_config(), policy=kwargs.pop('policy', make_policy()), **kwargs)


def test_related_fields_rank_above_unrelated(person):
    write_approved(person, [LEDGER, fact('skill', 'bookkeeping ledgers journals', fid='f2')])
    titles = [h.title for h in compute(person)]
    assert titles[0] in {'Accountant', 'Bookkeeper', 'Accountants and Auditors'}
    assert titles.index('Barista') > min(i for i, t in enumerate(titles) if t in {'Accountant', 'Accountants and Auditors'})


def test_only_approved_usable_facts_support_hypotheses(person):
    write_approved(person, [LEDGER, fact('availability', 'weekdays', fid='f3'), fact('skill', 'guess', basis='unknown', fid='f4')])
    got = compute(person)
    assert all(h.is_qualification_proof is False and set(h.supporting_facts) <= {'f1'} for h in got)
    with pytest.raises(ValidationError):
        FieldHypothesis(scheme='onet', code='x', title='x', similarity=.1, supporting_facts=(), rationale='x', is_qualification_proof=True)


def test_explicit_exclusions_remove_titles_and_families(person):
    write_approved(person, [LEDGER])
    policy = make_policy(exclusions=(ExclusionRule(rule_id='r', kind='title_term', value='bookkeeper'),))
    assert 'Bookkeeper' not in [h.title for h in compute(person, policy=policy)]
    policy = make_policy(exclusions=(ExclusionRule(rule_id='r', kind='family', value='accounting'),))
    assert 'Accountant' not in [h.title for h in compute(person, policy=policy)]


def test_career_focus_prioritises_focus(person):
    write_approved(person, [LEDGER])
    focus = make_policy(strategy='career_focus', focus=('software developer programming',))
    assert compute(person, policy=focus, limit=3)[0].title == 'Software Developer'
    assert compute(person, limit=3)[0].title != 'Software Developer'


def test_corresponding_records_collapse(person):
    write_approved(person, [LEDGER])
    got = compute(person)
    matches = [h for h in got if h.title in {'Accountant', 'Accountants and Auditors'}]
    assert len(matches) == 1 and len(matches[0].related) == 1


def test_profile_and_dataset_changes_invalidate_cache(person, monkeypatch):
    write_approved(person, [LEDGER])
    calls = []
    first = compute(person, calls)
    count = len(calls)
    assert compute(person, calls) == first and len(calls) == count
    assert cached_hypotheses(person) == first
    assert set(cached_doc_keys(person)) == {h.id for h in first}
    write_approved(person, [LEDGER, fact('skill', 'payroll')], version=2)
    assert cached_hypotheses(person) is None and cached_doc_keys(person) == {}
    compute(person, calls, policy=make_policy(profile_version=2))
    assert len(calls) > count
    reference = toy_reference().model_copy(update={'versions': {'anzsco2022': 'toy-2'}})
    monkeypatch.setattr(loaders, 'load_reference_records', lambda **k: reference)
    assert cached_hypotheses(person) is None


def test_policy_changes_invalidate_cache(person, monkeypatch):
    write_approved(person, [LEDGER])
    compute(person)
    monkeypatch.setattr(hypotheses, 'policy_for', lambda p: make_policy(focus=('new',)))
    assert cached_hypotheses(person) is None


def test_no_usable_facts_and_missing_reference_are_errors(person, monkeypatch):
    write_approved(person, [fact('skill', 'guess', basis='unknown')])
    with pytest.raises(DiscoveryError, match='no_profile_facts'):
        compute(person)
    write_approved(person, [LEDGER], version=2)
    monkeypatch.setattr(loaders, 'load_reference_records', lambda **k: toy_reference().model_copy(update={'records': ()}))
    with pytest.raises(DiscoveryError, match='reference_unavailable'):
        compute(person, policy=make_policy(profile_version=2))


def test_person_b_never_reads_person_a_cache_and_files_private(person):
    write_approved(person, [LEDGER])
    compute(person)
    assert cached_hypotheses('other') is None
    folder = users.user_dir(person) / 'discovery'
    assert all(stat.S_IMODE(p.stat().st_mode) == (0o700 if p.is_dir() else 0o600) for p in [folder, *folder.rglob('*')])


def test_cache_corruption_is_refused(person):
    write_approved(person, [LEDGER])
    compute(person)
    path = next((users.user_dir(person) / 'discovery' / 'hypotheses').glob('[0-9a-f]' * 64 + '.json'))
    data = json.loads(path.read_text())
    data['hypotheses'][0]['supporting_facts'] = ['invented']
    path.write_text(json.dumps(data))
    assert cached_hypotheses(person) is None


def test_select_strategy_is_pure_deduplicated_and_bounded():
    assert select('employment_first', ['a', 'b', 'c'], ['x'], 2) == ['a', 'b']
    assert select('career_focus', ['a', 'b', 'c'], ['x', 'a', 'z'], 3) == ['x', 'a', 'b']
    assert select('balanced', ['a', 'b', 'c'], ['x', 'a'], 4) == ['a', 'x', 'b', 'c']
    assert select('career_focus', ['a', 'b'], [], 2) == ['a', 'b']


def test_reference_index_budget_failure_resumes_completed_batches(person, monkeypatch, tmp_path):
    from jobwatch.occupations.loaders import OccupationRecord
    reference = toy_reference()
    records = tuple(OccupationRecord(scheme='onet', code=str(i), title=f'Synthetic role {i}',
        text='bookkeeping ledgers ' + ('journals ' * 25) + str(i), dataset_version='many') for i in range(65))
    reference = reference.model_copy(update={'records': records, 'correspondences': (), 'records_hash': 'many'})
    monkeypatch.setattr(loaders, 'load_reference_records', lambda **k: reference)
    write_approved(person, [LEDGER])
    # Reservation is conservatively byte-counted. One batch fits, the second cannot.
    from pipeline.agentic.runtime import _json_bytes
    ceiling = _json_bytes({'model': 'openrouter/qwen/qwen3-embedding-8b', 'input': [r.text for r in records[:32]]}) + 100
    config = make_config({'pipeline': {'agentic': {'embedding_model': 'openrouter/qwen/qwen3-embedding-8b'},
                                     'discovery': {'embedding_token_ceiling': ceiling}}})
    # Settled usage plus the next conservative reservation exceeds the ceiling.
    from pipeline.agentic import execution
    calls = []
    with execution.use(execution.Execution('partial', token_ceiling=ceiling)):
        with pytest.raises(DiscoveryError, match='reference_index_incomplete'):
            field_hypotheses(person, llm=approved_llm(hash_transport(calls)), config=config, policy=make_policy())
    assert 0 < len(list((tmp_path / 'reference').rglob('*.f32'))) < 65
    count = len(calls)
    result = compute(person, calls)
    assert result and len(calls) > count
    assert len(list((tmp_path / 'reference').rglob('*.f32'))) == 65


def test_same_version_content_replacement_invalidates_cache(person):
    write_approved(person, [LEDGER])
    compute(person)
    write_approved(person, [fact('skill', 'software programming', fid='new')])
    assert cached_hypotheses(person) is None


def test_mismatched_profile_policy_is_refused_before_calls(person):
    write_approved(person, [LEDGER])
    calls = []
    with pytest.raises(DiscoveryError, match='no_policy'):
        compute(person, calls, policy=make_policy(profile_version=2))
    assert calls == []


def test_supplied_connection_is_used_and_remains_open(person, tmp_path):
    from jobwatch import db
    from jobwatch.occupations.embeddings import discovery_tokens_since
    write_approved(person, [LEDGER])
    connection = db.connect(tmp_path / 'configured.sqlite')
    try:
        got = field_hypotheses(person, llm=approved_llm(hash_transport()), config=make_config(),
                               policy=make_policy(), conn=connection)
        assert got and discovery_tokens_since(connection, 0) > 0
        assert connection.execute('SELECT 1').fetchone()[0] == 1
        assert not users.db_path(person).exists()
    finally:
        connection.close()


def test_invalid_deadline_is_rejected_before_calls(person):
    write_approved(person, [LEDGER])
    calls = []
    with pytest.raises(DiscoveryError, match='invalid_configuration'):
        field_hypotheses(person, llm=approved_llm(hash_transport(calls)), config=make_config(), policy=make_policy(), seconds=0)
    assert calls == []


def test_new_person_database_is_private(person):
    write_approved(person, [LEDGER])
    compute(person)
    assert stat.S_IMODE(users.db_path(person).stat().st_mode) == 0o600


def test_cached_fields_use_explicit_runtime_config_after_refresh(person, monkeypatch):
    """An injected API/service config can differ from the configuration on disk."""
    write_approved(person, [LEDGER])
    config = make_config()
    monkeypatch.setattr(hypotheses, 'load_config', lambda: make_config({'pipeline': {'agentic': {}}}))
    calls = []
    got = field_hypotheses(person, llm=approved_llm(hash_transport(calls)), config=config, policy=make_policy())
    count = len(calls)
    assert cached_hypotheses(person, config=config) == got
    assert set(cached_doc_keys(person, config=config)) == {h.id for h in got}
    assert cached_hypotheses(person) is None
    assert cached_doc_keys(person) == {}
    assert len(calls) == count
