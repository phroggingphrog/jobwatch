"""Person-bound human feedback; fixtures and model responses are synthetic."""
import sqlite3

import pytest

from jobwatch import db, users
from jobwatch.candidate.contracts import digest
from pipeline.agentic import feedback, shortlist
from tests.baseline_support import world, frozen  # noqa: F401


@pytest.fixture
def conn(tmp_path):
    value = db.connect(tmp_path / 'feedback.db')
    yield value
    value.close()


@pytest.fixture
def shortlisted(frozen):
    entries = shortlist.build_shortlist(frozen.conn, frozen.config)
    frozen.entries = {e.posting_id: e for e in entries}
    return frozen


def reject(f, *, request_id='reject-one', **kwargs):
    return feedback.record_feedback(
        f.conn, f.config, posting_id=42, kind='reject', request_id=request_id,
        actor='person', expected_entry_id=f.entries[42].entry_id,
        reason_code='other', reason_text='  Exact human words.\n', **kwargs)


def test_vocabulary_keeps_taste_eligibility_and_data_quality_distinct():
    reasons = feedback.REJECTION_REASONS
    assert len(reasons) == 11
    assert reasons['pay_too_low'].meaning == 'preference'
    assert reasons['seems_ineligible_for_me'].meaning == 'eligibility'
    assert reasons['ad_looks_wrong'].meaning == 'data_quality'
    assert reasons['other'].text_required
    assert reasons['not_this_employer'].rule_kind == 'employer'


def test_rejection_replay_and_restore_preserve_human_history(shortlisted):
    f = shortlisted
    runs = [tuple(r) for r in f.conn.execute('SELECT * FROM agentic_runs')]
    before = feedback.dismissal_state_hash(f.conn)
    event = reject(f)
    assert event['reason_text'] == '  Exact human words.\n'
    assert event['person'] == users.current() and event['actor'] == 'person'
    assert event['entry_id'] == f.entries[42].entry_id
    assert event['run_key'] == f.entries[42].run_key
    assert event['meaning'] == 'unspecified'
    assert event['reasons_version'] == feedback.REASONS_VERSION
    assert feedback.rejected_posting_ids(f.conn) == {42}
    assert feedback.dismissal_state_hash(f.conn) != before
    # An exact retry cannot restore visibility or require a current shortlist entry.
    assert reject(f) == event
    restored = feedback.record_feedback(
        f.conn, f.config, posting_id=42, kind='restore', request_id='restore-one',
        actor='person', source='chat', expected_rejection_id=event['id'])
    assert restored['detail']['rejection_event_id'] == event['id']
    assert restored['entry_id'] == event['entry_id']
    assert restored['run_key'] == event['run_key']
    assert restored['profile_version'] == event['profile_version']
    assert restored['source'] == 'chat'
    assert feedback.rejected_posting_ids(f.conn) == set()
    assert feedback.dismissal_state_hash(f.conn) != before
    assert [tuple(r) for r in f.conn.execute('SELECT * FROM agentic_runs')] == runs
    assert not f.conn.execute("SELECT 1 FROM sqlite_master WHERE name='preference_picks'").fetchone()
    assert feedback.list_events(f.conn) == [restored, event]
    with pytest.raises(sqlite3.IntegrityError, match='immutable'):
        f.conn.execute('DELETE FROM feedback_events')
    f.conn.rollback()


def test_reject_binds_current_entry_and_replay_binds_exact_payload(shortlisted):
    f = shortlisted
    with users.use('unrelated-fixture'):
        with pytest.raises(feedback.FeedbackError, match='posting_not_shortlisted'):
            reject(f)
        assert feedback.list_events(f.conn) == []
    with pytest.raises(feedback.FeedbackError, match='entry_changed'):
        feedback.record_feedback(f.conn, f.config, posting_id=42, kind='reject',
            actor='person', request_id='stale', expected_entry_id='wrong', reason_code='pay_too_low')
    assert feedback.list_events(f.conn) == []
    event = reject(f)
    for changed in ({'source':'chat'}, {'expected_entry_id':'changed'}, {'reason_text':'changed'}):
        values = dict(posting_id=42, kind='reject', actor='person', request_id='reject-one',
            expected_entry_id=f.entries[42].entry_id, reason_code='other', reason_text='  Exact human words.\n')
        values.update(changed)
        with pytest.raises(feedback.FeedbackError, match='feedback_conflict'):
            feedback.record_feedback(f.conn, f.config, **values)
    assert feedback.list_events(f.conn) == [event]


def test_restore_binds_latest_active_rejection_and_never_replays_state(shortlisted):
    f = shortlisted
    event = reject(f)
    values = dict(posting_id=42, kind='restore', actor='person', request_id='restore-one',
                  expected_rejection_id=event['id'])
    restored = feedback.record_feedback(f.conn, f.config, **values)
    assert feedback.record_feedback(f.conn, f.config, **values) == restored
    with pytest.raises(feedback.FeedbackError, match='rejection_stale'):
        feedback.record_feedback(f.conn, f.config, **{**values, 'request_id':'restore-two'})
    f.entries = {e.posting_id:e for e in shortlist.build_shortlist(f.conn, f.config)}
    next_event = reject(f, request_id='reject-two')
    assert next_event['id'] != event['id']
    with pytest.raises(feedback.FeedbackError, match='rejection_stale'):
        feedback.record_feedback(f.conn, f.config, **{**values, 'request_id':'restore-three'})
    # Historical successful retry returns the old result, without restoring the new rejection.
    assert feedback.record_feedback(f.conn, f.config, **values) == restored
    assert feedback.rejected_posting_ids(f.conn) == {42}


def test_restore_of_closed_posting_does_not_revive_old_snapshot(shortlisted):
    f = shortlisted
    event = reject(f)
    f.conn.execute("UPDATE postings SET closed_at='2026-10-23' WHERE id=42")
    f.conn.commit()
    feedback.record_feedback(f.conn, f.config, posting_id=42, kind='restore', actor='person',
        request_id='restore-closed', expected_rejection_id=event['id'])
    assert shortlist.load_entry(f.conn, 42, config=f.config) is None
    assert 42 not in {e.posting_id for e in shortlist.build_shortlist(f.conn, f.config)}


@pytest.mark.parametrize('actor', ['agent', 'owner', '', None, True])
def test_actor_must_be_person(conn, actor):
    with pytest.raises(feedback.FeedbackError, match='person_required'):
        feedback.record_feedback(conn, {}, posting_id=42, kind='reject', actor=actor,
            request_id='a', expected_entry_id='e', reason_code='pay_too_low')
    assert feedback.list_events(conn) == []


@pytest.mark.parametrize('changed,code', [
    ({'source':'model'}, 'invalid_request'), ({'posting_id':True}, 'invalid_request'),
    ({'request_id':''}, 'invalid_request'), ({'request_id':'x'*129}, 'invalid_request'),
    ({'reason_text':None}, 'invalid_request'), ({'reason_text':'x'*2001}, 'invalid_request'),
    ({'expected_entry_id':None}, 'invalid_request'), ({'reason_code':'unknown'}, 'invalid_reason'),
    ({'reason_code':'other','reason_text':' \n'}, 'reason_text_required'),
])
def test_invalid_lifecycle_inputs_leave_no_event(conn, changed, code):
    values = dict(posting_id=42, kind='reject', actor='person', request_id='a',
                  expected_entry_id='e', reason_code='pay_too_low')
    values.update(changed)
    with pytest.raises(feedback.FeedbackError, match=code):
        feedback.record_feedback(conn, {}, **values)
    assert feedback.list_events(conn) == []


def test_append_helper_is_atomic_with_caller_and_person_scoped(conn):
    with pytest.raises(feedback.FeedbackError, match='transaction_required'):
        feedback.append_event(conn, kind='answer', request_id='a', actor='person')
    conn.execute('BEGIN IMMEDIATE')
    with users.use('fixture-a'):
        first = feedback.append_event(conn, kind='answer', request_id='same', actor='person',
            reason_text='Raw exact answer', prompt_id='p', detail={'answer':'Raw exact answer'})
        assert conn.in_transaction
        assert feedback.append_event(conn, kind='answer', request_id='same', actor='person',
            reason_text='Raw exact answer', prompt_id='p', detail={'answer':'Raw exact answer'}) == first
        with pytest.raises(feedback.FeedbackError, match='feedback_conflict'):
            feedback.append_event(conn, kind='answer', request_id='same', actor='person', reason_text='different')
    with users.use('fixture-b'):
        assert feedback.list_events(conn) == []
        second = feedback.append_event(conn, kind='answer', request_id='same', actor='person')
        assert second['id'] != first['id']
        assert feedback.list_events(conn) == [second]
    conn.rollback()
    assert conn.execute('SELECT count(*) FROM feedback_events').fetchone()[0] == 0


@pytest.mark.parametrize('kind', ['select', 'exclude', 'comparison', 'answer'])
def test_other_domain_events_retain_payload_and_never_commit(conn, kind):
    conn.execute('BEGIN IMMEDIATE')
    event = feedback.append_event(conn, kind=kind, actor='person', source='chat',
        request_id='domain-request', posting_id=42, entry_id='entry', run_key='run',
        profile_version=1, prompt_id='prompt', reason_text='Exact human text.\n',
        detail={'operation':kind, 'selected':None, 'alternatives':[42, 43, 44]})
    assert event['kind'] == kind and event['meaning'] is None
    assert event['detail'] == {'operation':kind, 'selected':None, 'alternatives':[42, 43, 44]}
    assert event['reasons_version'] == feedback.REASONS_VERSION
    assert event['reason_text'] == 'Exact human text.\n'
    assert conn.in_transaction
    conn.rollback()
    assert feedback.list_events(conn) == []


@pytest.mark.parametrize('changed', [
    {'source':True}, {'kind':[]}, {'reason_code':[]}, {'profile_version':True},
    {'entry_id':42}, {'prompt_id':False}, {'detail':[]}, {'detail':{1:'coerced-key'}},
    {'detail':{'invalid':float('nan')}}, {'detail':{'invalid':object()}},
    {'input_hash':'not-a-hash'},
])
def test_append_validation_is_typed_and_preserves_caller_transaction(conn, changed):
    conn.execute('BEGIN')
    values = dict(kind='answer', actor='person', request_id='a')
    values.update(changed)
    with pytest.raises(feedback.FeedbackError):
        feedback.append_event(conn, **values)
    assert conn.in_transaction and feedback.list_events(conn) == []
    conn.rollback()


def test_append_accepts_a_canonical_domain_request_hash(conn):
    conn.execute('BEGIN IMMEDIATE')
    manifest_hash = digest({'approved':'exact-human-payload', 'entry_id':'entry'})
    event = feedback.append_event(conn, kind='select', actor='person', request_id='a',
        entry_id='entry', input_hash=manifest_hash)
    assert event['input_hash'] == manifest_hash
    assert feedback.append_event(conn, kind='select', actor='person', request_id='a',
        entry_id='entry', input_hash=manifest_hash) == event
    with pytest.raises(feedback.FeedbackError, match='feedback_conflict'):
        feedback.append_event(conn, kind='select', actor='person', request_id='a',
            entry_id='entry', input_hash=digest({'changed':'payload'}))
    conn.rollback()


def test_shared_connection_dismissals_never_cross_people(conn):
    with users.use('fixture-a'):
        empty = feedback.dismissal_state_hash(conn)
        conn.execute('BEGIN IMMEDIATE')
        first = feedback.append_event(conn, kind='reject', request_id='a', actor='person',
            posting_id=42, entry_id='a-entry', reason_code='pay_too_low')
        conn.commit()
        own = feedback.dismissal_state_hash(conn)
        assert feedback.rejected_posting_ids(conn) == {42}
    with users.use('fixture-b'):
        assert feedback.dismissal_state_hash(conn) == empty
        assert feedback.rejected_posting_ids(conn) == set()
        assert feedback.list_events(conn) == []
        with pytest.raises(feedback.FeedbackError, match='rejection_stale'):
            feedback.record_feedback(conn, {}, posting_id=42, kind='restore', actor='person',
                request_id='b', expected_rejection_id=first['id'])
    with users.use('fixture-a'):
        assert feedback.dismissal_state_hash(conn) == own
        assert feedback.list_events(conn) == [first]


def test_public_mutation_cannot_commit_caller_transaction(conn):
    conn.execute('BEGIN')
    with pytest.raises(feedback.FeedbackError, match='transaction_active'):
        feedback.record_feedback(conn, {}, posting_id=42, kind='reject', actor='person',
            request_id='a', expected_entry_id='e', reason_code='pay_too_low')
    assert conn.in_transaction
    conn.rollback()


@pytest.mark.parametrize('limit', [0, 201, True, '10'])
def test_history_limit_is_bounded(conn, limit):
    with pytest.raises(feedback.FeedbackError, match='invalid_request'):
        feedback.list_events(conn, limit=limit)


def test_read_helpers_do_not_create_schema():
    value = sqlite3.connect(':memory:')
    assert feedback.list_events(value) == []
    assert feedback.rejected_posting_ids(value) == set()
    assert feedback.dismissal_state_hash(value) == digest([])
    assert value.execute('SELECT count(*) FROM sqlite_master').fetchone()[0] == 0
    value.close()
