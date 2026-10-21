import json

from jobwatch import cli, users
from jobwatch.apply import paths as apaths
from jobwatch.candidate import intake


def test_profile_adopt_creates_version_one_for_the_current_person(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    users.create_user_dirs("friend")
    with users.use("friend"):
        (apaths.profile_dir() / "profile.yaml").write_text("candidate:\n  name: Synthetic\n")
        (apaths.profile_dir() / "master_resume.md").write_text("# Synthetic\n\nAccounts Assistant, 2021\n")
    assert cli.main(["--user", "friend", "profile", "adopt"]) == 0
    assert capsys.readouterr().out.strip() == "adopted profile as version 1"
    with users.use("friend"):
        assert json.loads((users.user_dir() / "profile-versions" / "1" / "approved.json").read_text())["adopted_from_files"] is True
        assert (apaths.profile_dir() / "profile.yaml").read_text() == "candidate:\n  name: Synthetic\n"


def test_profile_adopt_refusal_exits_non_zero_with_the_code(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    users.create_user_dirs("friend")
    assert cli.main(["--user", "friend", "profile", "adopt"]) == 1
    cap = capsys.readouterr()
    assert "nothing_to_adopt" in cap.err and cap.out == ""
    with users.use("friend"):
        assert intake.current_version("friend") is None
