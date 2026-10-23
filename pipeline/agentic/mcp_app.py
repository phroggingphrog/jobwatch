"""MCP Apps rendering adapter. Native HTTP remains the authority for every operation."""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
from typing import Literal
from urllib.parse import urlparse

import httpx
from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token
from fastmcp.tools import ToolResult

from pipeline.agentic.api import credentials_from_env
from pipeline.agentic.runtime import RuntimeErrorSafe

UI = 'ui://jobwatch/panel.html'
ID = re.compile(r'[A-Za-z0-9_-]{1,100}')


class Verifier(TokenVerifier):
    def __init__(self, credentials):
        super().__init__(required_scopes=['jobwatch'])
        self.hashes = [(hashlib.sha256(k.encode()).digest(), p) for k, p in credentials.items()]

    async def verify_token(self, token):
        digest = hashlib.sha256(token.encode()).digest()
        for expected, p in self.hashes:
            if hmac.compare_digest(digest, expected):
                return AccessToken(token=token, client_id='jobwatch-app', subject=p.person,
                                   scopes=['jobwatch', *p.scopes])
        return None


def create_server(*, credentials=None, base_url=None, origin=None, transport=None):
    credentials = credentials if credentials is not None else credentials_from_env()
    base_url = base_url or os.environ.get('JOBWATCH_NATIVE_URL', 'http://127.0.0.1:18914')
    url = urlparse(base_url)
    if url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost', '::1') or url.username:
        raise RuntimeErrorSafe('native_url_not_allowed')
    origin = origin or os.environ.get('JOBWATCH_APP_ORIGIN', '')
    if not re.fullmatch(r'https://[A-Za-z0-9.-]+(?::[0-9]+)?', origin):
        raise RuntimeErrorSafe('app_origin_required')
    server = FastMCP('Jobwatch', auth=Verifier(credentials), mask_error_details=True,
        instructions='Jobwatch owns its agent. jobwatch_view renders an existing native run; it cannot approve work.')

    def auth(scope):
        token = get_access_token()
        if token is None or scope not in token.scopes:
            raise RuntimeErrorSafe('scope_required')
        # Resolve again from server configuration. No person or credential is accepted in tool arguments.
        for key, principal in credentials.items():
            if hmac.compare_digest(key, token.token):
                return key, principal
        raise RuntimeErrorSafe('authentication_required')

    async def native(path, *, method='GET', body=None, human=False, run=False):
        key, p = auth('approve' if human else 'read')
        if run:
            # Only an authenticated human app operation can delegate a paid native command.
            if not human:
                raise RuntimeErrorSafe('human_required')
            candidates = [k for k, q in credentials.items() if q.person == p.person and 'run' in q.scopes
                          and 'approve' not in q.scopes and 'interact' not in q.scopes]
            if len(candidates) != 1:
                raise RuntimeErrorSafe('run_credential_required')
            key = candidates[0]
        async with httpx.AsyncClient(base_url=base_url, transport=transport, timeout=30,
                                     follow_redirects=False) as client:
            res = await client.request(method, path, json=body, headers={'Authorization': 'Bearer ' + key})
        if res.status_code >= 300:
            # Native responses contain fixed safe codes. Never surface response bodies or credentials.
            raise RuntimeErrorSafe('native_request_failed_' + str(res.status_code))
        return res

    def ident(value):
        if not isinstance(value, str) or not ID.fullmatch(value):
            raise RuntimeErrorSafe('invalid_id')
        return value

    async def state(run_id):
        run = (await native('/api/agent/runs/' + ident(run_id))).json()
        for _ in range(64):
            if run['state'] != 'resumed':
                break
            # Resume IDs are read from authoritative, same-person native state.
            from pipeline.agentic.api_store import APIStore
            _, principal = auth('read')
            with APIStore(principal.person) as store:
                row = store.conn.execute('SELECT resume_run FROM api_interactions WHERE run_id=? '
                    'AND resume_run IS NOT NULL LIMIT 1', (run['id'],)).fetchone()
            if row is None:
                break
            run = (await native('/api/agent/runs/' + ident(row[0]))).json()
        profile = (await native('/api/agent/client/profile')).json()
        return {'run': run, 'profile': profile,
                'models': (await native('/api/agent/client/models')).json(),
                'shortlist': (await native('/api/agent/shortlist')).json()}

    @server.tool(name='jobwatch_view', title='Jobwatch', annotations={'readOnlyHint': True},
                 meta={'ui': {'resourceUri': UI}, 'ui/resourceUri': UI})
    async def view(run_id: str):
        """Show the authenticated person's existing Jobwatch run inside the conversation."""
        run = (await native('/api/agent/runs/' + ident(run_id))).json()
        return ToolResult(structured_content={'run_id': run['id'], 'state': run['state']})

    @server.resource(UI, name='Jobwatch panel', mime_type='text/html;profile=mcp-app',
        meta={'ui': {'prefersBorder': True, 'csp': {'connectDomains': [origin], 'resourceDomains': [],
                                                  'frameDomains': [], 'baseUriDomains': []}}})
    def panel():
        auth('read')
        return Path(__file__).with_name('jobwatch-app.html').read_text()

    @server.resource('jobwatch://runs/{run_id}', mime_type='application/json')
    async def run_resource(run_id: str):
        return json.dumps(await state(run_id))

    @server.resource('jobwatch://artifacts/{artifact_id}', mime_type='application/json')
    async def artifact_resource(artifact_id: str):
        res = await native('/api/agent/artifacts/' + ident(artifact_id))
        if res.headers.get('content-type', '').startswith('application/pdf'):
            from pypdf import PdfReader
            text = '\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(res.content)).pages)
        else:
            text = res.text
        return json.dumps({'text': text[:150000], 'truncated': len(text) > 150000})

    @server.tool(name='jobwatch_action', title='Confirm a Jobwatch action',
                 meta={'ui': {'visibility': ['app']}}, annotations={'readOnlyHint': False})
    async def action(action: Literal['respond', 'cancel', 'retry', 'models', 'upload_ticket',
                                    'parse_uploads', 'profile_answer', 'profile_edit', 'profile_confirm',
                                    'download_ticket'], arguments: dict):
        """Human app action only. LibreChat displays the exact arguments before confirmation."""
        auth('approve')  # visibility is a host hint; scope is the actual security boundary
        a = dict(arguments)
        target = a.pop('id', None)
        if action == 'respond':
            res = await native('/api/agent/interactions/' + ident(target) + '/responses',
                               method='POST', body=a, human=True)
        elif action in ('cancel', 'retry'):
            if a:
                raise RuntimeErrorSafe('invalid_arguments')
            res = await native('/api/agent/runs/' + ident(target) + '/' + action, method='POST', human=True, run=True)
        elif action == 'models':
            res = await native('/api/agent/client/models', method='POST', body=a, human=True)
        elif action == 'upload_ticket':
            res = await native('/api/agent/client/upload-ticket', method='POST', body=a, human=True)
        elif action == 'download_ticket':
            if a:
                raise RuntimeErrorSafe('invalid_arguments')
            res = await native('/api/agent/client/artifacts/' + ident(target) + '/download-ticket', method='POST', human=True)
        elif action == 'parse_uploads':
            path = ('/api/agent/profile/proposals/' + ident(target) + '/uploads' if target else '/api/agent/profile/proposals')
            res = await native(path, method='POST', body=a, human=True, run=True)
        else:
            suffix = {'profile_answer': '/answers', 'profile_edit': '', 'profile_confirm': '/confirm'}[action]
            res = await native('/api/agent/profile/proposals/' + ident(target) + suffix,
                               method='PATCH' if action == 'profile_edit' else 'POST', body=a, human=True)
        # Capabilities and candidate data are delivered to the app, outside model-visible content.
        return ToolResult(content='Jobwatch action completed.', meta={'jobwatch': res.json()})

    return server


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Jobwatch embedded MCP App')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=18918)
    args = parser.parse_args()
    create_server().run(transport='http', host=args.host, port=args.port, stateless_http=True)
