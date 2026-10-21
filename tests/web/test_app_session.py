"""The SPA (static/app/app.js) in a real browser: an ended session is an error, never a silent success."""
import socket
import threading
import time

import pytest

from jobwatch import db as dbm
from jobwatch.config import DEFAULT_CONFIG_DIR, DEFAULT_SETTINGS, Config, _merge
from jobwatch.web.app import create_app


@pytest.fixture
def board(tmp_path, monkeypatch):
    uvicorn = pytest.importorskip("uvicorn")
    data = tmp_path / "data"
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(data))
    monkeypatch.delenv("JOBWATCH_DB", raising=False)
    settings = _merge(DEFAULT_SETTINGS, {"db_path": str(data / "jobwatch.db")})
    config = Config(config_dir=DEFAULT_CONFIG_DIR, settings=settings, rules={}, searches={}, feeds={}, employers=[])
    dbm.connect(config.db_path).close()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(config), host="127.0.0.1", port=port, log_level="error",
                                           lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(5)


@pytest.mark.parametrize("reply", [
    {"status": 401, "content_type": "application/json", "body": '{"error": "sign in required"}'},     # server now
    {"status": 200, "content_type": "text/html", "body": "<html><form action=/login></form></html>"},  # a followed 303
])
def test_an_ended_session_shows_an_error_not_an_empty_page(board, reply):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.route("**/api/inbox*", lambda route: route.fulfill(**reply))
            page.goto(board + "/app#inbox")
            alert = page.locator("#view [role=alert]")
            alert.wait_for(timeout=10_000)
            assert "session ended" in alert.inner_text()
        finally:
            browser.close()
