"""Optional OAuth 2.1 for the Jobwatch MCP server (authorization code + PKCE S256, dynamic client registration).

Off by default (JOBWATCH_MCP_OAUTH=1 turns it on). ChatGPT connectors support OAuth or no auth, not a static bearer
token. One passphrase-gated consent page maps whoever completes it to the one configured Jobwatch person; the bearer
verifier keeps working beside it. State is in memory: a restart makes ChatGPT sign in again. Never serve this on a
public URL without the owner's decision; this module opens nothing by itself.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import secrets
import time
from urllib.parse import urlencode

from mcp.server.auth.provider import (AccessToken, AuthorizationCode, AuthorizationParams, RefreshToken,
                                      TokenError, construct_redirect_uri)
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from fastmcp.server.auth import OAuthProvider

SCOPE = 'jobwatch'
CODE_SECONDS, ACCESS_SECONDS, REFRESH_SECONDS, TXN_SECONDS, MAX_ATTEMPTS = 300, 3600, 30 * 86400, 600, 5


class JobwatchOAuth(OAuthProvider):
    def __init__(self, *, base_url: str, person: str, passphrase: str):
        if len(passphrase or '') < 16:
            raise ValueError('oauth_passphrase_too_short')
        super().__init__(base_url=base_url, required_scopes=[SCOPE],
                         client_registration_options=ClientRegistrationOptions(
                             enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]),
                         revocation_options=RevocationOptions(enabled=True))
        self._person, self._pass = person, passphrase.encode()
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._txns: dict[str, dict] = {}
        self._codes: dict[str, AuthorizationCode] = {}
        self._access: dict[str, AccessToken] = {}
        self._refresh: dict[str, RefreshToken] = {}

    # -- registration and authorization --------------------------------------------------------------------
    async def get_client(self, client_id):
        return self._clients.get(client_id)

    async def register_client(self, client_info):
        self._clients[client_info.client_id] = client_info

    async def authorize(self, client, params: AuthorizationParams) -> str:
        now = time.time()
        for key in [k for k, v in self._txns.items() if v['expires'] <= now]:
            del self._txns[key]
        txn = secrets.token_urlsafe(24)
        self._txns[txn] = {'client': client, 'params': params, 'attempts': 0, 'expires': now + TXN_SECONDS}
        return f"{str(self.base_url).rstrip('/')}/oauth/consent?{urlencode({'txn': txn})}"

    def _page(self, txn: str, note: str = '') -> HTMLResponse:
        who = html.escape(self._txns[txn]['client'].client_name or 'An app')
        return HTMLResponse(
            '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Allow access to Jobwatch</title><style>body{font:16px system-ui;max-width:28rem;margin:3rem auto;padding:0 1rem}'
            'input,button{font:inherit;padding:.6rem;margin:.4rem 0;width:100%;box-sizing:border-box}</style>'
            f'<h1>Allow access to Jobwatch</h1><p>{who} wants to read your jobs, hand work to the Jobwatch agent '
            'and, only from a button you press, submit a reviewed application.</p>'
            f'<p role="alert">{html.escape(note)}</p>'
            f'<form method="post"><input type="hidden" name="txn" value="{html.escape(txn)}">'
            '<label>Jobwatch passphrase<input type="password" name="passphrase" autocomplete="current-password" required></label>'
            '<button type="submit">Allow</button><button type="submit" name="deny" value="1">Deny</button></form>')

    async def consent(self, request: Request):
        form = await request.form() if request.method == 'POST' else None
        txn = (form.get('txn') if form else request.query_params.get('txn')) or ''
        entry = self._txns.get(txn)
        if entry is None or entry['expires'] <= time.time():
            return HTMLResponse('This sign-in link expired. Start again from ChatGPT.', status_code=400)
        if form is None:
            return self._page(txn)
        params = entry['params']
        if form.get('deny'):
            del self._txns[txn]
            return RedirectResponse(construct_redirect_uri(str(params.redirect_uri), error='access_denied',
                                                           state=params.state), status_code=302)
        entry['attempts'] += 1
        if not hmac.compare_digest(hashlib.sha256(str(form.get('passphrase') or '').encode()).digest(),
                                   hashlib.sha256(self._pass).digest()):
            if entry['attempts'] >= MAX_ATTEMPTS:
                del self._txns[txn]
                return HTMLResponse('Too many attempts. Start again from ChatGPT.', status_code=429)
            return self._page(txn, 'That passphrase is wrong.')
        del self._txns[txn]
        code = secrets.token_urlsafe(32)
        self._codes[code] = AuthorizationCode(
            code=code, scopes=[SCOPE], expires_at=time.time() + CODE_SECONDS, client_id=entry['client'].client_id,
            code_challenge=params.code_challenge, redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource, subject=self._person)
        return RedirectResponse(construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state),
                                status_code=302)

    # -- tokens --------------------------------------------------------------------------------------------
    async def load_authorization_code(self, client, authorization_code):
        code = self._codes.get(authorization_code)
        return code if code and code.client_id == client.client_id and code.expires_at > time.time() else None

    def _issue(self, client_id: str, resource) -> OAuthToken:
        now = int(time.time())
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self._access[access] = AccessToken(token=access, client_id=client_id, scopes=[SCOPE], expires_at=now + ACCESS_SECONDS,
                                           resource=resource, subject=self._person, claims={'sub': self._person})
        self._refresh[refresh] = RefreshToken(token=refresh, client_id=client_id, scopes=[SCOPE],
                                              expires_at=now + REFRESH_SECONDS, resource=resource, subject=self._person)
        return OAuthToken(access_token=access, expires_in=ACCESS_SECONDS, scope=SCOPE, refresh_token=refresh)

    async def exchange_authorization_code(self, client, authorization_code: AuthorizationCode):
        if self._codes.pop(authorization_code.code, None) is None:      # single use
            raise TokenError('invalid_grant', 'authorization code already used')
        return self._issue(client.client_id, authorization_code.resource)

    async def load_refresh_token(self, client, refresh_token):
        token = self._refresh.get(refresh_token)
        return token if token and token.client_id == client.client_id and (token.expires_at or 0) > time.time() else None

    async def exchange_refresh_token(self, client, refresh_token: RefreshToken, scopes):
        self._refresh.pop(refresh_token.token, None)                    # rotate
        return self._issue(client.client_id, refresh_token.resource)

    async def load_access_token(self, token):
        found = self._access.get(token)
        return found if found and (found.expires_at or 0) > time.time() else None

    async def revoke_token(self, token) -> None:
        self._access.pop(getattr(token, 'token', ''), None)
        self._refresh.pop(getattr(token, 'token', ''), None)
