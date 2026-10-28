from datetime import date, timedelta

from jobwatch.followups import FollowupHistory, FollowupPin, cadence

TODAY = date(2026, 10, 11)


def history(**changes):
    return FollowupHistory(**{'status': 'applied', 'applied_on': TODAY - timedelta(days=21), **changes})


def test_applied_reminder_boundary_and_no_draft_submission_inference():
    assert cadence(history(), today=TODAY).state == 'overdue'
    assert cadence(history(applied_on=TODAY - timedelta(days=6)), today=TODAY).state == 'waiting'
    assert cadence(history(status='drafted'), today=TODAY).state == 'inactive'
    assert cadence(history(applied_on=None), today=TODAY).state == 'unknown'


def test_sent_followup_restarts_clock_and_two_unanswered_become_cold():
    first = TODAY - timedelta(days=3)
    assert cadence(history(sent_on=(first,)), today=TODAY).due_on == first + timedelta(days=7)
    result = cadence(history(sent_on=(first - timedelta(days=7), first)), today=TODAY)
    assert result.state == 'cold' and result.due_on is None
    assert not result.draft_allowed


def test_reply_resets_unanswered_streak_without_erasing_history():
    result = cadence(history(status='assessment', response_on=TODAY,
        sent_on=(TODAY - timedelta(days=8), TODAY - timedelta(days=2))), today=TODAY)
    assert result.state == 'urgent' and result.followups_since_response == 0
    assert result.sent_count == 2


def test_interview_status_is_not_evidence_that_interview_happened():
    result = cadence(history(status='interview'), today=TODAY)
    assert result.state == 'unknown' and not result.draft_allowed
    completed = cadence(history(status='interview', interview_completed_on=TODAY - timedelta(days=1)), today=TODAY)
    assert completed.state == 'overdue' and completed.kind == 'interview_thankyou'


def test_pin_overrides_cold_until_later_send_and_terminal_always_wins():
    sent = (TODAY - timedelta(days=10), TODAY - timedelta(days=2))
    pin = FollowupPin(due_on=TODAY + timedelta(days=2), set_on=TODAY)
    result = cadence(history(sent_on=sent, pin=pin), today=TODAY)
    assert result.state == 'waiting' and result.due_on == pin.due_on
    assert cadence(history(status='rejected', sent_on=sent, pin=pin), today=TODAY).state == 'inactive'
    assert cadence(history(sent_on=sent + (TODAY,), pin=pin), today=TODAY).state == 'cold'


def test_unknown_or_future_activity_never_produces_fabricated_overdue_state():
    assert cadence(history(applied_on=TODAY + timedelta(days=1)), today=TODAY).state == 'unknown'
    assert cadence(history(sent_on=(TODAY + timedelta(days=1),)), today=TODAY).state == 'unknown'
    assert cadence(history(status='assessment'), today=TODAY).state == 'unknown'


def test_followup_after_reply_uses_three_day_cadence():
    result = cadence(history(status='assessment', response_on=TODAY - timedelta(days=6),
        sent_on=(TODAY - timedelta(days=3),)), today=TODAY)
    assert result.state == 'overdue' and result.due_on == TODAY


def test_same_day_reply_and_sent_order_requires_event_time_before_scheduling():
    result = cadence(history(status='assessment', response_on=TODAY, sent_on=(TODAY,)), today=TODAY)
    assert result.state == 'unknown' and result.reason == 'same_day_response_order_unverified'
