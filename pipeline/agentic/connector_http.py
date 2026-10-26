"""Loopback JSON front for the ChatGPT connector logic, so a thin MCP server (mcp-app/, TypeScript) can call it.

All safety logic stays in chatgpt_connector (digest check, single-use approvals, per-person data). This module only
authenticates one bearer token, binds it to one configured person (never an argument) and maps errors to fixed codes.
Run: JOBWATCH_CONNECTOR_TOKEN=... python -m pipeline.agentic.connector_http --port 18940
"""
from __future__ import annotations

import hmac
import os

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jobwatch import users
from pipeline.agentic import chatgpt_connector as cc
from pipeline.agentic.runtime import RuntimeErrorSafe


class Prepare(BaseModel):
    instructions: str = Field('', max_length=4000)


class Revise(BaseModel):
    changes: str = Field(max_length=4000)


class Decide(BaseModel):
    interaction_id: str = Field(max_length=100)
    decision: str
    binding: str = Field(max_length=200)


class ChatStart(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str = Field(max_length=16000)


class ChatContinue(BaseModel):
    model_config = ConfigDict(extra='forbid')
    thread_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    message: str = Field(max_length=16000)


class Submit(BaseModel):
    confirm_digest: str = Field(max_length=200)
    shown_hash: str = Field(max_length=200)


def create_app(*, token: str | None = None, person: str | None = None) -> FastAPI:
    token = token if token is not None else os.environ.get('JOBWATCH_CONNECTOR_TOKEN')
    person = person if person is not None else os.environ.get('JOBWATCH_MCP_PERSON', users.DEFAULT_USER)
    if not token or len(token) < 32 or not users.valid_name(person):
        raise RuntimeErrorSafe('connector_configuration_required')

    def authed(authorization: str = Header('')) -> str:
        given = authorization[7:] if authorization.startswith('Bearer ') else ''
        if not hmac.compare_digest(given.encode(), token.encode()):
            raise HTTPException(401, 'authentication_required')
        return person

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(RuntimeErrorSafe)
    async def _safe(_, exc: RuntimeErrorSafe):
        return JSONResponse({'error': str(exc)}, status_code=400)

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

    @app.post('/connector/chat/start')
    def chat_start(body: ChatStart, who: str = Depends(authed)):
        return cc.chat_turn(who, None, body.message)

    @app.post('/connector/chat/continue')
    def chat_continue(body: ChatContinue, who: str = Depends(authed)):
        return cc.chat_turn(who, body.thread_id, body.message)

    return app


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
