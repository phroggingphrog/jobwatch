"""Private immutable ad snapshots and revisioned owner context for URL prep.

Identical URL, source, text, title, company and acquisition method reuse the
original snapshot (including its timestamp), preserving owner notes and revision.
Explicit conflicting inputs require a revisioned edit, never an implicit merge.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
import re
from uuid import uuid4

from jobwatch import ledger
from jobwatch.interview_ad import InterviewAd, MAX_AD_CHARS, ats_target
from jobwatch.interview_inputs import InterviewInputs
from jobwatch.models import canonical_url
from pipeline.agentic.contracts import AgenticError

_ACQUISITIONS = {'structured_ats', 'browser', 'unconfirmed (fetched without browser)', 'owner_supplied'}
_AD_FIELDS = {'url', 'source_url', 'title', 'company', 'text', 'acquired_at', 'acquisition'}


class _Subject(dict):
    def __repr__(self):
        return '<private interview subject>'


def _id(subject_id):
    if type(subject_id) is not str or not re.fullmatch(r'[0-9a-f]{32}', subject_id):
        raise AgenticError('interview_subject_missing')


def _inputs(value):
    if type(value) is not InterviewInputs:
        raise AgenticError('interview_inputs_invalid')
    try:
        return InterviewInputs.model_validate(value.model_dump(warnings=False))
    except (ValueError, TypeError):
        raise AgenticError('interview_inputs_invalid') from None


def _ad(value):
    try:
        if type(value) is not InterviewAd:raise ValueError
        data = asdict(value)
        if set(data) != _AD_FIELDS | {'expires_at'} or any(type(data[k]) is not str for k in _AD_FIELDS):raise ValueError
        if value.expires_at is not None:
            if type(value.expires_at) is not str or len(value.expires_at)>64:raise ValueError
            if datetime.fromisoformat(value.expires_at).utcoffset() is None:raise ValueError
        for key in ('url', 'source_url'):
            if not data[key] or any(c.isspace() for c in data[key]):raise ValueError
            ats_target(data[key])  # Shared syntactic HTTPS, credentials and port checks; no network.
        if not value.title.strip() or len(value.title)>500 or len(value.company)>500:raise ValueError
        if not 200 <= len(value.text.strip()) <= MAX_AD_CHARS or len(value.text)>MAX_AD_CHARS:raise ValueError
        if value.acquisition not in _ACQUISITIONS or len(value.acquired_at)>64:raise ValueError
        if datetime.fromisoformat(value.acquired_at).utcoffset() is None:raise ValueError
        # Reconstruct rather than trusting unchecked dataclass mutations/copies.
        return InterviewAd(**data)
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise AgenticError('interview_subject_invalid') from None


def _detail(ad, inputs):
    return json.dumps({'ad':asdict(ad), 'text_hash':ad.text_hash,
                       'inputs':inputs.model_dump(mode='json')}, ensure_ascii=False)


def load_subject(conn, subject_id):
    _id(subject_id)
    row = conn.execute('SELECT revision,detail_json FROM interview_subjects WHERE subject_id=?', (subject_id,)).fetchone()
    if row is None:raise AgenticError('interview_subject_missing')
    try:
        revision = row['revision']
        if type(revision) is not int or revision<1:raise ValueError
        if type(row['detail_json']) is not str or len(row['detail_json'])>1_000_000:raise ValueError
        detail = json.loads(row['detail_json'])
        if type(detail) is not dict or set(detail)!={'ad','text_hash','inputs'}:raise ValueError
        if type(detail['ad']) is not dict or set(detail['ad']) not in (_AD_FIELDS, _AD_FIELDS | {'expires_at'}):raise ValueError
        ad = _ad(InterviewAd(**detail['ad']))
        if type(detail['text_hash']) is not str or detail['text_hash']!=ad.text_hash:raise ValueError
        inputs = InterviewInputs.model_validate(detail['inputs'])
    except (ValueError, TypeError, AgenticError):
        raise AgenticError('interview_subject_invalid') from None
    return _Subject(subject_id=subject_id, revision=revision, ad=ad, inputs=inputs)


def create_subject(conn, ad: InterviewAd, inputs: InterviewInputs | None = None) -> str:
    ad = _ad(ad)
    explicit_inputs = inputs is not None
    inputs = _inputs(InterviewInputs() if inputs is None else inputs)
    if conn.in_transaction:raise AgenticError('transaction_already_active')
    subject_id = uuid4().hex
    conn.execute('BEGIN IMMEDIATE')
    try:
        identity = asdict(ad)
        identity.pop('acquired_at')
        identity['url'] = canonical_url(identity['url'])
        for row in conn.execute('SELECT subject_id FROM interview_subjects ORDER BY rowid'):
            existing = load_subject(conn, row['subject_id'])
            previous = asdict(existing['ad'])
            previous.pop('acquired_at')
            previous['url'] = canonical_url(previous['url'])
            if previous == identity:
                if explicit_inputs and existing['inputs'] != inputs:
                    raise AgenticError('interview_subject_inputs_conflict')
                conn.commit()
                return existing['subject_id']
        ledger.upsert(conn, 'applications', 'interview_subjects', {
            'subject_id':subject_id, 'revision':1, 'detail_json':_detail(ad, inputs)}, commit=False)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return subject_id


def save_subject_inputs(conn, subject_id, inputs, *, expected_revision):
    inputs = _inputs(inputs)
    if type(expected_revision) is not int or expected_revision<1:
        raise AgenticError('interview_inputs_invalid')
    if conn.in_transaction:raise AgenticError('transaction_already_active')
    conn.execute('BEGIN IMMEDIATE')
    try:
        subject = load_subject(conn, subject_id)
        if subject['revision']!=expected_revision:raise AgenticError('interview_inputs_changed')
        revision = expected_revision+1
        ledger.upsert(conn, 'applications', 'interview_subjects', {
            'subject_id':subject_id, 'revision':revision,
            'detail_json':_detail(subject['ad'], inputs)}, commit=False)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return inputs, revision
