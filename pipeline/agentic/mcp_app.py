"""MCP Apps rendering adapter. Native HTTP remains the authority for every operation."""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import base64
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
from pipeline.agentic.cards import CardKind, TITLES, resolve

# LibreChat persists resolved app resources with historical messages. New views
# must name the current bundle instead of silently reusing an older saved UI.
_BUNDLE = Path(__file__).with_name('jobwatch-app.html')
UI = 'ui://jobwatch/panel-' + hashlib.sha256(_BUNDLE.read_bytes()).hexdigest()[:16] + '.html'
ID = re.compile(r'[A-Za-z0-9_-]{1,100}')


class Verifier(TokenVerifier):
    def __init__(self, credentials):
        super().__init__(required_scopes=['jobwatch'])
        self.credentials = credentials

    async def verify_token(self, token):
        digest = hashlib.sha256(token.encode()).digest()
        for key, p in self.credentials().items():
            expected = hashlib.sha256(key.encode()).digest()
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
    def all_credentials():
        from pipeline.agentic import identity
        return {**credentials, **identity.credentials()}

    server = FastMCP('Jobwatch', auth=Verifier(all_credentials), mask_error_details=True,
        instructions='Jobwatch owns its agent. jobwatch_view renders an existing native run; it cannot approve work.')

    def auth(scope):
        token = get_access_token()
        if token is None or scope not in token.scopes:
            raise RuntimeErrorSafe('scope_required')
        # Resolve again from server configuration. No person or credential is accepted in tool arguments.
        for key, principal in all_credentials().items():
            if hmac.compare_digest(key, token.token):
                return key, principal
        raise RuntimeErrorSafe('authentication_required')

    async def native(path, *, method='GET', body=None, human=False, run=False, request_key=None):
        key, p = auth('approve' if human else 'read')
        if run:
            # Only an authenticated human app operation can delegate a paid native command.
            if not human:
                raise RuntimeErrorSafe('human_required')
            candidates = [k for k, q in all_credentials().items() if q.person == p.person and 'run' in q.scopes
                          and 'approve' not in q.scopes and 'interact' not in q.scopes]
            if len(candidates) != 1:
                raise RuntimeErrorSafe('run_credential_required')
            key = candidates[0]
        async with httpx.AsyncClient(base_url=base_url, transport=transport, timeout=30,
                                     follow_redirects=False) as client:
            res = await client.request(method, path, json=body, headers={'Authorization': 'Bearer ' + key, **({'Idempotency-Key':request_key} if request_key else {})})
        if res.status_code >= 300:
            # Native responses contain fixed safe codes. Never surface response bodies or credentials.
            raise RuntimeErrorSafe('native_request_failed_' + str(res.status_code))
        return res

    def ident(value):
        if not isinstance(value, str) or not ID.fullmatch(value):
            raise RuntimeErrorSafe('invalid_id')
        return value

    async def state(run_id, kind="auto", subject="0", legacy=False):
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
        selections = []
        for outcome in (run.get('result') or {}).get('outcomes') or []:
            if outcome.get('status') == 'selected' and outcome.get('selection_id'):
                selection = (await native('/api/agent/selections/' + ident(outcome['selection_id']))).json()
                selections.append(selection)
        chosen = resolve(run,requested=kind,has_profile=bool((profile.get('current') or {}).get('version')))
        if not legacy and chosen in ('progress','documents'):
            recent=(await native('/api/agent/selections')).json()['selections']
            selections=list({v['id']:v for v in [*selections,*recent]}.values())
        value = {'run':run,'card':{'kind':chosen,'title':TITLES[chosen],'subject_id':subject},
                 'profile':profile,'selections':selections}
        if chosen == 'models' or legacy:
            value['models'] = (await native('/api/agent/client/models')).json()
        if chosen == 'jobs' or legacy:
            value['shortlist'] = (await native('/api/agent/shortlist')).json()
        if not legacy and chosen in ('application','documents'):
            res = await native('/api/agent/applications')
            value['applications'] = res.json()['applications']
            if chosen == 'application' and subject != '0':
                if not subject.isdecimal():
                    raise RuntimeErrorSafe('invalid_subject')
                value['application'] = (await native('/api/agent/applications/'+subject)).json()
        return value


    @server.tool(name='jobwatch_view', title='Jobwatch', annotations={'readOnlyHint': True},
                 meta={'ui': {'resourceUri': UI}, 'ui/resourceUri': UI})
    async def view(run_id: str, card_kind: CardKind = "auto", subject_id: str = "0"):
        """Show the authenticated person's existing Jobwatch run inside the conversation."""
        run = (await native('/api/agent/runs/' + ident(run_id))).json()
        return ToolResult(structured_content={'run_id': run['id'], 'state': run['state'], 'card_kind':card_kind,
            'subject_id':ident(subject_id),'created':run['created'],'card_title':TITLES[card_kind]})

    @server.resource(UI, name='Jobwatch panel', mime_type='text/html;profile=mcp-app',
        meta={'ui': {'prefersBorder': True, 'csp': {'connectDomains': [origin], 'resourceDomains': [],
                                                  'frameDomains': [], 'baseUriDomains': []}}})
    def panel():
        auth('read')
        return _BUNDLE.read_text()

    # Keep the original resource available for historical integrations.
    server.resource('ui://jobwatch/panel.html', name='Jobwatch legacy panel',
        mime_type='text/html;profile=mcp-app',
        meta={'ui': {'prefersBorder': True, 'csp': {'connectDomains': [origin],
            'resourceDomains': [], 'frameDomains': [], 'baseUriDomains': []}}})(panel)

    @server.resource('jobwatch://runs/{run_id}', mime_type='application/json')
    async def run_resource(run_id: str):
        return json.dumps(await state(run_id,legacy=True))

    @server.resource('jobwatch://cards/{run_id}/{kind}/{subject}', mime_type='application/json')
    async def card_resource(run_id: str, kind: str, subject: str):
        if kind not in TITLES:
            raise RuntimeErrorSafe('invalid_card')
        return json.dumps(await state(ident(run_id),kind,ident(subject)))

    @server.resource('jobwatch://browser/{posting_id}/{part}', mime_type='application/json')
    async def browser_resource(posting_id: str, part: str):
        auth('approve')
        if not posting_id.isdecimal() or part not in ('frame','review','status'):
            raise RuntimeErrorSafe('invalid_browser_resource')
        path='/api/agent/applications/'+posting_id+('' if part=='status' else '/'+part)
        res=await native(path,human=True)
        return json.dumps({'jpeg':base64.b64encode(res.content).decode()} if part=='frame' else res.json())

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
    async def action(action: Literal['respond', 'cancel', 'retry', 'cancel_selection', 'models', 'upload_ticket',
                                    'parse_uploads', 'profile_answer', 'profile_edit', 'profile_confirm',
                                    'download_ticket', 'select_jobs','browser_open','browser_control','browser_review','browser_submit','browser_answers','browser_restart'], arguments: dict):
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
        elif action == 'cancel_selection':
            if a:
                raise RuntimeErrorSafe('invalid_arguments')
            res = await native('/api/agent/selections/' + ident(target) + '/cancel', method='POST', human=True)
        elif action == 'models':
            res = await native('/api/agent/client/models', method='POST', body=a, human=True)
        elif action == 'upload_ticket':
            res = await native('/api/agent/client/upload-ticket', method='POST', body=a, human=True)
        elif action == 'download_ticket':
            if a:
                raise RuntimeErrorSafe('invalid_arguments')
            res = await native('/api/agent/client/artifacts/' + ident(target) + '/download-ticket', method='POST', human=True)
        elif action == 'select_jobs':
            request_key=a.pop('request_key',None)
            if not request_key:
                raise RuntimeErrorSafe('request_key_required')
            res=await native('/api/agent/selections',method='POST',body=a,human=True,request_key=request_key)
        elif action.startswith('browser_'):
            pid=a.pop('posting_id',None)
            if type(pid) is not int or not 0 < pid < 2**63:
                raise RuntimeErrorSafe('invalid_posting')
            request_key=a.pop('request_key',None)
            if action == 'browser_control':
                if a:
                    raise RuntimeErrorSafe('invalid_arguments')
                res=await native('/api/agent/client/browser/control',method='POST',body={'posting_id':pid},human=True)
            else:
                suffix={'browser_open':'open','browser_restart':'open','browser_review':'review','browser_submit':'submit','browser_answers':'answers'}[action]
                if action == 'browser_restart':
                    a['restart']=True
                res=await native('/api/agent/applications/'+str(pid)+'/'+suffix,method='POST',body=a,human=True,request_key=request_key)
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
