"""Human chat responses to native questions and an exact profile review.

Only the authenticated frontend server may use this adapter. Model-facing tokens,
assistant text and generated interfaces never carry its response authority.
"""
from __future__ import annotations

import json
import re

from jobwatch import users
from pipeline.agentic.api_store import fingerprint


def tables(store):
    store.conn.execute('CREATE TABLE IF NOT EXISTS client_chat_reviews('
        'client_id TEXT NOT NULL, interaction_id TEXT NOT NULL REFERENCES api_interactions(id), '
        'content_hash TEXT NOT NULL, response_key TEXT UNIQUE, resume_run TEXT, '
        'PRIMARY KEY(client_id,interaction_id,content_hash))')


def pending(run):
    return [item for item in run['interactions'] if not item['answered']]


def prompt(run):
    """Render frozen backend data, rather than letting the model describe the approval."""
    items = pending(run)
    if len(items) != 1:
        return None
    item = items[0]
    if item['type'] == 'question':
        return item['question']
    if item.get('operation') != 'profile_confirm':
        return None
    subject = item.get('binding', {}).get('subject')
    if not subject:
        return None
    lines = ['Review your profile (draft revision ' + str(subject['revision']) + '):', '']
    for fact in subject['facts']:
        value = json.dumps(fact['value'], ensure_ascii=False) if not isinstance(fact['value'], str) else fact['value']
        lines.append('- ' + fact['section'].replace('_', ' ') + ': ' + value + ' (' + fact['basis'] + ')')
    if subject['questions']:
        lines += ['', 'Still unknown:'] + ['- ' + q['text'] for q in subject['questions']]
    scope = subject['scope']
    lines += ['', 'Search scope:', '- Work: ' + '; '.join(scope['basis']),
        '- Locations: ' + ('; '.join(scope['locations']) or 'Not specified'),
        '- Daily limits: ' + str(scope['daily_assessments']) + ' assessments; ' + str(scope['daily_token_ceiling']) + ' tokens.',
        '', 'Job titles are derived from your confirmed CV, skills and preferences. Your chat sentences are not typed into job boards as search terms. The choices are checked each run and recalculated when the confirmed profile changes. Changes to your profile need your confirmation; applications and employer messages are not authorised.',
        'Confirming saves this profile and enables discovery and assessment within this scope.',
        'It does not approve application documents, employer messages or final Submit.',
        '', 'Do you confirm this profile and search scope? Reply yes to confirm, no to decline, or tell me what to change.']
    return '\n'.join(lines)


def remember(store, conversation, run, content):
    if prompt(run) is None:
        return
    tables(store)
    with store.conn:
        store.conn.execute('INSERT OR IGNORE INTO client_chat_reviews(client_id,interaction_id,content_hash) VALUES(?,?,?)',
            (conversation, pending(run)[0]['id'], fingerprint(content)))


def respond(store, person, conversation, run, body, message, key, config):
    """Resolve one human reply only against the review this conversation received."""
    items = pending(run)
    legacy_answers = items and all(i.get('operation') in ('profile_answer', 'profile_correct') for i in items)
    legacy_confirmation = len(items) == 1 and items[0].get('operation') == 'profile_confirm' and not items[0].get('binding', {}).get('subject')
    if legacy_answers or legacy_confirmation:
        # Rejection grants no authority. Deliver the current human message in that
        # same resume, so recovery cannot finish/interrupt before hearing it.
        for item in items:
            resume, _ = store.respond(item['id'], {'decision': 'reject', 'answer': None}, message=message)
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
    extra_message = None
    if item['type'] == 'question':
        if len(message) > 4000:
            return None
        response = {'decision': 'answer', 'answer': message}
    elif item.get('operation') == 'profile_confirm' and item.get('binding', {}).get('subject'):
        words = re.sub(r'[^\w\s]', ' ', message.casefold())
        words = ' '.join(words.split())
        yes = '?' not in message and words in ('yes', 'yes please', 'confirm', 'i confirm', 'confirm my profile',
            'yes confirm', 'yes confirm my profile', 'yes i confirm', 'yes that is correct', 'yes that s correct')
        no = words in ('no', 'no thanks', 'do not confirm', 'don t confirm', 'reject', 'decline')
        if yes:
            from pipeline.agentic.chat import _approval_binding
            from pipeline.agentic.contracts import AgenticError
            try:
                with users.use(person):
                    yes = item['binding'] == _approval_binding('profile_confirm', item['binding']['arguments'], config)
            except AgenticError:
                yes = False
        response = {'decision': 'approve' if yes else 'reject', 'answer': None}
        if not yes and not no:
            extra_message = message
    else:
        return None
    resume, _ = store.respond(item['id'], response, message=extra_message)
    _remember_response(store, conversation, item['id'], previous.content, key, resume)
    return store.public_run(resume)


def _remember_response(store, conversation, interaction, content, key, resume):
    with store.conn:
        store.conn.execute('INSERT INTO client_chat_reviews(client_id,interaction_id,content_hash,response_key,resume_run) '
            'VALUES(?,?,?,?,?) ON CONFLICT(client_id,interaction_id,content_hash) '
            'DO UPDATE SET response_key=excluded.response_key,resume_run=excluded.resume_run',
            (conversation, interaction, fingerprint(content), key, resume))
