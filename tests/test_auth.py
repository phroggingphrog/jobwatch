import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jobwatch import users
from jobwatch.web.auth_routes import COOKIE, install_auth, set_password


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JOBWATCH_SESSION_SECRET", "s3cret")
    monkeypatch.setenv("JOBWATCH_INVITE_CODE", "letmein")
    app = FastAPI()
    install_auth(app)

    @app.get("/")
    def home():
        return {"user": users.current()}

    set_password("friend", "longenough1")
    return TestClient(app, base_url="http://127.0.0.1:8960")


def test_auth(client, tmp_path):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert client.get("/", headers={"hx-request": "true"}).status_code == 401
    assert client.get("/login").status_code == 200

    r = client.post("/login", data={"username": "friend", "password": "wrong"})
    assert r.status_code == 401 and "do not match" in r.text and COOKIE not in client.cookies

    r = client.post("/login", data={"username": "friend", "password": "longenough1"}, follow_redirects=False)
    assert r.status_code == 303 and COOKIE in client.cookies
    assert client.get("/").json() == {"user": "friend"}
    assert oct((tmp_path / "users.json").stat().st_mode & 0o777) == "0o600"

    client.cookies.clear()
    r = client.post("/signup", data={"username": "newbie", "password": "longenough1", "invite": "nope"})
    assert r.status_code == 403 and "invite" in r.text and not (tmp_path / "users" / "newbie").exists()
    r = client.post("/signup", data={"username": "newbie", "password": "longenough1", "invite": "letmein"},
                    follow_redirects=False)
    assert r.status_code == 303 and (tmp_path / "users" / "newbie" / "profile").is_dir()
    assert client.get("/").json() == {"user": "newbie"}
