import pytest

from jobwatch import users
from jobwatch.candidate.contracts import CandidateError


class Bundle:
    bundle_hash = 'b' * 64


def test_interview_default_bundle_uses_approved_evidence(monkeypatch):
    from jobwatch.interview import prep
    expected = Bundle()
    calls = []
    monkeypatch.setattr(users, 'current', lambda: 'synthetic-user')
    monkeypatch.setattr(prep.approved, 'evidence', lambda person: calls.append(person) or expected)
    assert prep._approved_bundle() is expected
    assert calls == ['synthetic-user']


def test_followup_default_bundle_uses_approved_evidence(monkeypatch):
    from jobwatch.followup import drafts
    expected = Bundle()
    calls = []
    monkeypatch.setattr(users, 'current', lambda: 'synthetic-user')
    monkeypatch.setattr(drafts.approved, 'evidence', lambda person: calls.append(person) or expected)
    assert drafts._approved_bundle() is expected
    assert calls == ['synthetic-user']


def test_candidate_insights_use_approved_evidence(monkeypatch):
    from pipeline.agentic import model_insights
    expected = Bundle()
    calls = []
    monkeypatch.setattr(users, 'current', lambda: 'synthetic-user')
    monkeypatch.setattr(model_insights.approved, 'evidence', lambda person: calls.append(person) or expected)
    monkeypatch.setattr(model_insights.service, 'load_inputs', lambda *args: ())
    monkeypatch.setattr(model_insights.service, '_config', lambda config: {})
    monkeypatch.setattr(model_insights.service, 'analyse_candidate', lambda *args: object())
    monkeypatch.setattr(model_insights.service, 'default_policy', lambda: object())
    monkeypatch.setattr('jobwatch.candidate.analysis.structural_summary', lambda result: {'ok': True})
    assert model_insights.candidate_paths(None) == {'ok': True}
    assert calls == ['synthetic-user']


def test_preference_current_runs_use_approved_evidence(monkeypatch):
    from jobwatch import preference_service
    expected = Bundle()
    calls = []
    monkeypatch.setattr(users, 'current', lambda: 'synthetic-user')
    monkeypatch.setattr(preference_service.approved_reader, 'evidence', lambda person: calls.append(person) or expected)
    monkeypatch.setattr(preference_service.service, 'load_inputs', lambda *args: ())
    monkeypatch.setattr(preference_service.service, 'analyse_candidate', lambda *args: object())
    monkeypatch.setattr(preference_service.service, '_config', lambda config: {})
    monkeypatch.setattr(preference_service.service, 'default_policy', lambda: object())
    monkeypatch.setattr(preference_service.service, 'verify_evidence_snapshot', lambda bundle: None)
    monkeypatch.setattr(preference_service, 'preference_context', lambda **kwargs: 'ctx')
    import sqlite3
    conn = sqlite3.connect(':memory:')
    assert preference_service.current_runs(conn, None)[1] is expected
    assert calls == ['synthetic-user']


def test_render_profile_reads_approved_settings_without_live_fallback(monkeypatch):
    from jobwatch.apply import render
    calls = []
    monkeypatch.setattr(users, 'current', lambda: 'synthetic-user')
    monkeypatch.setattr(render.approved, 'settings', lambda person, name: calls.append((person, name)) or {'candidate': {'headline': 'Synthetic'}})
    assert render._candidate() == {'headline': 'Synthetic'}
    assert calls == [('synthetic-user', 'profile.yaml')]


def test_render_profile_returns_empty_when_approved_settings_fail(monkeypatch):
    from jobwatch.apply import render
    monkeypatch.setattr(render.approved, 'settings', lambda *args: (_ for _ in ()).throw(CandidateError('no_profile_version')))
    assert render._candidate() == {}


def test_location_reads_approved_settings_without_live_fallback(monkeypatch):
    from pipeline.agentic import location
    calls = []
    monkeypatch.setattr(users, 'current', lambda: 'synthetic-user')
    monkeypatch.setattr(location.approved, 'settings', lambda person, name: calls.append((person, name)) or {'candidate': {'location': 'Brunswick, VIC'}})
    assert location._profile_home() == location.victorian_place('Brunswick, VIC')
    assert calls == [('synthetic-user', 'profile.yaml')]


def test_location_returns_unknown_when_approved_settings_fail(monkeypatch):
    from pipeline.agentic import location
    monkeypatch.setattr(location.approved, 'settings', lambda *args: (_ for _ in ()).throw(CandidateError('approved_restrictions_invalid')))
    assert location.home_place() == ''


def test_ordering_uses_approved_career_profile(monkeypatch):
    from pipeline.agentic import service
    from jobwatch.candidate import approved
    calls = []
    bundle = type('Evidence', (), {'contents': {'career_ops_profile.md': b'# Approved roles'}})()
    monkeypatch.setattr(users, 'current', lambda: 'synthetic-user')
    monkeypatch.setattr(approved, 'evidence', lambda person: calls.append(person) or bundle)
    monkeypatch.setattr(service, '_capture', lambda conn, pid: ('hash', 'ad text'))
    monkeypatch.setattr(service, 'rank_by_target', lambda conn, items, profile, config: calls.append(profile) or {1: 1.0})
    assert service._target_first(None, None, [1]) == [1]
    assert calls == ['synthetic-user', '# Approved roles']


def test_ordering_fails_before_paid_ranking_without_approved_bundle(monkeypatch):
    from pipeline.agentic import service
    from jobwatch.candidate import approved
    monkeypatch.setattr(users, 'current', lambda: 'synthetic-user')
    monkeypatch.setattr(approved, 'evidence', lambda person: (_ for _ in ()).throw(CandidateError('no_profile_version')))
    monkeypatch.setattr(service, '_capture', lambda conn, pid: ('hash', 'ad text'))
    monkeypatch.setattr(service, 'rank_by_target', lambda *args: pytest.fail('ranking must not run'))
    with pytest.raises(CandidateError, match='no_profile_version'):
        service._target_first(None, None, [1])
