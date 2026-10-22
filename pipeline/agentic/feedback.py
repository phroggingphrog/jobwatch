"""Append-only human feedback, distinct from eligibility and preference training.

Identity always comes from ``users.current()``. Domain writers may append other
human events inside their own transaction; rejection and restoration own theirs.
Nothing here builds schemas, calls models, changes profile facts or records picks.
"""
from __future__ import annotations

import json
from typing import Literal

from jobwatch import db, users
from jobwatch.candidate.contracts import StrictFrozen, digest

REASONS_VERSION = 'rejection-reasons-v1'


class Reason(StrictFrozen):
    code: str
    label: str
    meaning: Literal['preference', 'eligibility', 'data_quality', 'neutral', 'unspecified']
    rule_kind: Literal['family', 'employer', 'location', 'work_type'] | None = None
    text_required: bool = False


REJECTION_REASONS = {
    reason.code: reason for reason in (
        Reason(code='not_this_kind_of_work', label='Not this kind of work', meaning='preference', rule_kind='family'),
        Reason(code='not_this_employer', label='Not this employer', meaning='preference', rule_kind='employer'),
        Reason(code='location_unsuitable', label='Location unsuitable', meaning='preference', rule_kind='location'),
        Reason(code='hours_or_work_type', label='Hours or work type', meaning='preference', rule_kind='work_type'),
        Reason(code='pay_too_low', label='Pay too low', meaning='preference'),
        Reason(code='level_too_high', label='Level too high', meaning='preference'),
        Reason(code='level_too_low', label='Level too low', meaning='preference'),
        Reason(code='seems_ineligible_for_me', label='Seems ineligible for me', meaning='eligibility'),
        Reason(code='duplicate_or_already_seen', label='Duplicate or already seen', meaning='neutral'),
        Reason(code='ad_looks_wrong', label='Ad looks wrong', meaning='data_quality'),
        Reason(code='other', label='Other', meaning='unspecified', text_required=True),
    )
}
STATUS = {
    'person_required': 403, 'invalid_reason': 422, 'reason_text_required': 422,
    'invalid_request': 422, 'posting_not_shortlisted': 404, 'feedback_conflict': 409,
    'entry_changed': 409, 'rejection_stale': 409,
    'transaction_active': 409, 'transaction_required': 409,
}
CODES = frozenset(STATUS)
_KINDS = frozenset(('reject', 'restore', 'select', 'exclude', 'comparison', 'answer'))


class FeedbackError(ValueError):
    """A fixed public code; human text and private inputs never enter errors."""

    def __init__(self, code):
        if code not in CODES:
            raise ValueError('invalid_feedback_error')
        self.code = code
        super().__init__(code)


def _text(value, *, optional=False, maximum=None):
    if optional and value is None:
        return
    if (type(value) is not str or not value.strip()
            or (maximum is not None and len(value) > maximum)):
        raise FeedbackError('invalid_request')


def _positive_id(value, *, optional=False):
    if optional and value is None:
        return
    if type(value) is not int or value <= 0 or value > 2**63 - 1:
        raise FeedbackError('invalid_request')


def _common(*, kind, request_id, actor, source, posting_id, reason_code, reason_text):
    if actor != 'person' or type(actor) is not str:
        raise FeedbackError('person_required')
    if type(kind) is not str or kind not in _KINDS:
        raise FeedbackError('invalid_request')
    if type(source) is not str or source not in ('api', 'chat'):
        raise FeedbackError('invalid_request')
    _text(request_id, maximum=128)
    _positive_id(posting_id, optional=True)
    if type(reason_text) is not str or len(reason_text) > 2000:
        raise FeedbackError('invalid_request')
    # Validate types before dictionary lookup to avoid leaking untyped exceptions.
    if reason_code is not None and type(reason_code) is not str:
        raise FeedbackError('invalid_reason')


def _reason(reason_code, reason_text, *, required=False):
    if reason_code is None and not required:
        return None
    if reason_code not in REJECTION_REASONS:
        raise FeedbackError('invalid_reason')
    reason = REJECTION_REASONS[reason_code]
    if reason.text_required and not reason_text.strip():
        raise FeedbackError('reason_text_required')
    return reason


def _json_value(value):
    """Only portable JSON, without coercing keys or silently accepting NaN."""
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        import math
        if math.isfinite(value):
            return
    elif type(value) is list:
        for item in value:
            _json_value(item)
        return
    elif type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _json_value(item)
        return
    raise FeedbackError('invalid_request')


def _event(row, cursor):
    if row is None:
        return None
    value = dict(zip((column[0] for column in cursor.description), row))
    value['detail'] = json.loads(value.pop('detail_json'))
    return value


def _prior(conn, request_id):
    cursor = conn.execute('SELECT * FROM feedback_events WHERE person=? AND request_id=?',
                          (users.current(), request_id))
    return _event(cursor.fetchone(), cursor)


def _retry(conn, request_id, input_hash):
    previous = _prior(conn, request_id)
    if previous is not None and previous['input_hash'] != input_hash:
        raise FeedbackError('feedback_conflict')
    return previous


def append_event(conn, *, kind, request_id, actor, source='api', posting_id=None,
                 entry_id=None, run_key=None, profile_version=None, reason_code=None,
                 reason_text='', prompt_id=None, detail=None, input_hash=None) -> dict:
    """Append within the caller's transaction, or replay its identical event.

    The calling domain validates its subject and exact human approval. An explicit
    ``input_hash`` binds that domain's canonical request; otherwise the full event
    payload provides the idempotency binding. This helper never commits or rolls
    back the caller's transaction, including validation and conflict failures.
    """
    _common(kind=kind, request_id=request_id, actor=actor, source=source,
            posting_id=posting_id, reason_code=reason_code, reason_text=reason_text)
    for value in (entry_id, run_key, prompt_id):
        _text(value, optional=True)
    _positive_id(profile_version, optional=True)
    reason = _reason(reason_code, reason_text, required=kind == 'reject')
    if detail is None:
        detail = {}
    if type(detail) is not dict:
        raise FeedbackError('invalid_request')
    try:
        _json_value(detail)
        detail_json = json.dumps(detail, sort_keys=True, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise FeedbackError('invalid_request') from exc
    payload = dict(person=users.current(), kind=kind, request_id=request_id, actor=actor,
        source=source, posting_id=posting_id, entry_id=entry_id, run_key=run_key,
        profile_version=profile_version, reason_code=reason_code, reason_text=reason_text,
        prompt_id=prompt_id, detail=detail, meaning=reason.meaning if reason else None,
        reasons_version=REASONS_VERSION)
    if input_hash is None:
        input_hash = digest(payload)
    elif (type(input_hash) is not str or len(input_hash) != 64
          or any(c not in '0123456789abcdef' for c in input_hash)):
        raise FeedbackError('invalid_request')
    if not conn.in_transaction:
        raise FeedbackError('transaction_required')
    previous = _retry(conn, request_id, input_hash)
    if previous is not None:
        return previous
    conn.execute(
        'INSERT INTO feedback_events(person,posting_id,entry_id,kind,reason_code,reason_text,'
        'meaning,reasons_version,actor,source,run_key,profile_version,request_id,prompt_id,'
        'detail_json,input_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (users.current(), posting_id, entry_id, kind, reason_code, reason_text,
         reason.meaning if reason else None, REASONS_VERSION, actor, source, run_key,
         profile_version, request_id, prompt_id, detail_json, input_hash, db.ts()))
    return _prior(conn, request_id)


def _latest_dismissal(conn, posting_id):
    cursor = conn.execute(
        "SELECT * FROM feedback_events WHERE person=? AND posting_id=? "
        "AND kind IN ('reject','restore') ORDER BY id DESC LIMIT 1",
        (users.current(), posting_id))
    return _event(cursor.fetchone(), cursor)


def record_feedback(conn, config, *, posting_id, kind, request_id, actor, source='api',
                    expected_entry_id=None, reason_code=None, reason_text='',
                    expected_rejection_id=None) -> dict:
    """Reject a current entry, or restore its latest active rejection.

    Exact request replays return the original event before checking current
    freshness. They never repeat a state transition. Restoring releases only a
    posting dismissal; it cannot revive an old snapshot or override eligibility.
    """
    _common(kind=kind, request_id=request_id, actor=actor, source=source,
            posting_id=posting_id, reason_code=reason_code, reason_text=reason_text)
    _positive_id(posting_id)
    if kind == 'reject':
        _text(expected_entry_id)
        if expected_rejection_id is not None:
            raise FeedbackError('invalid_request')
    elif kind == 'restore':
        _positive_id(expected_rejection_id)
        if expected_entry_id is not None or reason_code is not None or reason_text:
            raise FeedbackError('invalid_request')
    else:
        raise FeedbackError('invalid_request')
    input_hash = digest(dict(person=users.current(), posting_id=posting_id, kind=kind,
        request_id=request_id, actor=actor, source=source, expected_entry_id=expected_entry_id,
        reason_code=reason_code, reason_text=reason_text, expected_rejection_id=expected_rejection_id))
    if conn.in_transaction:
        raise FeedbackError('transaction_active')
    conn.execute('BEGIN IMMEDIATE')
    try:
        previous = _retry(conn, request_id, input_hash)
        if previous is not None:
            conn.rollback()
            return previous
        if kind == 'reject':
            _reason(reason_code, reason_text, required=True)
            from pipeline.agentic import shortlist
            entry = shortlist.load_entry(conn, posting_id, config=config)
            if entry is None:
                raise FeedbackError('posting_not_shortlisted')
            if entry.entry_id != expected_entry_id:
                raise FeedbackError('entry_changed')
            current = _latest_dismissal(conn, posting_id)
            if current and current['kind'] == 'reject':
                raise FeedbackError('rejection_stale')
            provenance = dict(entry_id=entry.entry_id, run_key=entry.run_key,
                              profile_version=entry.profile_version)
            detail = {}
        else:
            current = _latest_dismissal(conn, posting_id)
            if not current or current['kind'] != 'reject' or current['id'] != expected_rejection_id:
                raise FeedbackError('rejection_stale')
            provenance = {key: current[key] for key in ('entry_id', 'run_key', 'profile_version')}
            detail = {'rejection_event_id': current['id']}
        event = append_event(conn, kind=kind, request_id=request_id, actor=actor,
            source=source, posting_id=posting_id, reason_code=reason_code, reason_text=reason_text,
            detail=detail, input_hash=input_hash, **provenance)
        conn.commit()
        return event
    except BaseException:
        conn.rollback()
        raise


def _has_events(conn):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='feedback_events'").fetchone() is not None


def _dismissals(conn):
    if not _has_events(conn):
        return []
    # Latest lifecycle row for each posting, always constrained to this person.
    return [tuple(row) for row in conn.execute(
        "SELECT posting_id,id,kind FROM feedback_events WHERE person=? AND id IN ("
        "SELECT MAX(id) FROM feedback_events WHERE person=? AND posting_id IS NOT NULL "
        "AND kind IN ('reject','restore') GROUP BY posting_id) ORDER BY posting_id",
        (users.current(), users.current()))]


def rejected_posting_ids(conn) -> set[int]:
    return {posting_id for posting_id, _, kind in _dismissals(conn) if kind == 'reject'}


def dismissal_state_hash(conn) -> str:
    """Fence lifecycle changes, including restores, so historic snapshots stay old."""
    return digest(_dismissals(conn))


def list_events(conn, *, limit=100) -> list[dict]:
    if type(limit) is not int or not 1 <= limit <= 200:
        raise FeedbackError('invalid_request')
    if not _has_events(conn):
        return []
    cursor = conn.execute('SELECT * FROM feedback_events WHERE person=? ORDER BY id DESC LIMIT ?',
                          (users.current(), limit))
    return [_event(row, cursor) for row in cursor.fetchall()]
