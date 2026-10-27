import json
import stat

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jobwatch import cli, users
from jobwatch.web import auth_routes


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("JOBWATCH_INVITE_CODE", raising=False)
    (tmp_path / "home").mkdir()
    return tmp_path


def _client():
    app = FastAPI()
    auth_routes.install_auth(app)
    return TestClient(app, base_url="http://127.0.0.1:8960")


def test_login_links_to_signup_even_when_closed(home, monkeypatch):
    monkeypatch.setenv("JOBWATCH_SESSION_SECRET", "s")
    monkeypatch.setenv("JOBWATCH_INVITE_CODE", "")
    r = _client().get("/login")
    assert 'href="/signup"' in r.text and "Create account" in r.text


def test_signup_closed_explains_and_hides_code_field(home, monkeypatch):
    monkeypatch.setenv("JOBWATCH_SESSION_SECRET", "s")
    monkeypatch.setenv("JOBWATCH_INVITE_CODE", "")
    t = _client().get("/signup").text
    assert "closed" in t and "invite code from the person who runs this Jobwatch" in t
    assert "jobwatch user invite" in t and 'name="invite"' not in t


def test_signup_open_shows_code_field(home, monkeypatch):
    monkeypatch.setenv("JOBWATCH_SESSION_SECRET", "s")
    monkeypatch.setenv("JOBWATCH_INVITE_CODE", "abc")
    assert 'name="invite"' in _client().get("/signup").text


def test_set_password_round_trip(home, monkeypatch, capsys):
    pws = iter(["longenough1", "longenough1"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(pws))
    assert cli.main(["user", "set-password", "newbie"]) == 0
    assert auth_routes.check_password("newbie", "longenough1")
    assert not auth_routes.check_password("newbie", "wrong")
    assert (home / "data" / "users" / "newbie" / "jobwatch.db").exists()
    out = capsys.readouterr()
    assert "longenough1" not in out.out + out.err
    assert cli.main(["user", "list"]) == 0
    assert "newbie" in capsys.readouterr().out.split()


@pytest.mark.parametrize("name", ["A", "1abc", "bad name", "../x"])
def test_set_password_rejects_bad_names(home, monkeypatch, name):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": pytest.fail("asked for a password"))
    assert cli.main(["user", "set-password", name]) == 2
    assert not (home / "data" / "users.json").exists()


def test_set_password_short_or_mismatch_changes_nothing(home, monkeypatch):
    for seq in (["short"], ["longenough1", "different11"]):
        it = iter(seq)
        monkeypatch.setattr("getpass.getpass", lambda prompt="", it=it: next(it))
        assert cli.main(["user", "set-password", "newbie"]) == 2
    assert not (home / "data" / "users.json").exists()


def test_invite_writes_replaces_backs_up_and_hides_code(home, monkeypatch, capsys):
    env = home / "agent.env"
    env.write_text("A=1\nJOBWATCH_INVITE_CODE=old\nB=2\n")
    monkeypatch.setenv("JOBWATCH_SETTINGS", str(env))
    assert cli.main(["user", "invite"]) == 0
    lines = env.read_text().splitlines()
    codes = [l for l in lines if l.startswith("JOBWATCH_INVITE_CODE=")]
    assert len(codes) == 1 and codes[0] != "JOBWATCH_INVITE_CODE=old" and "A=1" in lines and "B=2" in lines
    code = codes[0].split("=", 1)[1]
    out = capsys.readouterr().out
    assert code not in out and str(env) in out and "restart jobwatch-native-web to apply" in out
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    backups = list((home / "home" / "backups" / "jobwatch").glob("agent.env.*"))
    assert len(backups) == 1 and "JOBWATCH_INVITE_CODE=old" in backups[0].read_text()

    assert cli.main(["user", "invite", "--show"]) == 0
    new = [l for l in env.read_text().splitlines() if l.startswith("JOBWATCH_INVITE_CODE=")][0].split("=", 1)[1]
    assert new in capsys.readouterr().out


def test_invite_keeps_newest_three_backups(home, monkeypatch):
    env = home / "agent.env"
    env.write_text("A=1\n")
    monkeypatch.setenv("JOBWATCH_SETTINGS", str(env))
    d = home / "home" / "backups" / "jobwatch"
    d.mkdir(parents=True)
    for i in range(4):
        (d / f"agent.env.2020010{i}-000000").write_text("x")
    cli.main(["user", "invite"])
    names = sorted(p.name for p in d.glob("agent.env.*"))
    assert len(names) == 3 and "agent.env.20200100-000000" not in names


def test_invite_needs_settings_env(home, monkeypatch, capsys):
    monkeypatch.delenv("JOBWATCH_SETTINGS", raising=False)
    assert cli.main(["user", "invite"]) == 2
