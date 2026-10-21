from __future__ import annotations

import pytest
import yaml

from jobwatch import users
from jobwatch.apply import paths
from jobwatch.candidate import person


def _profile(folder, hours):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "profile.yaml").write_text(
        yaml.safe_dump({"candidate": {"work_rights": {"hours_limit_per_fortnight": hours}}}), encoding="utf-8")
    return folder


def test_pin_redirects_the_person_readers(tmp_path, monkeypatch):
    live = _profile(tmp_path / "live", 48)
    frozen = _profile(tmp_path / "frozen", 20)
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JOBWATCH_PROFILE_DIR", str(live))
    assert person.hours_limit_per_fortnight() == 48
    with paths.pin_profile_dir(frozen):
        assert paths.profile_dir() == frozen
        assert person.hours_limit_per_fortnight() == 20
    assert paths.profile_dir() == live
    assert person.hours_limit_per_fortnight() == 48


def test_pin_applies_to_a_non_default_person(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    users.create_user_dirs("friend")
    frozen = _profile(tmp_path / "frozen", 20)
    with users.use("friend"):
        own = paths.profile_dir()
        assert own == tmp_path / "users" / "friend" / "profile"
        with paths.pin_profile_dir(frozen):
            assert paths.profile_dir() == frozen
        assert paths.profile_dir() == own


def test_pinned_folder_is_read_only_to_code(tmp_path):
    frozen = _profile(tmp_path / "frozen", 20)
    with paths.pin_profile_dir(frozen):
        with pytest.raises(paths.ProfileWriteError):
            paths.safe_write_text(frozen / "x.txt", "y")


def test_pins_nest_and_restore(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path / "data"))
    unpinned = paths.profile_dir()
    outer = _profile(tmp_path / "a", 1)
    inner = _profile(tmp_path / "b", 2)
    with paths.pin_profile_dir(outer):
        assert paths.profile_dir() == outer
        with paths.pin_profile_dir(inner):
            assert paths.profile_dir() == inner
        assert paths.profile_dir() == outer
    assert paths.profile_dir() == unpinned


def test_pin_is_released_when_the_block_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path / "data"))
    unpinned = paths.profile_dir()
    with pytest.raises(RuntimeError):
        with paths.pin_profile_dir(_profile(tmp_path / "a", 1)):
            raise RuntimeError("boom")
    assert paths.profile_dir() == unpinned


@pytest.mark.parametrize("bad", ["relative/dir", "missing"])
def test_pin_needs_an_existing_absolute_directory(tmp_path, bad):
    target = str(tmp_path / "missing") if bad == "missing" else bad
    with pytest.raises(ValueError):
        with paths.pin_profile_dir(target):
            pass
