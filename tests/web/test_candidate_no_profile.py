import logging

from fastapi.testclient import TestClient

from jobwatch.config import load_config
from jobwatch.web.app import create_app


def test_candidate_page_without_profile_logs_no_error(tmp_path, monkeypatch, caplog):
    # Fresh start: no profile yet is normal, so it must not log a traceback on every load.
    monkeypatch.setenv("JOBWATCH_SETTINGS", "/dev/null")
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JOBWATCH_DB", str(tmp_path / "jobwatch.db"))
    monkeypatch.delenv("JOBWATCH_SESSION_SECRET", raising=False)
    client = TestClient(create_app(load_config()), base_url="http://localhost",
                        headers={"host": "localhost", "origin": "http://localhost"})
    with caplog.at_level(logging.WARNING):
        assert client.get("/candidate").status_code == 200
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
