"""Read-only data for the terminal app's views.

`Backend` is the seam the screens talk to. `WebBackend` calls the same `/api/*` handlers the web app
uses (through an in-process client, no network) and the same task-state functions the chat uses.
Tests pass a fake with the same method names.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
UPLOAD_EXTENSIONS = ('.pdf', '.docx', '.txt', '.md', '.rtf', '.odt')    # refined from intake at runtime
UPLOAD_KINDS = ('cv', 'letter', 'evidence')


class Backend:
    """Interface; every method returns plain dicts/lists and may raise."""

    def overview(self) -> list[dict]: return []
    def counts(self, rows: list[dict]) -> dict: return {'needs_you': 0, 'needs_info': 0, 'outcome_unknown': 0, 'submitted': 0}
    def services(self) -> list[tuple[str, str]]: return []
    def today(self) -> dict: return {}
    def job(self, posting_id: int) -> dict: return {}
    def review_form(self, posting_id: int) -> dict: return {'rows': []}
    def table(self, **params: Any) -> dict: return {'rows': []}
    def applications(self) -> dict: return {}
    def inbox(self) -> dict: return {'open': [], 'closed': []}
    def inbox_decide(self, proposal_id: int, decision: str) -> str: return ''
    def sources(self) -> dict: return {'health': [], 'employers': [], 'sectors': []}
    def insights(self) -> dict: return {}
    def models(self) -> dict: return {'rows': []}
    def save_models(self, picks: dict[str, str]) -> str: return ''
    def test_model(self, role: str) -> str: return ''
    def nav_counts(self) -> dict: return {}
    def chat_model(self) -> str: return ''
    def upload(self, path: Path, kind: str) -> dict: raise NotImplementedError


def check_attachment(path: Path) -> str | None:
    """The reason a file cannot be attached, or None. Same 10 MB limit the upload API enforces."""
    try:
        size = path.stat().st_size
    except OSError:
        return 'cannot read this file'
    if not path.is_file():
        return 'not a file'
    if size > MAX_UPLOAD_BYTES:
        return f'too large ({size / 1048576:.1f} MB; the limit is 10 MB)'
    if path.suffix.lower() not in _extensions():
        return f'{path.suffix or "this"} files are not supported'
    return None


def _extensions() -> tuple[str, ...]:
    try:
        from jobwatch.candidate import intake
        return tuple(intake.EXTENSIONS)
    except Exception:  # noqa: BLE001
        return UPLOAD_EXTENSIONS


class WebBackend(Backend):
    def __init__(self, person: str) -> None:
        self.person = person
        self._client = None
        self._config = None

    # -- plumbing
    def _cfg(self):
        if self._config is None:
            from jobwatch.config import load_config
            self._config = load_config()
        return self._config

    def _web(self):
        if self._client is None:
            from fastapi.testclient import TestClient
            from jobwatch.web.app import create_app
            self._client = TestClient(create_app(self._cfg()), base_url='http://localhost',
                                      headers={'host': 'localhost', 'origin': 'http://localhost'})
        return self._client

    def _get(self, path: str, **params: Any) -> Any:
        resp = self._web().get(path, params={k: v for k, v in params.items() if v not in (None, '')})
        resp.raise_for_status()
        return resp.json()

    # -- chat task state
    def overview(self) -> list[dict]:
        from jobwatch import users
        from pipeline.agentic import task_state
        from pipeline.agentic.chat import job_connection
        with users.use(self.person), job_connection(self._cfg()) as jobs:
            return task_state.jobs_overview(jobs)

    def counts(self, rows: list[dict]) -> dict:
        from pipeline.agentic import task_state
        return task_state.overview_counts(rows)

    # -- web views (the same handlers the web app serves)
    def services(self) -> list[tuple[str, str]]:
        word = {'ok': 'Healthy', 'warn': 'Attention', 'bad': 'Failing'}
        return [(h.get('label') or h.get('collector') or '?', word.get(h.get('rag'), 'Attention'))
                for h in self._get('/api/sources').get('health', [])[:4]]

    def today(self) -> dict:
        table = self._get('/api/table')
        return {'rows': table.get('rows', []), 'progress': table.get('progress') or {}, 'total': table.get('total', 0)}

    def job(self, posting_id: int) -> dict:
        return self._get(f'/api/job/{int(posting_id)}')

    def review_form(self, posting_id: int) -> dict:
        ctx = self.job(posting_id)
        job, links = ctx.get('job') or {}, ctx.get('draft_links') or {}
        names = {k: Path(v).name for k, v in links.items() if v}
        rows = [('Employer', job.get('company') or '', 'posting'), ('Role', job.get('title') or '', f'posting {posting_id}')]
        if names.get('cv'):
            rows.append(('CV', names['cv'], 'attached'))
        if names.get('letter'):
            rows.append(('Cover letter', names['letter'], 'attached'))
        return {'employer': job.get('company') or '', 'role': job.get('title') or '', 'rows': rows}

    def table(self, **params: Any) -> dict:
        return self._get('/api/table', **params)

    def applications(self) -> dict:
        return self._get('/api/applications')

    def inbox(self) -> dict:
        return self._get('/api/inbox')

    def inbox_decide(self, proposal_id: int, decision: str) -> str:
        resp = self._web().post(f'/api/inbox/{int(proposal_id)}/{decision}')
        resp.raise_for_status()
        return str((resp.json() or {}).get('toast') or 'done')

    def sources(self) -> dict:
        return self._get('/api/sources')

    def insights(self) -> dict:
        return self._get('/api/insights')

    def nav_counts(self) -> dict:
        from jobwatch import db as dbm
        from jobwatch.web import queries as q
        conn = dbm.connect(self._cfg().db_path)
        try:
            return q.nav_counts(conn)
        finally:
            conn.close()

    # -- models (the web page's own module functions)
    def models(self) -> dict:
        from jobwatch import model_choice as mc
        from jobwatch.web.models_routes import list_models
        ids, ok = list_models(self.person)
        picks = mc.chosen(self.person)
        rows = [{'role': role, 'label': label, 'value': picks.get(role) or mc.get_model(role, self.person),
                 'custom': role in picks} for role, (label, _) in mc.ROLES.items()]
        return {'rows': rows, 'options': ids, 'gateway_ok': ok, 'gateway': mc.gateway_view(self.person)}

    def save_models(self, picks: dict[str, str]) -> str:
        from jobwatch import model_choice as mc
        try:
            mc.set_models(picks, self.person)
        except (mc.ModelRefused, ValueError) as exc:
            return f'not saved: {exc}'
        return 'saved'

    def test_model(self, role: str) -> str:
        resp = self._web().post('/models/test', json={'role': role})
        body = resp.json()
        return 'ok' if body.get('ok') else str(body.get('error') or 'failed')

    # -- uploads: same save path the upload ticket endpoint ends in (intake.save_upload)
    def upload(self, path: Path, kind: str) -> dict:
        reason = check_attachment(path)
        if reason:
            raise ValueError(reason)
        from jobwatch.candidate import intake
        return intake.save_upload(self.person, path.name, path.read_bytes(), kind)

    def chat_model(self) -> str:
        from jobwatch import model_choice as mc
        try:
            return mc.get_model('chat', self.person)
        except Exception:  # noqa: BLE001
            return ''
