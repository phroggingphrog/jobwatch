"""Owner-confirmed follow-up history in the existing replayable application ledger."""
from __future__ import annotations

from datetime import UTC, date, datetime
import json
import re
from zoneinfo import ZoneInfo

from jobwatch import ledger
from jobwatch.followups import FollowupHistory, FollowupPin, cadence

from jobwatch.place import person_timezone
ACTIONS = {'applied_confirmed', 'response', 'interview_completed', 'sent', 'pin', 'clear_pin'}
ACTIVE = {'applied', 'assessment', 'interview'}


class FollowupEventError(ValueError):
    pass


def _time(value):
    try:
        result = datetime.fromisoformat(value) if isinstance(value, str) else value
        if type(result) is not datetime or result.tzinfo is None or result.utcoffset() is None:
            raise ValueError
        return result.astimezone(UTC)
    except (ValueError, TypeError):
        raise FollowupEventError('invalid_event_time') from None


def _events(conn, application_id):
    events = []
    for row in conn.execute('SELECT * FROM application_events WHERE application_id=? ORDER BY id', (application_id,)):
        row = dict(row)
        if row['actor'] != 'owner':
            continue
        action = row['kind'].removeprefix('followup_') if row['kind'].startswith('followup_') else None
        if action in ACTIONS:
            try:
                detail = json.loads(row['detail_json'] or '{}')
                if detail.get('owner_confirmed') is not True:
                    continue
                when = _time(detail.get('occurred_at', row['at']))
            except (ValueError, TypeError, AttributeError):
                raise FollowupEventError('invalid_followup_history') from None
        elif row['kind'] in {'status', 'outcome_decided'} and row['from_status'] != row['to_status']:
            # An owner-confirmed status is evidence of a submission/reply, never
            # evidence of the time a scheduled interview actually completed.
            action = 'applied_confirmed' if row['to_status'] == 'applied' else \
                     'response' if row['to_status'] in {'assessment', 'interview', 'offer'} else None
            if action is None:
                continue
            when, detail = _time(row['at']), {}
        else:
            continue
        events.append({'id': row['id'], 'action': action, 'when': when, 'recorded': _time(row['at']), 'detail': detail})
    return events


def _latest(events, action):
    matches = [e for e in events if e['action'] == action]
    if action == 'applied_confirmed':
        confirmations = [e for e in matches if e['detail'].get('owner_confirmed') is True]
        if confirmations:
            return max(confirmations, key=lambda e: (e['recorded'], e['id']))
    return max(matches, key=lambda e: (e['when'], e['id']), default=None)


def history(conn, application_id, *, now=None):
    now = _time(now or datetime.now(UTC))
    app = conn.execute('SELECT * FROM applications WHERE id=?', (application_id,)).fetchone()
    if app is None:
        raise FollowupEventError('application_missing')
    events = _events(conn, application_id)
    if any(e['when'] > now or e['recorded'] > now for e in events):
        raise FollowupEventError('future_activity_unverified')
    def latest(action):
        return _latest(events, action)
    applied = latest('applied_confirmed')
    response, interview = latest('response'), latest('interview_completed')
    sent = sorted((e for e in events if e['action'] == 'sent'), key=lambda e: (e['when'],e['id']))
    day = lambda e: e['when'].astimezone(person_timezone()).date() if e else None
    anchor = interview if app['status'] == 'interview' else response or applied
    recent = tuple(day(e) for e in sent if anchor and (e['when'], e['id']) >= (anchor['when'], anchor['id']))
    pins = [e for e in events if e['action'] in {'pin','clear_pin'}]
    pin_event = max(pins, key=lambda e: (e['recorded'],e['id']), default=None)
    pin = None
    if pin_event and pin_event['action'] == 'pin' and not any(
        (e['when'], e['id']) >= (pin_event['recorded'], pin_event['id']) for e in sent
    ):
        try:
            pin = FollowupPin(date.fromisoformat(pin_event['detail']['due_on']), pin_event['recorded'].astimezone(person_timezone()).date())
        except (KeyError, ValueError, TypeError):
            raise FollowupEventError('invalid_followup_history') from None
    return FollowupHistory(status=app['status'], applied_on=day(applied), response_on=day(response),
        interview_completed_on=day(interview), sent_on=tuple(day(e) for e in sent), pin=pin,
        sent_since_anchor=recent, pin_active=pin is not None)


def application_cadence(conn, application_id, *, now=None):
    now = _time(now or datetime.now(UTC))
    return cadence(history(conn, application_id, now=now), today=now.astimezone(person_timezone()).date())


def record_event(conn, application_id, action, *, operation_id, owner_confirmed,
                 occurred_at=None, due_on=None, channel=None, now=None):
    """Record what the owner confirms happened. No send operation exists here.

    A serialized transaction makes repeated requests idempotent. The existing
    ledger keeps these events during reindex; no new table or daemon is needed.
    """
    if owner_confirmed is not True:
        raise FollowupEventError('owner_confirmation_required')
    if action not in ACTIONS or type(operation_id) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', operation_id):
        raise FollowupEventError('invalid_followup_action')
    now = _time(now or datetime.now(UTC))
    detail = {'owner_confirmed': True}
    if action in {'pin','clear_pin'}:
        if occurred_at is not None or channel is not None:
            raise FollowupEventError('invalid_followup_fields')
        if action == 'pin':
            if type(due_on) is not date:
                raise FollowupEventError('invalid_pin_date')
            detail['due_on'] = due_on.isoformat()
        elif due_on is not None:
            raise FollowupEventError('invalid_followup_fields')
    else:
        at = _time(occurred_at)
        if at > now or due_on is not None:
            raise FollowupEventError('invalid_event_time')
        detail['occurred_at'] = at.isoformat()
        if action == 'sent':
            if channel not in {'email','linkedin','phone','other'}:
                raise FollowupEventError('invalid_followup_channel')
            detail['channel'] = channel
        elif channel is not None:
            raise FollowupEventError('invalid_followup_fields')
    payload = json.dumps(detail, sort_keys=True)
    source = 'followup:' + operation_id
    if conn.in_transaction:
        raise FollowupEventError('transaction_already_active')
    conn.execute('BEGIN IMMEDIATE')
    try:
        prior = conn.execute('SELECT * FROM application_events WHERE source=?', (source,)).fetchone()
        if prior:
            if prior['application_id'] != application_id or prior['kind'] != 'followup_'+action or prior['detail_json'] != payload:
                raise FollowupEventError('operation_conflict')
            conn.commit()
            return dict(prior)
        h = history(conn, application_id, now=now)
        if h.status not in ACTIVE:
            raise FollowupEventError('application_not_active')
        if action not in {'applied_confirmed','pin','clear_pin'}:
            applied = _latest(_events(conn, application_id), 'applied_confirmed')
            if applied is None or at < applied['when']:
                raise FollowupEventError('application_date_unverified')
        if action == 'applied_confirmed':
            if any(e['action'] in {'sent', 'response', 'interview_completed'} and e['when'] < at
                   for e in _events(conn, application_id)):
                raise FollowupEventError('application_date_after_communication')
            ledger.upsert(conn, 'applications', 'applications', {'id': application_id,
                'applied_at': at.isoformat()}, commit=False)
        row = ledger.upsert(conn,'applications','application_events',{
            'application_id':application_id,'at':now.isoformat(),'kind':'followup_'+action,
            'actor':'owner','source':source,'detail_json':payload},commit=False)
        conn.commit()
        return row
    except BaseException:
        conn.rollback()
        raise


def recent_events(conn, application_id, *, limit=10):
    """Display metadata only; preserve all canonical events in the ledger."""
    events = sorted(_events(conn, application_id), key=lambda e: (e['when'],e['id']), reverse=True)
    labels = {'sent':'Follow-up sent', 'response':'Reply received',
              'interview_completed':'Interview completed', 'applied_confirmed':'Application confirmed',
              'pin':'Reminder date set', 'clear_pin':'Standard timing restored'}
    return {'total':len(events), 'items':[{'label':labels[e['action']],
        'at':e['when'].astimezone(person_timezone()).strftime('%Y-%m-%d %H:%M'),
        'channel':e['detail'].get('channel','')} for e in events[:limit]]}
