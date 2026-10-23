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


@contextmanager
def registry():
    root = ensure_dir(users.base_dir() / 'agent-api')
    path = root / 'identities.sqlite'
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE IF NOT EXISTS identities(subject TEXT PRIMARY KEY,person TEXT UNIQUE NOT NULL, '
                 'chat_key TEXT UNIQUE NOT NULL,human_key TEXT UNIQUE NOT NULL)')
    try:
        yield conn
    finally:
        conn.close()


def credentials():
    if not os.environ.get('JOBWATCH_LIBRECHAT_IDENTITY_KEY'):
        return {}
    from pipeline.agentic.api import Principal
    with registry() as conn:
        rows = conn.execute('SELECT person,chat_key,human_key FROM identities').fetchall()
    result = {}
    for row in rows:
        result[row['chat_key']] = Principal(row['person'])
        result[row['human_key']] = Principal(row['person'], frozenset({'read', 'interact', 'approve'}))
    return result


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

    @app.post('/api/agent/librechat/enroll')
    def enroll(body: Enrollment, authorization: str | None = Header(default=None)):
        if not hmac.compare_digest(authorization or '', 'Bearer ' + secret):
            raise HTTPException(401, 'authentication_required')
        with registry() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM identities WHERE subject=?', (body.subject,)).fetchone()
            if row is None:
                owner = body.subject == owner_subject
                person = users.DEFAULT_USER if owner else 'lc-' + hashlib.sha256(body.subject.encode()).hexdigest()[:24]
                chat, human = (owner_run[0], owner_human[0]) if owner else (secrets.token_urlsafe(40), secrets.token_urlsafe(40))
                conn.execute('INSERT INTO identities VALUES(?,?,?,?)', (body.subject, person, chat, human))
                row = dict(person=person, chat_key=chat, human_key=human)
            # Finish initialization before publishing credentials, also on a retried enrollment.
            users.create_user_dirs(row['person'])
            conn.commit()
            return {key: row[key] for key in ('person', 'chat_key', 'human_key')}
