"""Authenticated loopback operations for the TypeScript MCP server.

Onboarding calls canonical intake functions directly; job work uses the existing
Career Ops service. Identity always comes from the configured bearer mapping.
Run: JOBWATCH_CONNECTOR_TOKEN=... python -m pipeline.agentic.connector_http --port 18940
"""
from __future__ import annotations

import hmac
import os
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from jobwatch import users
from jobwatch.candidate import intake
from jobwatch.candidate.contracts import CandidateError
from pipeline.agentic import chatgpt_connector as cc
from pipeline.agentic import connector_onboarding as onboarding
from pipeline.agentic.profile_api import STATUS as INTAKE_STATUS
from pipeline.agentic.runtime import RuntimeErrorSafe


class Prepare(BaseModel):
    instructions: str = Field('', max_length=4000)


class Revise(BaseModel):
    changes: str = Field(max_length=4000)


class Decide(BaseModel):
    interaction_id: str = Field(max_length=100)
    decision: str
    binding: str = Field(max_length=200)


class OnboardingBody(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class OnboardingStart(OnboardingBody):
    upload_ids: list[str] = Field(min_length=1, max_length=20)
    base_version: int | None = Field(default=None, ge=1)


class OnboardingProposal(OnboardingBody):
    proposal_id: str = Field(pattern=r'^[0-9a-f]{16}$')


class AddFact(OnboardingBody):
    op: Literal['add']
    section: str = Field(min_length=1, max_length=64)
    value: JsonValue


class SetFact(OnboardingBody):
    op: Literal['set']
    fact_id: str = Field(min_length=1, max_length=64)
    basis: Literal['evidence'] = 'evidence'
    value: JsonValue


class RemoveFact(OnboardingBody):
    op: Literal['remove']
    fact_id: str = Field(min_length=1, max_length=64)


class OnboardingUpdate(OnboardingProposal):
    expected_revision: int = Field(ge=1)
    edits: list[Annotated[AddFact | SetFact | RemoveFact, Field(discriminator='op')]] = Field(min_length=1, max_length=100)


class OnboardingAnswer(OnboardingProposal):
    expected_revision: int = Field(ge=1)
    question_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=4000)


class OnboardingConfirm(OnboardingProposal):
    proposal_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    scope_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    confirmed: Literal[True]

    @field_validator('confirmed', mode='before')
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError('confirmed must be true')
        return value


class Submit(BaseModel):
    confirm_digest: str = Field(max_length=200)
    shown_hash: str = Field(max_length=200)


class Verify(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: str


def _oauth_state_path() -> Path:
    """Where issued tokens and clients persist (0600, hashed tokens): next to the person's settings, not in the repo."""
    given = os.environ.get('JOBWATCH_CONNECTOR_OAUTH_STATE')
    if given:
        return Path(given).expanduser()
    return Path(os.environ.get('JOBWATCH_CONFIG_DIR') or '~/.config/jobwatch').expanduser() / 'connector-oauth.json'


def _public_origin(url: str | None) -> str | None:
    """The public origin of the TypeScript server (https; plain http only for a loopback test). None when unusable."""
    parsed = urlparse(url or '')
    local = parsed.hostname in ('127.0.0.1', 'localhost', '::1')
    if (parsed.scheme not in ('https', 'http') or (parsed.scheme == 'http' and not local) or not parsed.netloc
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username):
        return None
    return f'{parsed.scheme}://{parsed.netloc}'


def create_app(*, token: str | None = None, person: str | None = None, oauth: bool | None = None,
               public_url: str | None = None, passphrase: str | None = None,
               oauth_state: str | Path | None = None) -> FastAPI:
    token = token if token is not None else os.environ.get('JOBWATCH_CONNECTOR_TOKEN')
    person = person if person is not None else os.environ.get('JOBWATCH_MCP_PERSON', users.DEFAULT_USER)
    if not token or len(token) < 32 or not users.valid_name(person):
        raise RuntimeErrorSafe('connector_configuration_required')
    # OAuth login is OFF unless JOBWATCH_CONNECTOR_OAUTH=1 (or oauth=True) and it is fully configured: a public URL (the
    # TypeScript server's origin) and a passphrase of 16+ characters. Half-configured refuses to start.
    oauth = oauth if oauth is not None else os.environ.get('JOBWATCH_CONNECTOR_OAUTH') == '1'
    provider = None
    if oauth:
        origin = _public_origin(public_url if public_url is not None else os.environ.get('JOBWATCH_MCP_PUBLIC_URL'))
        phrase = passphrase if passphrase is not None else os.environ.get('JOBWATCH_MCP_OAUTH_PASSPHRASE')
        if not origin or not phrase or len(phrase) < 16:
            raise RuntimeErrorSafe('connector_oauth_configuration_required')
        from pipeline.agentic.mcp_oauth import JobwatchOAuth
        provider = JobwatchOAuth(base_url=origin, person=person, passphrase=phrase,
                                 state_path=oauth_state if oauth_state is not None else _oauth_state_path())

    def authed(authorization: str = Header('')) -> str:
        given = authorization[7:] if authorization.startswith('Bearer ') else ''
        if not hmac.compare_digest(given.encode(), token.encode()):
            raise HTTPException(401, 'authentication_required')
        return person

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(RuntimeErrorSafe)
    async def _safe(_, exc: RuntimeErrorSafe):
        return JSONResponse({'error': str(exc)}, status_code=400)

    @app.exception_handler(intake.IntakeError)
    async def _intake_failed(_, exc):
        return JSONResponse({'error': exc.code}, status_code=INTAKE_STATUS.get(exc.code, 400))

    @app.exception_handler(CandidateError)
    async def _candidate_failed(_, exc):
        return JSONResponse({'error': 'profile_invalid'}, status_code=409)

    @app.get('/connector/overview')
    def overview(limit: int = 50, who: str = Depends(authed)):
        return cc.overview(who, limit)

    @app.get('/connector/jobs/{posting_id}')
    def job(posting_id: int, who: str = Depends(authed)):
        return {'job': cc.detail(who, posting_id)}

    @app.get('/connector/jobs/{posting_id}/review')
    def review(posting_id: int, who: str = Depends(authed)):
        # The digest is a separate field: the TypeScript front puts it in view-only _meta, never in model-visible content.
        data, digest = cc.review(who, posting_id)
        return {'review': data, 'submit_digest': digest}

    @app.get('/connector/jobs/{posting_id}/status')
    def status(posting_id: int, who: str = Depends(authed)):
        return cc.status(who, posting_id)

    @app.post('/connector/jobs/{posting_id}/prepare')
    def prepare(posting_id: int, body: Prepare, who: str = Depends(authed)):
        message = f'Prepare the application for posting {posting_id}.' + (
            f' Instructions: {body.instructions}' if body.instructions else '')
        data, meta = cc._hand_off(who, posting_id, message)
        return {'data': data, 'meta': meta}

    @app.post('/connector/jobs/{posting_id}/revise')
    def revise(posting_id: int, body: Revise, who: str = Depends(authed)):
        if not body.changes.strip():
            raise RuntimeErrorSafe('invalid_request')
        data, meta = cc._hand_off(who, posting_id, f'Revise the application for posting {posting_id}. Changes: {body.changes}')
        return {'data': data, 'meta': meta}

    @app.post('/connector/decide')
    def decide(body: Decide, who: str = Depends(authed)):
        data, meta = cc.decide(who, body.interaction_id, body.decision, body.binding)
        return {'data': data, 'meta': meta}

    @app.post('/connector/jobs/{posting_id}/submit')
    def submit(posting_id: int, body: Submit, who: str = Depends(authed)):
        return cc.submit_reviewed(who, posting_id, body.confirm_digest, body.shown_hash)

    @app.get('/connector/onboarding/status')
    def onboarding_status(who: str = Depends(authed)):
        return onboarding.status(who)

    @app.post('/connector/onboarding/start')
    def onboarding_start(body: OnboardingStart, who: str = Depends(authed)):
        return onboarding.start(who, body.upload_ids, body.base_version)

    @app.post('/connector/onboarding/update')
    def onboarding_update(body: OnboardingUpdate, who: str = Depends(authed)):
        return onboarding.update(who, body.proposal_id, body.expected_revision,
                                 [edit.model_dump() for edit in body.edits])

    @app.post('/connector/onboarding/answer')
    def onboarding_answer(body: OnboardingAnswer, who: str = Depends(authed)):
        return onboarding.answer(who, body.proposal_id, body.expected_revision, body.question_id, body.text)

    @app.post('/connector/onboarding/review')
    def onboarding_review(body: OnboardingProposal, who: str = Depends(authed)):
        return onboarding.review(who, body.proposal_id)

    @app.post('/connector/onboarding/confirm')
    def onboarding_confirm(body: OnboardingConfirm, who: str = Depends(authed)):
        return onboarding.confirm(who, body.proposal_id, body.proposal_digest, body.scope_digest)

    if provider is not None:
        _mount_oauth(app, provider, token, person)

    return app


def _mount_oauth(app: FastAPI, provider, connector_token: str, person: str) -> None:
    """OAuth authorization-server routes (metadata, /authorize, /token, /register, /revoke, consent page) plus the
    verify call the TypeScript server makes for each bearer. The TypeScript server proxies the public paths here."""
    from starlette.requests import Request
    from starlette.responses import JSONResponse as Json
    from starlette.routing import Route

    origin = str(provider.base_url).rstrip('/')
    routes = provider.get_routes(mcp_path='/mcp')

    async def consent(request: Request):
        return await provider.consent(request)

    async def resource_metadata(_: Request):
        return Json({'resource': origin + '/mcp', 'authorization_servers': [origin], 'scopes_supported': ['jobwatch'],
                     'bearer_methods_supported': ['header']})

    class PublicClientRevoke:
        """The SDK's /revoke insists on a client_secret key even for public (PKCE, no secret) clients, which is what
        ChatGPT registers as. A urlencoded request without the key gets an empty one; nothing else changes."""

        def __init__(self, inner):
            self.inner = inner

        async def __call__(self, scope, receive, send):
            if scope['type'] != 'http' or scope['method'] != 'POST':
                return await self.inner(scope, receive, send)
            body = b''
            while True:
                message = await receive()
                body += message.get('body', b'')
                if not message.get('more_body'):
                    break
            if b'client_secret=' not in body:
                body += (b'&' if body else b'') + b'client_secret='
            sent = False

            async def replay():
                nonlocal sent
                if sent:
                    return {'type': 'http.disconnect'}
                sent = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return await self.inner(scope, replay, send)

    def public_client_revoke(route):
        return Route(route.path, PublicClientRevoke(route.endpoint), methods=route.methods)

    routes = [public_client_revoke(r) if r.path == '/revoke' else r for r in routes]
    extra = [Route('/oauth/consent', consent, methods=['GET', 'POST']),
             Route('/.well-known/oauth-protected-resource', resource_metadata, methods=['GET'])]
    have = {r.path for r in routes}
    app.router.routes.extend([*[r for r in extra if r.path not in have], *routes])

    @app.post('/connector/oauth/verify')
    def verify(body: Verify, authorization: str = Header('')):
        given = authorization[7:] if authorization.startswith('Bearer ') else ''
        if not hmac.compare_digest(given.encode(), connector_token.encode()):
            raise HTTPException(401, 'authentication_required')
        # The static JOBWATCH_MCP_TOKEN fallback is checked by the TypeScript server itself (constant time); this answers
        # only for an OAuth access token this server issued. The person is the configured one, never the caller's choice.
        found = provider.verify(body.token)
        return found | ({'person': person} if found['valid'] else {})


def main(argv=None) -> int:
    import argparse
    import uvicorn
    parser = argparse.ArgumentParser(description='Jobwatch connector JSON front (loopback only)')
    parser.add_argument('--port', type=int, default=18940)
    args = parser.parse_args(argv)
    uvicorn.run(create_app(), host='127.0.0.1', port=args.port, log_level='warning')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
