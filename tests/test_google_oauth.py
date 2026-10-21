import json
import stat
from urllib.parse import parse_qs, urlsplit

import pytest

from jobwatch import google_oauth as g
from jobwatch import users


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost/connect/google/callback")


def test_consent_url_scopes_no_send(env):
    q = parse_qs(urlsplit(g.build_consent_url("s")).query)
    scopes = q["scope"][0].split()
    assert "https://www.googleapis.com/auth/gmail.modify" in scopes
    assert "https://www.googleapis.com/auth/drive.file" in scopes
    assert not any("gmail.send" in s or s == "https://mail.google.com/" for s in scopes)
    assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"]


def test_missing_env_raises(monkeypatch):
    for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(g.GoogleNotConfigured, match="GOOGLE_CLIENT_ID"):
        g.build_consent_url("s")


def test_token_file_0600_with_mock(env, monkeypatch):
    class R:
        status_code = 200
        def json(self):
            return {"access_token": "a", "refresh_token": "r", "expires_in": 3600, "scope": "x"}
    monkeypatch.setattr(g.requests, "post", lambda *a, **k: R())
    with users.use("friend"):
        g.exchange_code("code")
        p = g.token_path()
        assert p.parent.name == "friend"
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert json.loads(p.read_text())["refresh_token"] == "r"


def test_state_tamper_rejected(env):
    with users.use("friend"):
        s = g.make_state()
    assert g.check_state(s) == "friend"
    body, sig = s.rsplit(".", 1)
    for bad in (body + ".0" + sig[1:], "x" + s, "junk", g.make_state("friend", now=1)):
        with pytest.raises(ValueError):
            g.check_state(bad)
