"""Read-only follow-up cadence, separate from draft generation and owner sending.

Dates must come from confirmed application/communication events, converted to the
owner's calendar date by the caller. A draft, note edit, or scheduled interview is
never a communication event. No IO or automatic status changes occur here.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
from datetime import date, timedelta


@dataclass(frozen=True)
class FollowupPin:
    due_on: date
    set_on: date


@dataclass(frozen=True)
class FollowupHistory:
    status: str
    applied_on: date | None
    response_on: date | None = None
    interview_completed_on: date | None = None
    sent_on: tuple[date, ...] = ()  # Only distinct owner-confirmed sent events.
    pin: FollowupPin | None = None
    sent_since_anchor: tuple[date, ...] | None = None  # Timestamp-ordered by the event adapter.
    pin_active: bool | None = None


@dataclass(frozen=True)
class FollowupCadence:
    state: str
    kind: str
    due_on: date | None
    sent_count: int
    followups_since_response: int
    reason: str

    @property
    def draft_allowed(self) -> bool:
        return self.state in {'urgent', 'overdue'}


def cadence(history: FollowupHistory, *, today: date) -> FollowupCadence:
    """Original 7-day applied / 1-day initial reply / 3-day later cadence.

    Two unanswered applied chases become cold, never rejected. A current owner
    pin may override cold; terminal application states always suppress reminders.
    Scheduled interviews require an actual completion date before a thank-you.
    """
    sent = history.sent_on
    count = len(sent)
    unanswered = count

    def result(state, kind='application', due=None, reason=''):
        return FollowupCadence(state, kind, due, count, unanswered, reason)

    if history.status not in {'applied', 'assessment', 'interview'}:
        return result('inactive', reason='application_not_active')
    facts = (history.applied_on, history.response_on, history.interview_completed_on, *sent)
    if history.applied_on is None or any(
        value is not None and (type(value) is not date or value > today) for value in facts
    ):
        return result('unknown', reason='activity_date_unverified')
    if any(value is not None and value < history.applied_on for value in facts[1:]):
        return result('unknown', reason='activity_order_unverified')
    anchor = history.applied_on
    kind = 'application'
    interval = 7
    if history.status == 'assessment':
        if history.response_on is None:
            return result('unknown', reason='response_date_missing')
        anchor, kind, interval = history.response_on, 'reply', 1
    elif history.status == 'interview':
        if history.interview_completed_on is None:
            return result('unknown', reason='interview_completion_unverified')
        anchor, kind, interval = history.interview_completed_on, 'interview_thankyou', 1
    elif history.response_on is not None:
        # A confirmed reply may precede the owner's next tracker status edit.
        anchor, kind, interval = history.response_on, 'reply', 1
    if history.sent_since_anchor is not None and (Counter(history.sent_since_anchor) - Counter(sent)):
        return result('unknown', kind, reason='activity_order_unverified')
    if history.sent_since_anchor is None and kind != 'application' and anchor in sent:
        return result('unknown', kind, reason='same_day_response_order_unverified')
    recent = history.sent_since_anchor if history.sent_since_anchor is not None else tuple(day for day in sent if day >= anchor)
    unanswered = len(recent)
    pin = history.pin
    if pin is not None:
        if type(pin.due_on) is not date or type(pin.set_on) is not date or pin.set_on > today:
            return result('unknown', kind, reason='pin_date_unverified')
        if history.pin_active is True or (history.pin_active is None and not any(day >= pin.set_on for day in sent)):
            return result('overdue' if pin.due_on <= today else 'waiting', kind, pin.due_on, 'owner_date')
    if kind == 'application' and unanswered >= 2:
        return result('cold', kind, reason='two_unanswered_followups')
    if recent:
        interval = 7 if kind == 'application' else 3
        due = max(recent) + timedelta(days=interval)
    else:
        due = anchor + timedelta(days=interval)
        if kind == 'reply' and anchor == today:
            return result('urgent', kind, due, 'new_reply')
    return result('overdue' if due <= today else 'waiting', kind, due, 'cadence')
