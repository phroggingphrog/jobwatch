"""Clients project current understanding without preparing or replacing authority."""
import sqlite3
from types import SimpleNamespace

from jobwatch import users
from jobwatch.candidate.presentation import current_understanding


def test_current_projection_keeps_policy_separate_and_never_reuses_another_person(monkeypatch):
    from pipeline.agentic import candidate_digest
    constraints = {'regions': ['VIC']}
    policy = SimpleNamespace(profile_version=4, model_dump=lambda **kw: constraints)
    monkeypatch.setattr('jobwatch.candidate.policy.policy_for', lambda person: policy)
    findings = {'strengths': [], 'gaps': [], 'target_paths': [], 'uncertainties': [],
                'advisory_suggestions': ['Consider a different region'], 'model_interpretation': {},
                'approved_constraints': constraints, 'model_provenance': {'callbacks': {'status': 'prior_only'}},
                'manifest': {'private_binding': 'not_a_client_projection'}}
    digest = SimpleNamespace(identity='synthetic-current', model_dump=lambda **kw: findings)
    monkeypatch.setattr(candidate_digest, 'current_policy_digest',
                        lambda conn, selected: digest if users.current() == 'fixture-a' else None)
    monkeypatch.setattr(candidate_digest, 'ensure_digest', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('read prepared a digest')))
    with sqlite3.connect(':memory:') as conn:
        conn.execute('CREATE TABLE candidate_digests(person TEXT)')
        conn.execute("INSERT INTO candidate_digests VALUES ('fixture-a')")
        conn.commit()
        writes = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE, sqlite3.SQLITE_CREATE_TABLE}
        conn.set_authorizer(lambda action, *args: sqlite3.SQLITE_DENY if action in writes else sqlite3.SQLITE_OK)
        with users.use('fixture-a'):
            first = current_understanding(conn)
        with users.use('fixture-b'):
            second = current_understanding(conn)
        assert first['status'] == 'current' and first['profile_version'] == 4
        assert first['approved_constraints'] == constraints
        assert first['candidate']['advisory_suggestions'] == ['Consider a different region']
        assert first['models']['callbacks']['status'] == 'prior_only'
        assert 'manifest' not in first and 'manifest' not in first['candidate']
        assert second['status'] == 'missing' and second['candidate'] is None
        monkeypatch.setattr(candidate_digest, 'current_policy_digest', lambda *a: None)
        with users.use('fixture-a'):
            stale = current_understanding(conn)
        assert stale['status'] == 'stale' and stale['candidate'] is None
        assert stale['approved_constraints'] == constraints
