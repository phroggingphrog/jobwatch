"""Human chat responses to the backend's native questions.

Only the authenticated frontend server may use this adapter. Model-facing tokens,
assistant text and generated interfaces never carry its response authority.
"""
from __future__ import annotations

from pipeline.agentic.api_store import fingerprint


def tables(store):
    store.conn.execute('CREATE TABLE IF NOT EXISTS client_chat_reviews('
        'client_id TEXT NOT NULL, interaction_id TEXT NOT NULL REFERENCES api_interactions(id), '
        'content_hash TEXT NOT NULL, response_key TEXT UNIQUE, resume_run TEXT, '
        'PRIMARY KEY(client_id,interaction_id,content_hash))')


def pending(run):
    return [item for item in run['interactions'] if not item['answered']]


def prompt(run):
    """Render the backend's question text, never model-authored approval wording."""
    items = pending(run)
    if len(items) != 1:
        return None
    item = items[0]
    if item['type'] == 'question':
        return item['question']
    return None


def remember(store, conversation, run, content):
    if prompt(run) is None:
        return
    tables(store)
    with store.conn:
        store.conn.execute('INSERT OR IGNORE INTO client_chat_reviews(client_id,interaction_id,content_hash) VALUES(?,?,?)',
            (conversation, pending(run)[0]['id'], fingerprint(content)))


def respond(store, person, conversation, run, body, message, key, config):
    """Resolve one human reply only against the question this conversation received."""
    items = pending(run)
    legacy = items and all(i.get('operation') in ('profile_answer', 'profile_correct', 'profile_confirm') for i in items)
    if legacy:
        # Historical checkpoints held profile approvals/questions. Treat the authenticated message as ordinary chat;
        # it cannot itself approve a protected operation. Retire the stale wait and resume with the exact text.
        for item in items:
            response = ({'decision': 'reject', 'answer': None} if item['type'] == 'approval'
                        else {'decision': 'answer', 'answer': message})
            resume, _ = store.respond(item['id'], response, message=message)
        _remember_response(store, conversation, items[-1]['id'], '', key, resume)
        return store.public_run(resume)
    if len(items) != 1 or len(body.messages) < 2:
        return None
    item, previous = items[0], body.messages[-2]
    if previous.role != 'assistant' or not isinstance(previous.content, str):
        return None
    offered = store.conn.execute('SELECT 1 FROM client_chat_reviews WHERE client_id=? AND interaction_id=? AND content_hash=?',
        (conversation, item['id'], fingerprint(previous.content))).fetchone()
    if not offered:
        return None
    if item['type'] == 'question':
        if len(message) > 4000:
            return None
        response = {'decision': 'answer', 'answer': message}
    else:
        return None
    resume, _ = store.respond(item['id'], response, message=None)
    _remember_response(store, conversation, item['id'], previous.content, key, resume)
    return store.public_run(resume)


def _remember_response(store, conversation, interaction, content, key, resume):
    with store.conn:
        store.conn.execute('INSERT INTO client_chat_reviews(client_id,interaction_id,content_hash,response_key,resume_run) '
            'VALUES(?,?,?,?,?) ON CONFLICT(client_id,interaction_id,content_hash) '
            'DO UPDATE SET response_key=excluded.response_key,resume_run=excluded.resume_run',
            (conversation, interaction, fingerprint(content), key, resume))
