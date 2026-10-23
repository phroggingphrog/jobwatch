"""Synthetic owner-session preparation; no external requests or personal data."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import socket
import sys
import subprocess

import pytest
import yaml
pytest.importorskip('playwright.sync_api',  # module-level: collection used to error without the
                    reason='the prefill tests need the browser extra')  # browser extra, not skip
from playwright.sync_api import sync_playwright

from jobwatch.apply import prefill


@pytest.fixture
def owner():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers()
            if self.path.startswith('/WelcomeScreen'):
                self.wfile.write(b'POST required')
            elif self.path == '/login':
                self.wfile.write(b'<input name=username><input type=password name=pwd>')
            else:
                self.wfile.write(b'<form method=post action="/WelcomeScreen?in_jnCounter=synthetic"><button>Next</button></form>')

        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers()
            self.wfile.write(b'''<form><label for=answer>Response</label>
              <input id=answer name=response required value="SYNTHETIC_VALUE">
              <textarea name=notes>SYNTHETIC_TEXT</textarea>
              <input type=hidden name=csrf value="SYNTHETIC_TOKEN">
              <button onclick="window.clicked=true">Submit</button></form>''')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=[f'--remote-debugging-port={port}'])
        page = browser.new_context().new_page()
        page.goto(f'http://127.0.0.1:{server.server_port}/')
        yield browser, page, f'http://127.0.0.1:{port}'
        browser.close()
    server.shutdown(); server.server_close(); thread.join()


def cli(monkeypatch, cdp, *args):
    result = subprocess.run([sys.executable, '-m', 'jobwatch.apply.prefill', '--cdp', cdp,
                             '--attach', '--allow-host', '127.0.0.1', *args],
                            capture_output=True, text=True, timeout=20)
    print(result.stdout, end='')
    return result.returncode


def test_cli_discovery_attaches_post_step_without_navigation(owner, monkeypatch, capsys, tmp_path):
    browser, page, cdp = owner
    page.get_by_text('Next').click(); page.wait_for_url('**/WelcomeScreen?*')
    page.evaluate('window.marker = 123')
    # GET cannot reproduce this POST-only form.
    probe = page.context.new_page(); probe.goto(page.url)
    assert probe.locator('[name=response]').count() == 0
    probe.close()
    output = tmp_path / 'template.yaml'
    assert cli(monkeypatch, cdp, '--discover', '--generate-template', str(output)) == 0
    metadata = json.loads(capsys.readouterr().out)['controls']
    assert metadata[0] == {'name': 'response', 'id': 'answer', 'type': 'text', 'label': 'Response', 'required': True}
    assert all(set(c) == {'name', 'id', 'type', 'label', 'required'} for c in metadata)
    assert 'SYNTHETIC_' not in json.dumps(metadata)
    assert page.evaluate('window.marker') == 123
    assert page.locator('[name=response]').input_value() == 'SYNTHETIC_VALUE'
    assert page.evaluate('window.clicked') is None
    assert len(browser.contexts[0].pages) == 1
    assert output.stat().st_mode & 0o777 == 0o600
    assert yaml.safe_load(output.read_text()) == {'fields': {
        'response': {'value': '', 'owner_verified': False},
        'notes': {'value': '', 'owner_verified': False}}}


def test_cli_fill_existing_step(owner, monkeypatch, tmp_path):
    _, page, cdp = owner
    page.get_by_text('Next').click(); page.wait_for_url('**/WelcomeScreen?*')
    page.evaluate('window.marker = 456')
    answers = tmp_path / 'answers.yaml'
    answers.write_text('fields:\n  response:\n    value: Synthetic replacement\n    owner_verified: true\n')
    answers.chmod(0o600)
    from datetime import datetime, timedelta, timezone
    import hashlib
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'board_approval_id': 'synthetic', 'application_id': 'synthetic-app',
        'host': '127.0.0.1', 'welcome_url': page.url,
        'answers_sha256': hashlib.sha256(answers.read_bytes()).hexdigest(), 'verified_fields': ['response'],
        'documents_sha256': {}, 'expires_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}))
    manifest.chmod(0o600)
    assert cli(monkeypatch, cdp, '--authorize-transmission', '--answers', str(answers),
               '--manifest', str(manifest), '--application-id', 'synthetic-app') == 0
    assert page.locator('[name=response]').input_value() == 'Synthetic replacement'
    assert page.evaluate('window.marker') == 456
    assert page.evaluate('window.clicked') is None


def test_host_mismatch_and_ambiguous_tabs_refuse(owner):
    browser, page, _ = owner
    with pytest.raises(prefill.PrefillRefused):
        prefill.select_owner_page(browser, ['localhost'])
    extra = browser.contexts[0].new_page()
    with pytest.raises(prefill.PrefillRefused):
        prefill.select_owner_page(browser, ['127.0.0.1'])
    assert prefill.select_owner_page(browser, ['127.0.0.1'], tab_index=0) == page
    with pytest.raises(prefill.PrefillRefused):
        prefill.select_owner_page(browser, ['127.0.0.1'], tab_index=1)
    extra.close()


@pytest.mark.parametrize('host', ['localhost', '*.0.0.1', '127.0.0.1.evil.invalid', 'http://127.0.0.1', '127.0.0.1:80'])
def test_cli_host_refusal_no_template_or_mutation(owner, monkeypatch, tmp_path, host):
    _, page, cdp = owner
    page.get_by_text('Next').click(); page.wait_for_url('**/WelcomeScreen?*')
    output = tmp_path / 'new.yaml'
    result = subprocess.run([sys.executable, '-m', 'jobwatch.apply.prefill', '--cdp', cdp,
                             '--attach', '--allow-host', host, '--discover',
                             '--generate-template', str(output)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 1
    assert not output.exists()
    assert page.locator('[name=response]').input_value() == 'SYNTHETIC_VALUE'


def test_discovery_wrapped_labels_exclude_control_contents(owner):
    _, page, _ = owner
    page.set_content('<label>Notes<textarea name=notes>SYNTHETIC_TEXT</textarea></label>'
                     '<label>Pick<select name=choice><option>SYNTHETIC_OPTION</option></select></label>')
    metadata = prefill.discover_controls(page, allowed_hosts=['127.0.0.1'])
    assert [c['label'] for c in metadata] == ['Notes', 'Pick']
    assert 'SYNTHETIC_' not in json.dumps(metadata)


def test_login_discovery_and_password_target_refusal(owner):
    _, page, _ = owner
    page.goto(page.url + 'login')
    metadata = prefill.discover_controls(page, allowed_hosts=['127.0.0.1'])
    assert metadata[1]['type'] == 'password'
    with pytest.raises(prefill.PrefillRefused, match='password'):
        prefill.fill_page(page, {'username': {'value': 'Synthetic', 'owner_verified': True},
                                'pwd': {'value': 'Synthetic', 'owner_verified': True}}, {}, authorized_url=page.url)
    assert page.locator('[name=username]').input_value() == ''
    assert page.locator('[name=pwd]').input_value() == ''


@pytest.mark.parametrize('existing', ['fields:\n  x:\n    value: Synthetic\n    owner_verified: true\n', 'legacy: Synthetic\n'])
def test_template_refuses_existing_without_carry_over(tmp_path, existing):
    path = tmp_path / 'answers.yaml'; path.write_text(existing); path.chmod(0o600)
    with pytest.raises(prefill.PrefillRefused):
        prefill.generate_template(path, [{'name': 'x', 'id': '', 'type': 'text'}])
    assert path.read_text() == existing


def test_template_symlink_refused_password_omitted_and_id_fallback(tmp_path):
    target = tmp_path / 'target'; target.write_text('unchanged')
    link = tmp_path / 'link'; link.symlink_to(target)
    controls = [{'name': 'pwd', 'id': '', 'type': 'password'}, {'name': '', 'id': 'notes', 'type': 'textarea'}]
    with pytest.raises(prefill.PrefillRefused):
        prefill.generate_template(link, controls)
    assert target.read_text() == 'unchanged'
    path = tmp_path / 'new.yaml'; prefill.generate_template(path, controls)
    assert yaml.safe_load(path.read_text()) == {'fields': {'notes': {'value': '', 'owner_verified': False}}}
