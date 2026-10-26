"""Optional OAuth 2.1 for the Jobwatch MCP server (authorization code + PKCE S256, dynamic client registration).

Off by default (JOBWATCH_MCP_OAUTH=1 turns it on; the loopback connector front has its own switch,
JOBWATCH_CONNECTOR_OAUTH=1). ChatGPT connectors support OAuth or no auth, not a static bearer token. One
passphrase-gated consent page maps whoever completes it to the one configured Jobwatch person; the bearer verifier keeps
working beside it. Without `state_path` state is in memory (a restart makes ChatGPT sign in again). With it, clients and
issued tokens persist in a 0600 file; tokens are stored only as sha256 hashes, so the file alone cannot be used to call
anything. Never serve this on a public URL without the owner's decision; this module opens nothing by itself.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import secrets
import stat
import tempfile
import time
from pathlib import Path
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
# Wrong passphrases across ALL sign-in attempts (a new transaction must not reset the guessing budget).
GLOBAL_FAILURES, GLOBAL_WINDOW = 20, 600


def _h(token: str) -> str:
    return hashlib.sha256(('jobwatch-oauth-token\0' + str(token)).encode()).hexdigest()


class JobwatchOAuth(OAuthProvider):
    def __init__(self, *, base_url: str, person: str, passphrase: str, state_path: str | Path | None = None):
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
        # Tokens are keyed by the hash of the token, never the token itself.
        self._access: dict[str, AccessToken] = {}
        self._refresh: dict[str, RefreshToken] = {}
        self._pair: dict[str, str] = {}              # access hash <-> refresh hash: revoking one revokes both
        self._failures: list[float] = []
        self._state = Path(state_path) if state_path else None
        if self._state is not None:
            self._load()

    # -- persistence (optional) ------------------------------------------------------------------------------
    def _load(self) -> None:
        """Read the state file if it is a private regular file of ours and parses; otherwise start empty (a damaged or
        loose file is never trusted, and never blocks startup)."""
        path = self._state
        try:
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077 or info.st_uid != os.getuid()):
                return
            data = json.loads(path.read_text())
            now = time.time()
            for cid, raw in data['clients'].items():
                self._clients[cid] = OAuthClientInformationFull.model_validate(raw)
            for key, raw in data['access'].items():
                if raw['expires_at'] > now and raw['client_id'] in self._clients:
                    self._access[key] = AccessToken(token=key, client_id=raw['client_id'], scopes=[SCOPE],
                        expires_at=int(raw['expires_at']), resource=raw.get('resource'), subject=self._person,
                        claims={'sub': self._person})
            for key, raw in data['refresh'].items():
                if raw['expires_at'] > now and raw['client_id'] in self._clients:
                    self._refresh[key] = RefreshToken(token=key, client_id=raw['client_id'], scopes=[SCOPE],
                        expires_at=int(raw['expires_at']), resource=raw.get('resource'), subject=self._person)
            self._pair = {a: r for a, r in data.get('pair', {}).items() if a in self._access and r in self._refresh}
        except Exception:                                   # noqa: BLE001 - never trust or fail on a bad file
            self._clients.clear(); self._access.clear(); self._refresh.clear(); self._pair.clear()

    def _save(self) -> None:
        if self._state is None:
            return
        now = time.time()
        self._access = {k: v for k, v in self._access.items() if (v.expires_at or 0) > now}
        self._refresh = {k: v for k, v in self._refresh.items() if (v.expires_at or 0) > now}
        self._pair = {a: r for a, r in self._pair.items() if a in self._access and r in self._refresh}
        doc = {'version': 1,
               'clients': {cid: c.model_dump(mode='json') for cid, c in self._clients.items()},
               'access': {k: {'client_id': v.client_id, 'expires_at': v.expires_at, 'resource': str(v.resource) if v.resource else None}
                          for k, v in self._access.items()},
               'refresh': {k: {'client_id': v.client_id, 'expires_at': v.expires_at, 'resource': str(v.resource) if v.resource else None}
                           for k, v in self._refresh.items()},
               'pair': self._pair}
        self._state.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self._state.parent, 0o700) if self._state.parent.stat().st_uid == os.getuid() and not self._state.parent.is_symlink() else None
        fd, tmp = tempfile.mkstemp(dir=self._state.parent, prefix='.oauth-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w') as stream:
                os.fchmod(stream.fileno(), 0o600)
                json.dump(doc, stream, sort_keys=True)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(tmp, self._state)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # -- registration and authorization --------------------------------------------------------------------
    async def get_client(self, client_id):
        return self._clients.get(client_id)

    async def register_client(self, client_info):
        self._clients[client_info.client_id] = client_info
        self._save()

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
        now = time.time()
        self._failures = [t for t in self._failures if t > now - GLOBAL_WINDOW]
        if len(self._failures) >= GLOBAL_FAILURES:
            return HTMLResponse('Too many wrong passphrases. Wait a few minutes.', status_code=429)
        entry['attempts'] += 1
        if not hmac.compare_digest(hashlib.sha256(str(form.get('passphrase') or '').encode()).digest(),
                                   hashlib.sha256(self._pass).digest()):
            self._failures.append(now)
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
        ah, rh = _h(access), _h(refresh)
        self._access[ah] = AccessToken(token=ah, client_id=client_id, scopes=[SCOPE], expires_at=now + ACCESS_SECONDS,
                                       resource=resource, subject=self._person, claims={'sub': self._person})
        self._refresh[rh] = RefreshToken(token=rh, client_id=client_id, scopes=[SCOPE],
                                         expires_at=now + REFRESH_SECONDS, resource=resource, subject=self._person)
        self._pair[ah] = rh
        self._save()
        return OAuthToken(access_token=access, expires_in=ACCESS_SECONDS, scope=SCOPE, refresh_token=refresh)

    async def exchange_authorization_code(self, client, authorization_code: AuthorizationCode):
        if self._codes.pop(authorization_code.code, None) is None:      # single use
            raise TokenError('invalid_grant', 'authorization code already used')
        return self._issue(client.client_id, authorization_code.resource)

    async def load_refresh_token(self, client, refresh_token):
        found = self._refresh.get(_h(refresh_token))
        if not found or found.client_id != client.client_id or (found.expires_at or 0) <= time.time():
            return None
        return found.model_copy(update={'token': refresh_token})      # the caller's own value, so it can be rotated out

    async def exchange_refresh_token(self, client, refresh_token: RefreshToken, scopes):
        self._drop_refresh(_h(refresh_token.token))                       # rotate
        return self._issue(client.client_id, refresh_token.resource)

    async def load_access_token(self, token):
        found = self._access.get(_h(token))
        if not found or (found.expires_at or 0) <= time.time():
            return None
        return found.model_copy(update={'token': token})

    def _drop_refresh(self, rh: str) -> None:
        self._refresh.pop(rh, None)
        for ah in [a for a, r in self._pair.items() if r == rh]:
            self._access.pop(ah, None)
            self._pair.pop(ah, None)
        self._save()

    async def revoke_token(self, token) -> None:
        value = _h(getattr(token, 'token', ''))
        if value in self._refresh:
            self._drop_refresh(value)
            return
        if value in self._access:
            rh = self._pair.pop(value, None)
            self._access.pop(value, None)
            self._refresh.pop(rh, None) if rh else None
            self._save()

    def verify(self, token: str) -> dict:
        """For the loopback connector front: is this an unexpired OAuth access token we issued, and for whom."""
        found = self._access.get(_h(token)) if isinstance(token, str) and 0 < len(token) <= 512 else None
        if not found or (found.expires_at or 0) <= time.time():
            return {'valid': False}
        return {'valid': True, 'person': self._person, 'client_id': found.client_id, 'expires_at': found.expires_at}
