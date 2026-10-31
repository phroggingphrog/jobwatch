"""Interstate postings never reach a paid read: the pickers re-check the confirmed region, and a pending digest
still applies the location rule (2026-10-31: 16 NSW/QLD postings were assessed for a VIC-only profile)."""
import sqlite3
from types import SimpleNamespace

from pipeline.agentic import service


def vic_policy():
    return SimpleNamespace(profile_version=1, policy_hash='a' * 64, focus=(), exclusions=(),
        home=None, regions=('VIC',), remote_ok=True)


def db():
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE postings(id INTEGER PRIMARY KEY, location TEXT, state TEXT, remote INTEGER)')
    conn.executemany('INSERT INTO postings VALUES(?,?,?,?)', [
        (1, 'Melbourne, VIC', 'VIC', 0),
        (2, 'Casula Sydney, New South Wales', 'NSW', 0),
        (3, 'Brisbane QLD', 'QLD', 0),
        (4, 'Sydney NSW', 'NSW', 1),
        (5, '', None, 0)])
    return conn


def test_picker_drops_interstate_and_keeps_home_remote_and_unknown(monkeypatch):
    monkeypatch.setattr('jobwatch.candidate.intake.current_version', lambda who: {'v': 1})
    monkeypatch.setattr(service, 'policy_for', lambda who, approved=None: vic_policy())
    assert service._in_profile_region(db(), [1, 2, 3, 4, 5, 99]) == [1, 4, 5]


def test_picker_without_confirmed_profile_changes_nothing(monkeypatch):
    monkeypatch.setattr('jobwatch.candidate.intake.current_version', lambda who: None)
    assert service._in_profile_region(db(), [2, 3]) == [2, 3]


def test_pending_digest_still_rejects_interstate():
    from jobwatch.filters import Rules
    from jobwatch.models import Posting
    rules = Rules.__new__(Rules)
    rules.profile_policy, rules.digest_pending = vic_policy(), True
    sydney = Posting(source='t', source_id='1', url='u', title='Nurse', company='c', location='Sydney NSW', state='NSW')
    melbourne = Posting(source='t', source_id='2', url='u', title='Nurse', company='c', location='Melbourne VIC', state='VIC')
    assert rules.evaluate(sydney).matched is False
    assert rules.evaluate(melbourne).matched is True
