import pytest
import hashlib
from types import SimpleNamespace

import yaml

from jobwatch import onboarding, users


@pytest.fixture(autouse=True)
def _owner_folder_profile(monkeypatch):
    monkeypatch.setenv("JOBWATCH_PROFILE_DIR", "")   # the owner's own data folder, not the conftest-pinned example profile

CV = """# Sam Friend
sam@example.com

## Summary
Graduate nurse who completed clinical placements in a busy emergency ward.

## Education
### Bachelor of Nursing
*Example University, 2023*
"""
LETTER = "Dear team,\nI like people and I like ward work.\nSam"
DIPLOMA = "Bachelor of Nursing, Example University, 2023\nCourses: Anatomy 101; Pharmacology 200\nCertificate: Provide First Aid"


class FakeLLM:
    def chat(self, model, messages, json_mode=True, **kw):
        if "extract a job-search profile" in messages[0]["content"]:
            return SimpleNamespace(data={"name": "Sam Friend", "level": "graduate", "target_titles": ["graduate nurse"],
                                         "questions": ["Work rights?"]})
        return SimpleNamespace(data={"certifications": ["Bachelor of Nursing, Example University, 2023", "Pharmacology 200",
                                                         "Made up course"],
                                     "projects": []})


def snap(root):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()
            and "users" not in p.relative_to(root).parts}










def test_legacy_string_work_rights_reads_as_unknown(tmp_path, monkeypatch):
    from jobwatch.candidate import person
    monkeypatch.setattr(person, '_yaml', lambda name: {'candidate': {'work_rights': 'Australian citizen'}})
    assert person.work_rights() == {"statement": "Australian citizen"}
    assert person.hours_limit_per_fortnight() is None


def test_build_profile_writes_structured_work_rights(tmp_path, monkeypatch):
    monkeypatch.setattr(onboarding, "write_profile_file", lambda user, name, text: None)
    class L:
        def chat(self, *a, **k):
            return SimpleNamespace(data={"name": "Sam", "work_rights": "Australian citizen"})
    profile, _ = onboarding.build_profile("cv", "sam", L())
    assert profile["candidate"]["work_rights"] == {"statement": "Australian citizen"}
    class E:
        def chat(self, *a, **k): return SimpleNamespace(data={"name": "Sam"})
    assert onboarding.build_profile("cv", "sam", E())[0]["candidate"]["work_rights"] == {}


def test_onboarding_missing_level_stays_unknown(monkeypatch):
    monkeypatch.setattr(onboarding, 'write_profile_file', lambda *args: None)
    class L:
        def chat(self, *args, **kwargs):
            return SimpleNamespace(data={'name': 'Sam'})
    profile, _ = onboarding.build_profile('cv', 'owner', L())
    assert profile['level'] == ''
    assert profile['avoid_titles'] == []
