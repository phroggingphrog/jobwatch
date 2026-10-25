from fastapi import FastAPI

from jobwatch import users
from jobwatch.web import app as web_app
from jobwatch.web.auth_routes import install_auth
from pipeline.agentic.tui_data import WebBackend


def test_tui_backend_signs_in_as_its_person_when_web_auth_is_on(tmp_path, monkeypatch):
    # Live web has a session secret, so an unsigned TUI call got 401 and every view failed.
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JOBWATCH_SESSION_SECRET", "s3cret")

    def fake_app(_cfg):
        app = FastAPI()
        install_auth(app)

        @app.get("/api/sources")
        def sources():
            return {"person": users.current(), "health": []}
        return app

    monkeypatch.setattr(web_app, "create_app", fake_app)
    backend = WebBackend("friend")
    backend._config = object()
    assert backend._get("/api/sources")["person"] == "friend"
