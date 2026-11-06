"""Private, idempotent account enrollment by the trusted LibreChat backend only."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
import os
import re
import secrets
import sqlite3

from fastapi import Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from jobwatch import users
from jobwatch.apply.paths import ensure_dir
from pipeline.agentic.private_sqlite import connect as private_connect


@contextmanager
def registry():
    root = ensure_dir(users.base_dir() / 'agent-api')
    path = root / 'identities.sqlite'
    conn = private_connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE IF NOT EXISTS identities(subject TEXT PRIMARY KEY,person TEXT UNIQUE NOT NULL, '
                 'chat_key TEXT UNIQUE NOT NULL,human_key TEXT UNIQUE NOT NULL)')
    try:
        yield conn
    finally:
        conn.close()


def credentials():
    return {}  # the owner's token follows the deployment credentials; nobody else is enrolled


class Enrollment(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    subject: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9._:@-]*$')


def mount(app, base_credentials):
    secret = os.environ.get('JOBWATCH_LIBRECHAT_IDENTITY_KEY', '')
    if not secret:
        return
    owner_subject = os.environ.get('JOBWATCH_LIBRECHAT_OWNER_SUBJECT', '')
    if len(secret) < 32 or not owner_subject:
        raise ValueError('librechat_identity_configuration_required')
    owner_run = [key for key,p in base_credentials.items() if p.person == users.DEFAULT_USER and 'run' in p.scopes]
    owner_human = [key for key,p in base_credentials.items() if p.person == users.DEFAULT_USER and 'approve' in p.scopes]
    if len(owner_run) != 1 or len(owner_human) != 1:
        raise ValueError('librechat_owner_credentials_required')

    def resolve(subject, authorization):
        if not hmac.compare_digest(authorization or '', 'Bearer ' + secret):
            raise HTTPException(401, 'authentication_required')
        try:
            subject = Enrollment(subject=subject).subject
        except ValueError:
            raise HTTPException(401, 'authentication_required') from None
        if subject != owner_subject:
            raise HTTPException(401, 'authentication_required')   # one owner: no other subject is enrolled
        return dict(person=users.DEFAULT_USER, chat_key=owner_run[0], human_key=owner_human[0])

    @app.post('/api/agent/librechat/enroll')
    def enroll(body: Enrollment, authorization: str | None = Header(default=None)):
        return resolve(body.subject, authorization)

    def client_principal(authorization, subject):
        # Configuration supplies the stable authenticated subject and server secret.
        # This resolver exports no credentials or scopes. The chat adapter separately
        # accepts human replies only from this authenticated frontend-server channel.
        from pipeline.agentic.api import Principal
        return Principal(resolve(subject, authorization)['person'])

    return client_principal
