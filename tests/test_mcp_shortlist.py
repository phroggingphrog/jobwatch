"""MCP recommendations are a projection of the canonical, frozen shortlist."""
import pytest
from tests.baseline_support import world, frozen
from jobwatch import users
from pipeline.agentic import shortlist, chatgpt_connector as cc, selection

@pytest.fixture
def connector(frozen, monkeypatch):
    monkeypatch.setattr(cc, 'load_config', lambda: frozen.config)
    return frozen

def test_exact_membership_order_explanations_and_no_activity_fallback(connector):
    expected = shortlist.build_shortlist(connector.conn, connector.config)
    actual = cc.overview(users.current())
    assert actual['status'] == 'ok'
    assert [j['posting_id'] for j in actual['jobs']] == [e.posting_id for e in expected]
    for row, entry in zip(actual['jobs'], expected):
        assert row['label'] == entry.label and row['rank_reason'] == entry.rank_reason
        assert row['evidence'] == list(entry.evidence)
        assert row['can_prepare'] is True
    assert cc.application_overview(users.current())['jobs'] == []
    assert cc.recommended_detail(users.current(), 999)['found'] is False
    assert cc.recommended_detail(users.current(), expected[0].posting_id)['shortlist_entry']['entry_id'] == expected[0].entry_id

def test_changed_inputs_hide_every_old_match(connector):
    shortlist.build_shortlist(connector.conn, connector.config)
    connector.conn.execute("UPDATE postings SET title='Changed job' WHERE id=42")
    connector.conn.commit()
    actual = cc.overview(users.current())
    assert actual['status'] == 'stale' and actual['jobs'] == []
    assert cc.recommended_detail(users.current(), 42)['found'] is False

def test_not_built_is_not_an_activity_list(connector):
    actual = cc.overview(users.current())
    assert actual['status'] == 'not_built' and actual['jobs'] == []

def test_prepare_requires_consent_current_identity_and_is_idempotent(connector):
    entries = shortlist.build_shortlist(connector.conn, connector.config)
    entry = entries[0]
    args = dict(expected_entry_id=entry.entry_id, expected_run_key=entry.run_key, request_id='synthetic-request', confirmed=True)
    with pytest.raises(Exception):
        cc.prepare_selected(users.current(), entry.posting_id, **dict(args, confirmed=False))
    with pytest.raises(selection.SelectionError):
        cc.prepare_selected(users.current(), entry.posting_id, **dict(args, expected_entry_id='changed'))
    first = cc.prepare_selected(users.current(), entry.posting_id, **args)
    second = cc.prepare_selected(users.current(), entry.posting_id, **args)
    assert first == second and first['authorises'] == 'preparation_only'
    assert first['state'] == 'queued'
    with pytest.raises(selection.SelectionError):
        cc.prepare_selected(users.current(), entry.posting_id, **dict(args, expected_run_key='changed'))
    connector.conn.execute("UPDATE selection_requests SET state='failed' WHERE id=?", (first['selection_id'],))
    connector.conn.commit()
    failed = cc.prepare_selected(users.current(), entry.posting_id, **args)
    assert failed['selection_id'] == first['selection_id'] and failed['state'] == 'failed'
    assert 'failed' in failed['answer'] and 'queued' not in failed['answer']

def test_holds_remain_visible_but_cannot_prepare_and_exclusions_never_appear(connector, monkeypatch):
    from types import SimpleNamespace
    real = cc.preference_service.current_runs
    def current(*args, **kwargs):
        identity, bundle, policy, runs = real(*args, **kwargs)
        changed = []
        for run in runs:
            values = {k: getattr(run, k) for k in ('posting_id','key','evaluation','posting','approved')}
            values['decision'] = run.decision.model_copy(update={
                'route': 'hold' if run.posting_id == 42 else 'archive',
                'reason': 'insufficient_evidence' if run.posting_id == 42 else 'hard_gate'})
            changed.append(SimpleNamespace(**values))
        return identity, bundle, policy, changed
    monkeypatch.setattr(cc.preference_service, 'current_runs', current)
    actual = cc.overview(users.current(), refresh=True)
    assert [j['posting_id'] for j in actual['jobs']] == [42]
    held = actual['jobs'][0]
    assert held['label'] == 'needs_clarification' and held['can_prepare'] is False
    with pytest.raises(selection.SelectionError):
        cc.prepare_selected(users.current(),42,expected_entry_id=held['entry_id'],expected_run_key=held['run_key'],request_id='held-request',confirmed=True)


def test_connector_loads_each_person_rules_before_opening_their_database(tmp_path, monkeypatch):
    from jobwatch.config import load_config
    monkeypatch.setattr(users, 'base_dir', lambda: tmp_path)
    shared = tmp_path / 'install-config'
    shared.mkdir()
    (shared / 'rules.yaml').write_text('policy: owner-only\n')
    (shared / 'searches.yaml').write_text('search: owner-search\n')
    guest = tmp_path / 'users' / 'guest' / 'config'
    guest.mkdir(parents=True)
    (guest / 'rules.yaml').write_text('policy: guest-only\n')
    (guest / 'searches.yaml').write_text('search: guest-search\n')
    monkeypatch.setenv('JOBWATCH_CONFIG_DIR', str(shared))
    seen = []
    class ConfigChecked(Exception):
        pass
    def inspect_config():
        config = load_config()
        seen.append((users.current(), config.rules['policy'], config.searches['search']))
        raise ConfigChecked
    monkeypatch.setattr(cc, 'load_config', inspect_config)
    operations = [
        lambda person: cc.overview(person),
        lambda person: cc.application_overview(person),
        lambda person: cc.detail(person, 1),
        lambda person: cc.prepare_selected(person, 1, expected_entry_id='entry',
            expected_run_key='key', request_id='request', confirmed=True),
    ]
    for operation in operations:
        for person in ('guest', 'owner'):
            with pytest.raises(ConfigChecked):
                operation(person)
    assert seen == [('guest', 'guest-only', 'guest-search'),
                    ('owner', 'owner-only', 'owner-search')] * len(operations)
    assert users.current() == users.DEFAULT_USER


def test_missing_person_database_returns_not_built_without_creating_it(tmp_path, monkeypatch):
    from types import SimpleNamespace
    missing = tmp_path / 'missing-person.db'
    monkeypatch.setattr(cc, 'load_config', lambda: SimpleNamespace(db_path=missing))
    result = cc.overview('guest', refresh=True)
    assert result['status'] == 'not_built' and result['jobs'] == []
    assert not missing.exists()
