"""Owner-supplied interview context, independent of application state."""
from __future__ import annotations

from datetime import UTC, datetime
import json

from pydantic import Field, model_validator

from jobwatch import ledger
from pipeline.agentic.contracts import AgenticError, StrictFrozen


class InterviewInputs(StrictFrozen):
    invite: str = Field(default='', max_length=20000, repr=False)
    panelist_profiles: str = Field(default='', max_length=20000, repr=False)
    story_bank: str = Field(default='', max_length=20000, repr=False)
    prior_compensation: str = Field(default='', max_length=10000, repr=False)
    coffee_chat: str = Field(default='', max_length=20000, repr=False)
    prior_round_notes: str = Field(default='', max_length=20000, repr=False)

    @model_validator(mode='after')
    def bounded(self):
        if sum(len(v) for v in self.model_dump().values())>60000:
            raise ValueError('interview_inputs_too_large')
        return self


def _posting(conn, posting_id):
    if type(posting_id) is not int or posting_id<=0 or not conn.execute(
            'SELECT 1 FROM postings WHERE id=?',(posting_id,)).fetchone():
        raise AgenticError('interview_posting_missing')


def load_inputs(conn, posting_id):
    _posting(conn,posting_id)
    row=conn.execute('SELECT inputs_json,revision FROM interview_inputs WHERE posting_id=?',(posting_id,)).fetchone()
    if row is None:return InterviewInputs(),0
    try:
        value=InterviewInputs.model_validate_json(row['inputs_json'])
        if type(row['revision']) is not int or row['revision']<1:raise ValueError
    except (ValueError,TypeError):
        raise AgenticError('interview_inputs_invalid') from None
    return value,row['revision']


def save_inputs(conn, posting_id, inputs, *, expected_revision):
    """Called only for an explicit owner edit; no generated facts are promoted."""
    if type(inputs) is not InterviewInputs or type(expected_revision) is not int or expected_revision<0:
        raise AgenticError('interview_inputs_invalid')
    try:
        inputs=InterviewInputs.model_validate(inputs.model_dump(warnings=False))
    except (ValueError,TypeError):
        raise AgenticError('interview_inputs_invalid') from None
    if conn.in_transaction:raise AgenticError('transaction_already_active')
    conn.execute('BEGIN IMMEDIATE')
    try:
        _,revision=load_inputs(conn,posting_id)
        if revision!=expected_revision:raise AgenticError('interview_inputs_changed')
        ledger.upsert(conn,'applications','interview_inputs',{
            'posting_id':posting_id,'updated_at':datetime.now(UTC).isoformat(),
            'revision':revision+1,'inputs_json':json.dumps(inputs.model_dump(mode='json'))},commit=False)
        conn.commit()
    except BaseException:
        conn.rollback();raise
    return inputs,revision+1
