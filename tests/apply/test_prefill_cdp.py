import subprocess
import sys
import socket
import threading
import time
import json
import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
import yaml
import pytest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from playwright.sync_api import sync_playwright

def get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ("/WelcomeScreen", "/jobtools/apCustomAppMgr.WelcomeScreen") and 'redirect=1' in self.path:
            self.send_response(302)
            self.send_header("Location", "/redirected_form")
            self.end_headers()
            return
        if path in ("/WelcomeScreen", "/jobtools/apCustomAppMgr.WelcomeScreen", "/redirected_form"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
            <!DOCTYPE html>
            <html><body>
                <form id="theform" action="/submit" method="POST">
                    <input type="text" name="full_name" id="full_name" onfocus="document.getElementById('btn_submit').click();">
                    <input type="checkbox" name="consent" id="consent">
                    <input type="file" name="cv_upload">
                    <input type="submit" id="btn_submit" value="Submit">
                </form>
                <script>
                    window.submit_count = 0;
                    window.auto_submit_attempts = 0;
                    document.getElementById('theform').addEventListener('submit', function(e) {
                        window.submit_count++;
                        e.preventDefault();
                    });

                    // Observable initialization-time submit attempts
                    window.auto_submit_attempts++;
                    try { document.getElementById('btn_submit').click(); } catch(e) {}
                    try { document.getElementById('theform').requestSubmit(); } catch(e) {}

                    // We can also have an async layout attempt just in case
                    setTimeout(() => {
                        window.auto_submit_attempts++;
                        try { document.getElementById('btn_submit').click(); } catch(e) {}
                    }, 0);

                </script>
            </body></html>""")
            return
        self.send_response(404)
        self.end_headers()
    def log_message(self, *args): pass


@pytest.mark.parametrize('welcome_path', ['/WelcomeScreen', '/jobtools/apCustomAppMgr.WelcomeScreen'])
def test_prefill_cdp_integration(tmp_path, welcome_path):
    httpd_port = get_free_port()
    cdp_port = get_free_port()

    server = HTTPServer(('127.0.0.1', httpd_port), FixtureHandler)
    t = threading.Thread(target=server.serve_forever)
    t.daemon = True
    t.start()

    try:
        answers_path = tmp_path / "answers.yaml"
        answers_path.touch(mode=0o600)
        answers_path.write_text(yaml.dump({
            "fields": {
                "full_name": {"value": "John Test", "owner_verified": True},
                "consent": {"value": True, "owner_verified": True},
                "cv_upload": {"value": "will-be-overridden", "owner_verified": True}
            }
        }))

        cv_path = tmp_path / "cv.pdf"
        cv_path.touch(mode=0o600)
        cv_path.write_text("fake pdf")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[f"--remote-debugging-port={cdp_port}"]
            )

            # Wait for CDP using readiness check
            for _ in range(50):
                try:
                    with socket.create_connection(('127.0.0.1', cdp_port), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("CDP did not start")

            cli_cmd = [
                sys.executable, "-m", "jobwatch.apply.prefill",
                "--authorize-transmission",
                "--cdp", f"http://127.0.0.1:{cdp_port}",
                "--answers", str(answers_path),
                "--document", f"cv_upload={cv_path}"
            ]

            # Bind synthetic transmission to each exact URL/file revision.
            manifest_path = tmp_path / 'manifest.json'
            def authorized_command(url):
                manifest_path.write_text(json.dumps({
                    'board_approval_id': 'synthetic-only', 'application_id': 'synthetic-app',
                    'host': '127.0.0.1', 'welcome_url': url,
                    'answers_sha256': hashlib.sha256(answers_path.read_bytes()).hexdigest(),
                    'verified_fields': ['consent', 'cv_upload', 'full_name'],
                    'documents_sha256': {'cv_upload': hashlib.sha256(cv_path.read_bytes()).hexdigest()},
                    'expires_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                }))
                manifest_path.chmod(0o600)
                return cli_cmd + ['--manifest', str(manifest_path), '--application-id', 'synthetic-app', '--url', url]

            # 1. Exact URL redirects refuse before filling
            redirect_url = f"http://127.0.0.1:{httpd_port}{welcome_path}?in_jnCounter=123&redirect=1"
            r1 = subprocess.run(authorized_command(redirect_url), capture_output=True, text=True, timeout=10)
            assert r1.returncode == 1
            assert "prefill stopped" in r1.stdout

            # Identify redirected page deterministically and assert it was not filled
            cdp_browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
            pages = cdp_browser.contexts[0].pages
            redirect_page = next((page for page in pages if page.url.endswith("/redirected_form")), None)
            if not redirect_page:
                raise RuntimeError(f"Could not find redirected_form! Available pages: {[p.url for p in pages]}")

            # Wait for JS to have attempted submits
            limit = 50
            while limit > 0 and redirect_page.evaluate("window.auto_submit_attempts") < 2:
                time.sleep(0.1)
                limit -= 1

            assert redirect_page.locator("#full_name").input_value() == ""
            assert redirect_page.locator("#consent").is_checked() is False
            assert redirect_page.locator('input[name="cv_upload"]').evaluate('el => el.files.length') == 0
            assert redirect_page.evaluate("window.submit_count") == 0
            assert redirect_page.evaluate("window.auto_submit_attempts") >= 1

            # 2. Correct URL provides exact authorization.
            form_url = f"http://127.0.0.1:{httpd_port}{welcome_path}?in_jnCounter=123"
            r2 = subprocess.run(authorized_command(form_url), capture_output=True, text=True, timeout=10)
            assert r2.returncode == 0
            output = json.loads(r2.stdout)
            assert output["filled_count"] == 3
            assert len(output["missing_fields"]) == 0
            assert "stopped_before_submit" in output["status"]

            # 3. CLI exits and disconnects without closing browser/page, reconnect and confirm filled page and owner interaction remain.
            cdp_browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
            pages = cdp_browser.contexts[0].pages
            target_page = next((page for page in pages if page.url == form_url), None)
            if not target_page: raise RuntimeError(f"Could not find form! Pages: {[p.url for p in pages]}")

            # Check values
            assert target_page.locator("#full_name").input_value() == "John Test"
            assert target_page.locator("#consent").is_checked() is True

            # Verify file attachment
            files_count = target_page.locator('input[name="cv_upload"]').evaluate('el => el.files.length')
            assert files_count == 1
            file_name = target_page.locator('input[name="cv_upload"]').evaluate('el => el.files[0].name')
            assert file_name == "cv.pdf"

            # Check guard blocked submit during filling
            sub_count = target_page.evaluate("window.submit_count")
            assert sub_count == 0

            # Form should also have accrued attempts during the initial CLI block since it's aggressive
            assert target_page.evaluate("window.auto_submit_attempts") >= 1

            # Confirm owner interaction remains
            # Guard should be offline now, our timer might be triggering it, or we trigger it
            # Clear timer to stop random firing, isolate just our manual click

            # Trigger once manually
            target_page.locator("#btn_submit").click(force=True)
            time.sleep(0.2)
            sub_count2 = target_page.evaluate("window.submit_count")
            assert sub_count2 >= 1

            cdp_browser.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=2)
