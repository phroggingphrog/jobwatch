"""A realistic filled application in a temp data dir, for end-to-end checks of the ChatGPT connector.

Real parts: the fill step (jobwatch.apply.prepare.prepare_application) driving a real Chromium page on a local employer-style
form, the browser session manager, the native browser API (pipeline.agentic.browser_api over HTTP) that the connector reads
the live form from, the preparation record on disk, the digest, and the loopback connector front. Stubbed: only the paid
model call (answers_agent.run_role) and the package freshness check. The employer form is a local page whose Submit is a
no-op; the worker that would press a queued Submit is NOT started (uvicorn lifespan off), so nothing is ever pressed.

Never touches the live install: everything lives under `root`, and the install settings file is replaced by /dev/null.
Run by hand:  python -m tests.realapp serve --root /tmp/opencode/realapp   (prints the ports, then waits)
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

CONNECTOR_TOKEN = 'c' * 40            # bearer between the TypeScript server and the Python front (fake)
NATIVE_CHAT, NATIVE_HUMAN = 'a' * 40, 'b' * 40       # the native browser API's own keys (fake)
CV_NAME, LETTER_NAME = 'Alex_Example_CV_2026.pdf', 'Cover letter - Acme Pty Ltd.pdf'
MOTIVATION = (
    'I have spent six years turning messy finance and operations data into reporting people trust: ledger '
    'reconciliations in Excel, SQL extracts that replaced a weekly manual copy-paste, and dashboards the '
    'finance team now reads every Monday.\n\n'
    'This role is mostly that work at a larger scale, with a team that cares about data quality. I would '
    'start by learning how your reporting is produced today, then remove the slowest manual step first.\n\n'
    'I am based in Melbourne and can work three days a week in the office.')
CV_TEXT = ('Full name: Alex Example. Reconciled invoices in Excel. Built SQL extracts and dashboards for the finance team. '
           'Based in Melbourne. Consent to processing: yes.')

FORM = '''<!doctype html><meta charset=utf-8><title>Apply - Data Analyst</title>
<form id=f method=post action="/submit" onsubmit="window.submits=(window.submits||0)+1;return false">
<label>Full name<input name=full_name></label>
<label>Why are you suitable for this role?<textarea name=motivation rows=8></textarea></label>
<label>CV<input type=file name=cv></label><label>Cover letter<input type=file name=letter></label>
<button>Submit application</button></form><script>window.submits=0</script>'''


def _pdf(text: str) -> bytes:
    from weasyprint import HTML
    return HTML(string='<p>' + (text + ' ') * 12 + '</p>').write_pdf()


def _fake_run_role(role, context, budget, llm):
    """Stands in for the paid model: answers only from the CV text with a real quote, and approves."""
    if role.name == 'prefill_answers':
        source_ids = {item['source_id']: item['content_hash'] for item in context['sources']}
        rows = []
        for question in context['questions']:
            name = question['question'].lower()
            if 'suitable' in name:
                value, quote, source = MOTIVATION, 'Reconciled invoices in Excel.', 'agent_draft'
            else:
                value, quote, source = 'Alex Example', 'Alex Example', 'profile'
            rows.append({'key': question['key'], 'value': value, 'source': source, 'question_to_owner': '',
                         'citations': [{'source_id': 'cv.md', 'content_hash': source_ids['cv.md'], 'quote': quote}]})
        output = {'answers': rows}
    else:
        from jobwatch.apply import answers_agent
        output = {'approved': True, 'checks': dict.fromkeys(answers_agent.CHECKS, True), 'feedback': []}
    return SimpleNamespace(output=role.tools[-1].arguments_model.model_validate(output))


def _serve_form():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            seen.append(('GET', self.path))
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(FORM.encode())

        def do_POST(self):
            seen.append(('POST', self.path))
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'This synthetic employer endpoint is never called by Jobwatch.')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen


def _uvicorn(app, port: int):
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning', lifespan='off'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            return server, thread
        time.sleep(0.1)
    raise RuntimeError('server did not start')


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _seed(db_path: Path, app_url: str, drafts: Path) -> None:
    from jobwatch import db as dbm
    conn = dbm.connect(db_path)
    conn.execute("INSERT INTO postings(id,source,source_id,url,url_hash,dedupe_key,title,company,location,first_seen_at,last_seen_at)"
                 " VALUES(1,'seek','1',?, 'h','d','Senior Data Analyst','Acme Pty Ltd','Melbourne VIC','t','t')", (app_url,))
    conn.execute("INSERT INTO applications(id,posting_id,status,created_at,updated_at) VALUES(1,1,'drafted','t','2026-10-25T10:00:00')")
    conn.execute("INSERT INTO ad_reviews(posting_id,content_hash,prompt_version,model,verdict,reviewed_at,score,reason,pros_json,cons_json)"
                 " VALUES(1,'c',1,'m','show','t',4.2,'Matches the SQL, reporting and reconciliation work in your CV.',?,?)",
                 (json.dumps(['SQL and dashboards', 'Hybrid, 3 days in Melbourne']), json.dumps(['Contract, 6 months'])))
    conn.execute("INSERT INTO selection_requests(id,person,request_key,input_hash,manifest_json,state,created_at,updated_at)"
                 " VALUES('s1','owner','k','h',?,'completed','t','2026-10-25T10:00:00')",
                 (json.dumps({'request': {'posting_ids': [1]}}),))
    conn.execute("INSERT INTO drafts(application_id,version,created_at,status,dir) VALUES(1,1,'t','ready',?)", (str(drafts),))
    conn.commit()
    conn.close()


class RealApplication:
    """Handles to the running pieces. `connector` is the base URL of the Python JSON front (bearer CONNECTOR_TOKEN)."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def edit(self, label_name: str, value: str) -> None:
        """The owner types into the live employer form (what a person does in the application browser)."""
        self.manager.with_page('1', lambda page: page.locator(f'[name={label_name}]').fill(value))

    def form_value(self, name: str) -> str:
        return self.manager.with_page('1', lambda page: page.locator(f'[name={name}]').input_value())

    def employer_requests(self) -> list:
        return list(self.seen)

    def queued(self) -> list:
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute('SELECT posting_id, status FROM submit_requests').fetchall() \
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name='submit_requests'").fetchone() else []
        finally:
            conn.close()


@contextmanager
def real_application(root: Path, *, connector_port: int | None = None, native_port: int | None = None):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    data = root / 'data'
    data.mkdir(mode=0o700, exist_ok=True)
    profile = root / 'profile'
    profile.mkdir(mode=0o700, exist_ok=True)
    (profile / 'cv.md').write_text(CV_TEXT)
    (profile / 'cv.md').chmod(0o600)
    native_port, connector_port = native_port or _free_port(), connector_port or _free_port()
    env = {'JOBWATCH_SETTINGS': os.devnull, 'JOBWATCH_DATA_DIR': str(data), 'JOBWATCH_CONFIG_DIR': str(root / 'config'),
           'JOBWATCH_DB': str(data / 'jobwatch.db'),       # the default person's DB would otherwise be the install's own
           'JOBWATCH_AGENT_TOKEN': NATIVE_CHAT, 'JOBWATCH_AGENT_APPROVAL_TOKEN': NATIVE_HUMAN,
           'JOBWATCH_NATIVE_BROWSER_URL': f'http://127.0.0.1:{native_port}', 'JOBWATCH_MCP_PERSON': 'owner'}
    (root / 'config').mkdir(exist_ok=True)
    for name in ('JOBWATCH_NATIVE_BROWSER_ENABLED', 'JOBWATCH_LIBRECHAT_ENABLED'):
        os.environ.pop(name, None)
    with mock.patch.dict(os.environ, env):
        from jobwatch import users
        from jobwatch.apply import answers_agent, browser as workflow, prepare
        from jobwatch.config import DEFAULT_CONFIG_DIR, DEFAULT_SETTINGS, Config, _merge, load_config
        from jobwatch.web.browser_session import BrowserSessionManager
        from pipeline.agentic import connector_http
        from pipeline.agentic.api import Principal, create_api
        db = users.db_path('owner')
        for resolved in (db, users.user_dir('owner'), load_config().db_path):
            if root.resolve() not in Path(resolved).resolve().parents:
                raise RuntimeError('refusing: a data path resolves outside the temp root')
        drafts = data / 'drafts' / '1' / 'v1'
        drafts.mkdir(parents=True)
        cv_pdf, letter_pdf = drafts / CV_NAME, drafts / LETTER_NAME
        cv_pdf.write_bytes(_pdf('Alex Example curriculum vitae finance reporting SQL dashboards'))
        letter_pdf.write_bytes(_pdf('Dear hiring team, I am writing about the Senior Data Analyst role at Acme'))
        employer, seen = _serve_form()
        form_url = f'http://127.0.0.1:{employer.server_port}/'
        _seed(db, form_url, drafts)
        manifest = {'pdfs': {'cv': hashlib.sha256(cv_pdf.read_bytes()).hexdigest(), 'letter': hashlib.sha256(letter_pdf.read_bytes()).hexdigest()},
                    'verification': dict.fromkeys(('cv_pdf', 'letter_pdf', 'claims', 'review'), True)}
        package = {'run_key': 'c' * 64, 'status': 'ready', 'manifest': manifest, 'cv_pdf': str(cv_pdf),
                   'letter_pdf': str(letter_pdf), 'candidate': None, 'evaluation': None}
        manager = BrowserSessionManager(None, allow_loopback=True)
        config = Config(config_dir=DEFAULT_CONFIG_DIR, settings=_merge(DEFAULT_SETTINGS, {'db_path': str(db)}),
                        rules={}, searches={}, feeds={}, employers=[])
        native = create_api(credentials={NATIVE_CHAT: Principal('owner'),
                                         NATIVE_HUMAN: Principal('owner', frozenset({'read', 'approve', 'interact'}))},
                            config=config, browser_sessions=manager)
        servers = []
        with mock.patch.object(answers_agent, 'run_role', _fake_run_role), \
                mock.patch.object(workflow, 'latest_result', lambda *a: package), \
                mock.patch.object(workflow, 'package_is_current', lambda *a: True):
            try:
                manager.open('1', form_url)

                def fill(page):
                    return prepare.prepare_application(
                        page, application_id='1', package_manifest=manifest, document_paths={'cv': cv_pdf, 'letter': letter_pdf},
                        profile_root=profile, data_root=users.user_dir(), job={'title': 'Senior Data Analyst', 'company': 'Acme Pty Ltd'},
                        budget=object(), llm=object(), reviewer=object(), allowed_hosts=['127.0.0.1'])
                result = manager.prepare('1', fill).result(timeout=120)
                if result.status != 'ready_for_owner':
                    raise RuntimeError(f'fill did not reach review: {result.status} {result.reason}')
                servers.append(_uvicorn(native, native_port)[0])
                servers.append(_uvicorn(connector_http.create_app(token=CONNECTOR_TOKEN, person='owner'), connector_port)[0])
                yield RealApplication(root=root, db=db, manager=manager, seen=seen, result=result,
                                      connector=f'http://127.0.0.1:{connector_port}', native=f'http://127.0.0.1:{native_port}',
                                      form_url=form_url)
            finally:
                for server in servers:
                    server.should_exit = True
                manager.close_all()
                employer.shutdown()
                employer.server_close()


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description='Realistic filled application in a temp dir (never the live install)')
    parser.add_argument('command', choices=['serve'])
    parser.add_argument('--root', required=True)
    parser.add_argument('--connector-port', type=int, default=18952)
    parser.add_argument('--native-port', type=int, default=18951)
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if not str(root).startswith('/tmp/'):
        raise SystemExit('refusing: --root must be under /tmp')
    with real_application(root, connector_port=args.connector_port, native_port=args.native_port) as app:
        print(json.dumps({'connector': app.connector, 'connector_token': CONNECTOR_TOKEN, 'native': app.native}), flush=True)
        # Control channel for hand/driver use: one JSON line per command on stdin, e.g. {"edit": "motivation", "value": "..."}
        # (the owner typing into the live employer form). Ends when stdin closes or on Ctrl-C.
        try:
            for line in sys.stdin:
                if not line.strip():
                    continue
                command = json.loads(line)
                if 'edit' in command:
                    app.edit(str(command['edit']), str(command['value']))
                    print(json.dumps({'edited': command['edit']}), flush=True)
            while sys.stdin.isatty():
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
