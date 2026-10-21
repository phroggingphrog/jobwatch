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


def test_confirm_scope_prints_then_confirms(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    users.create_user_dirs("friend")
    with users.use("friend"):
        (apaths.profile_dir() / "profile.yaml").write_text("candidate:\n  name: Synthetic\n")
        (apaths.profile_dir() / "master_resume.md").write_text("# Synthetic\n\nAccounts Assistant, 2021\n")
    assert cli.main(["--user", "friend", "profile", "adopt"]) == 0
    capsys.readouterr()
    assert cli.main(["--user", "friend", "profile", "confirm-scope"]) == 0
    out = capsys.readouterr().out
    digest = next(l.split(": ")[1] for l in out.splitlines() if l.startswith("scope_digest"))
    assert "base_version: 1" in out and intake.discovery_scope("friend") is None
    assert cli.main(["--user", "friend", "profile", "confirm-scope", "--base-version", "1", "--scope-digest", "0" * 64]) == 1
    assert "scope_changed" in capsys.readouterr().err
    assert cli.main(["--user", "friend", "profile", "confirm-scope", "--base-version", "1", "--scope-digest", digest]) == 0
    assert "version 2" in capsys.readouterr().out and intake.discovery_scope("friend") is not None


def test_run_and_read_skip_a_person_without_a_confirmed_profile(tmp_path, monkeypatch, capsys):
    from jobwatch import pipeline
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    for name in ("friend", "mate"):
        users.create_user_dirs(name)
    ran = []
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: ran.append(users.current()) or {"run_id": 1, "requests": 0, "pruned": 0,
                        "alerts": {"board": 0}, "collectors": []})
    from conftest import confirm_discovery
    from jobwatch.config import load_config
    confirm_discovery(load_config(), "mate")
    assert cli.main(["--user", "all", "run", "--tier", "fast", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "skipped friend: no_confirmed_profile" in out and "mate" not in out.split("skipped")[1:][0:1].__str__()
    assert ran == ["mate"]
