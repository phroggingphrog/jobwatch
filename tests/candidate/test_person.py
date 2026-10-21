from __future__ import annotations

import logging
from pathlib import Path

import pytest

from jobwatch.candidate import person


@pytest.fixture
def profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("JOBWATCH_PROFILE_DIR", str(tmp_path))
    return tmp_path


@pytest.mark.parametrize(("raw", "expected"), [("48", 48.0), ('"48"', 48.0), ("32.5", 32.5),
                                               ('"abc"', None), ("0", None), ("-5", None), ("true", None), ('""', None)])
def test_hours_limit_accepts_numbers_and_numeric_strings(profile, raw, expected):
    (profile / "profile.yaml").write_text(f"candidate:\n  work_rights:\n    hours_limit_per_fortnight: {raw}\n")
    assert person.hours_limit_per_fortnight() == expected


def test_a_yaml_syntax_error_is_neutral_but_logged(profile, caplog):
    (profile / "profile.yaml").write_text("candidate: [unclosed\n  work_rights: {\n")
    with caplog.at_level(logging.WARNING):
        assert person.hours_limit_per_fortnight() is None
    assert any("profile.yaml" in r.getMessage() for r in caplog.records)


def test_a_missing_profile_is_silently_neutral(profile, caplog):
    with caplog.at_level(logging.WARNING):
        assert person.hours_limit_per_fortnight() is None and person.excluded_families() == ()
    assert not caplog.records
