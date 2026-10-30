from __future__ import annotations

from pathlib import Path

import pytest

import json

from jobwatch.candidate import intake, person, projection
from jobwatch.candidate.contracts import CandidateError
from jobwatch import users


@pytest.fixture
def profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JOBWATCH_PROFILE_DIR", str(tmp_path / 'live'))
    root = intake._versions_root(users.current()) / '1'
    root.mkdir(parents=True)
    record = {'version': 1, 'facts': []}
    (root / 'approved.json').write_text(json.dumps(record))
    for name, text in projection.project(record).items():
        (root / name).write_text(text)
    return root


@pytest.mark.parametrize(("raw", "expected"), [("48", 48.0), ('"48"', 48.0), ("32.5", 32.5),
                                               ('"abc"', None), ("0", None), ("-5", None), ("true", None), ('""', None)])
def test_hours_limit_accepts_numbers_and_numeric_strings(profile, raw, expected):
    import yaml
    value = yaml.safe_load(raw)
    record = {'version': 1, 'facts': [{'section': 'work_rights', 'basis': 'evidence',
                                      'value': {'hours_limit_per_fortnight': value}}]}
    (profile / 'approved.json').write_text(json.dumps(record))
    for name, text in projection.project(record).items():
        (profile / name).write_text(text)
    assert person.hours_limit_per_fortnight() == expected


def test_a_yaml_syntax_error_blocks_approved_restrictions(profile):
    (profile / "profile.yaml").write_text("candidate: [unclosed\n  work_rights: {\n")
    with pytest.raises(CandidateError, match='approved_restrictions_invalid'):
        person.hours_limit_per_fortnight()


def test_a_missing_approved_profile_blocks_restrictions(profile):
    (profile / 'profile.yaml').unlink()
    with pytest.raises(CandidateError, match='approved_restrictions_missing'):
        person.hours_limit_per_fortnight()
