import json

import pytest

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
    import json as _json
    from conftest import confirm_discovery
    from jobwatch.config import load_config
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    users.create_user_dirs("friend")
    confirm_discovery(load_config(), "friend")
    path = users.user_dir("friend") / "profile-versions" / "1" / "approved.json"
    approved = _json.loads(path.read_text())
    del approved["scope"], approved["scope_digest"]                  # a version approved before scopes existed
    path.write_text(_json.dumps(approved))
    assert cli.main(["--user", "friend", "profile", "confirm-scope"]) == 0
    out = capsys.readouterr().out
    digest = next(l.split(": ")[1] for l in out.splitlines() if l.startswith("scope_digest"))
    assert "base_version: 1" in out and intake.discovery_scope("friend") is None
    assert cli.main(["--user", "friend", "profile", "confirm-scope", "--base-version", "1", "--scope-digest", "0" * 64]) == 1
    assert "scope_changed" in capsys.readouterr().err
    assert cli.main(["--user", "friend", "profile", "confirm-scope", "--base-version", "1", "--scope-digest", digest]) == 0
    assert "version 2" in capsys.readouterr().out and intake.discovery_scope("friend") is not None


def test_confirm_scope_of_an_adopted_profile_is_refused_as_incomplete(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    users.create_user_dirs("friend")
    with users.use("friend"):
        (apaths.profile_dir() / "profile.yaml").write_text("candidate:\n  name: Synthetic\n")
        (apaths.profile_dir() / "master_resume.md").write_text("# Synthetic\n\nAccounts Assistant, 2021\n")
    assert cli.main(["--user", "friend", "profile", "adopt"]) == 0
    capsys.readouterr()
    assert cli.main(["--user", "friend", "profile", "confirm-scope"]) == 0
    digest = next(l.split(": ")[1] for l in capsys.readouterr().out.splitlines() if l.startswith("scope_digest"))
    assert cli.main(["--user", "friend", "profile", "confirm-scope", "--base-version", "1", "--scope-digest", digest]) == 1
    assert "profile_incomplete" in capsys.readouterr().err and intake.discovery_scope("friend") is None


def _two_people(tmp_path, monkeypatch):
    from conftest import confirm_discovery
    from jobwatch.config import load_config
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    for name in ("friend", "mate"):
        users.create_user_dirs(name)
    confirm_discovery(load_config(), "mate")                 # mate is confirmed; friend has nothing


def test_run_skips_a_person_without_a_confirmed_profile(tmp_path, monkeypatch, capsys):
    from jobwatch import pipeline
    _two_people(tmp_path, monkeypatch)
    ran = []
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: ran.append(users.current()) or {"run_id": 1, "requests": 0, "pruned": 0,
                        "alerts": {"board": 0}, "collectors": []})
    assert cli.main(["--user", "all", "run", "--tier", "fast", "--dry-run"]) == 0
    skipped = [l for l in capsys.readouterr().out.splitlines() if "no_confirmed_profile" in l]
    assert sorted(skipped) == [f"run: skipped {who}: no_confirmed_profile (confirm the profile and its scope first)"
                               for who in ("friend", "owner")]
    assert ran == ["mate"]


def test_read_skips_a_person_without_a_confirmed_profile(tmp_path, monkeypatch, capsys):
    from pipeline.agentic import service
    from jobwatch import expiry
    _two_people(tmp_path, monkeypatch)
    ran = []
    monkeypatch.setattr(service, "after_collect", lambda conn, cfg, **k: ran.append((users.current(), k["max_seconds"])) or {})
    monkeypatch.setattr(expiry, "sweep", lambda conn, **k: {})
    assert cli.main(["--user", "all", "read"]) == 0
    assert sorted(l for l in capsys.readouterr().out.splitlines() if "skipped" in l) == [
        f"read: skipped {who}: no_confirmed_profile (confirm the profile and its scope first)" for who in ("friend", "owner")]
    assert [who for who, _ in ran] == ["mate"]


def test_user_all_splits_the_unit_budget_over_the_people_who_run(tmp_path, monkeypatch, capsys):
    from conftest import confirm_discovery
    from jobwatch import execution_mode, pipeline
    from jobwatch.config import load_config
    _two_people(tmp_path, monkeypatch)
    confirm_discovery(load_config(), "friend")                # now both are confirmed
    seen = []
    monkeypatch.setattr(pipeline, "tier_collectors", lambda *a, **k: [])
    monkeypatch.setattr(execution_mode, "effective_mode", lambda cfg: "reader")
    monkeypatch.setattr(pipeline.reader if hasattr(pipeline, "reader") else __import__("jobwatch.reader", fromlist=["x"]),
                        "after_collect", lambda conn, cfg, **k: seen.append(k["max_seconds"]) or {})
    assert cli.main(["--user", "all", "run", "--tier", "fast"]) == 0
    assert len(seen) == 2 and all(abs(x - pipeline.UNIT_BUDGET_S / 2) < 30 for x in seen)
    assert sum(seen) <= pipeline.UNIT_BUDGET_S                 # inside the unit's budget, whoever runs


def test_manual_assessment_commands_are_gated(tmp_path, monkeypatch, capsys):
    from jobwatch import reader, recall
    from pipeline import graph
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    users.create_user_dirs("friend")
    for mod, name in ((reader, "review_pending"), (reader, "sort_not_target"), (recall, "triage_new"), (graph, "run_once")):
        monkeypatch.setattr(mod, name, lambda *a, **k: pytest.fail("assessed without a confirmed profile"))
    for argv in (["review"], ["review", "recall"], ["review", "sort"], ["pipeline", "run"], ["pipeline", "sort"]):
        assert cli.main(["--user", "friend", *argv]) == 0
        assert "skipped friend: no_confirmed_profile" in capsys.readouterr().out
    from pipeline.agentic import cli as agentic_cli, service
    config = type("C", (), {})()
    monkeypatch.setattr(agentic_cli, "enabled", lambda cfg: True)
    monkeypatch.setattr(agentic_cli, "agentic_batch_run", lambda *a, **k: pytest.fail("assessed without a confirmed profile"))
    with users.use("friend"):
        assert agentic_cli.main(["--db", str(tmp_path / "x.db")]) == 0
    assert "no_confirmed_profile" in capsys.readouterr().out
