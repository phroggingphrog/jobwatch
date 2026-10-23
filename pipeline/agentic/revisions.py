"""Per-application human revision requests; never candidate evidence or profile facts."""
from __future__ import annotations

import hashlib
import json
from jobwatch import users
from jobwatch.apply.paths import ensure_dir, safe_write_text
from pipeline.agentic.runtime import RuntimeErrorSafe


def _path(posting_id):
    if type(posting_id) is not int or not 0 < posting_id < 2**63:
        raise RuntimeErrorSafe('invalid_posting')
    return users.user_dir() / 'agent-api' / 'revisions' / (str(posting_id)+'.json')


def current(posting_id):
    path = _path(posting_id)
    if not path.exists():
        return None
    value = json.loads(path.read_text())
    if set(value) != {'instructions','approval'} or not isinstance(value['instructions'],str) or not 1 <= len(value['instructions']) <= 4000:
        raise RuntimeErrorSafe('revision_invalid')
    return value


def record(posting_id, instructions, approval):
    if not isinstance(instructions,str) or not instructions.strip() or len(instructions)>4000:
        raise RuntimeErrorSafe('revision_invalid')
    path = _path(posting_id)
    ensure_dir(path.parent)
    safe_write_text(path,json.dumps({'instructions':instructions,'approval':approval},sort_keys=True))


def fingerprint(posting_id):
    value=current(posting_id)
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest() if value else None
