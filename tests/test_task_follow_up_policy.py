from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from caldav_assistant.api import Event, Task
from caldav_assistant.internal.reminders import ReminderEngine, TaskFollowUpPolicy


UTC = timezone.utc


def task(*, due, status="NEEDS-ACTION", completed=False):
    return Task(
        id="report",
        summary="English writing",
        due=due,
        status=status,
        completed=completed,
    )


def test_follow_up_waits_for_overdue_grace_period():
    policy = TaskFollowUpPolicy()
    due = datetime(2026, 8, 30, 16, 0, tzinfo=UTC)

    assert policy.evaluate(
        task(due=due),
        datetime(2026, 8, 30, 16, 19, tzinfo=UTC),
    ) == []

    requests = policy.evaluate(
        task(due=due),
        datetime(2026, 8, 30, 16, 20, tzinfo=UTC),
    )

    assert [request.when for request in requests] == [
        datetime(2026, 8, 30, 16, 20, tzinfo=UTC),
        datetime(2026, 8, 30, 17, 20, tzinfo=UTC),
    ]
    assert requests[0].source == "task_follow_up"
    assert requests[0].object_id == "report"
    assert requests[0].actions == ()
    assert "Overdue by 20 minutes" in requests[0].body


def test_long_offline_period_generates_only_latest_catch_up_and_next_slot():
    policy = TaskFollowUpPolicy()
    due = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)

    requests = policy.evaluate(
        task(due=due),
        datetime(2026, 8, 30, 15, 47, tzinfo=UTC),
    )

    # Slots are 10:20, 11:20, ...; do not replay all five missed reminders.
    assert [request.when for request in requests] == [
        datetime(2026, 8, 30, 15, 20, tzinfo=UTC),
        datetime(2026, 8, 30, 16, 20, tzinfo=UTC),
    ]
    assert [request.metadata["slot_index"] for request in requests] == [5, 6]


def test_follow_up_text_distinguishes_in_progress_task():
    policy = TaskFollowUpPolicy()
    due = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)

    request = policy.evaluate(
        task(due=due, status="IN-PROCESS"),
        datetime(2026, 8, 30, 10, 20, tzinfo=UTC),
    )[0]

    assert request.title == "Task still in progress: English writing"
    assert "mark it done" in request.body


def test_policy_defensively_stops_for_completed_cancelled_and_date_only_tasks():
    policy = TaskFollowUpPolicy()
    now = datetime(2026, 8, 30, 18, 0, tzinfo=UTC)
    overdue = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)

    assert policy.evaluate(task(due=overdue, completed=True), now) == []
    assert policy.evaluate(task(due=overdue, status="COMPLETED"), now) == []
    assert policy.evaluate(task(due=overdue, status="CANCELLED"), now) == []
    assert policy.evaluate(task(due=date(2026, 8, 30)), now) == []
    assert policy.evaluate(
        Event(id="lesson", summary="Lesson", start=overdue),
        now,
    ) == []


def test_policy_rejects_invalid_intervals():
    with pytest.raises(ValueError, match="first_overdue_delay"):
        TaskFollowUpPolicy(first_overdue_delay=timedelta(minutes=-1))

    with pytest.raises(ValueError, match="repeat_interval"):
        TaskFollowUpPolicy(repeat_interval=timedelta(0))


def test_default_assistant_engine_adds_follow_up_and_completed_task_stops_all_task_reminders():
    engine = ReminderEngine()
    due = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)
    now = datetime(2026, 8, 30, 10, 20, tzinfo=UTC)

    requests = engine.evaluate([task(due=due)], now=now)

    assert [request.source for request in requests] == [
        "task_due",
        "task_follow_up",
        "task_follow_up",
    ]
    assert requests[1].when == now
    assert requests[2].when == datetime(2026, 8, 30, 11, 20, tzinfo=UTC)

    assert engine.evaluate(
        [task(due=due, status="COMPLETED", completed=True)],
        now=now,
    ) == []


def test_changing_due_replaces_follow_up_schedule_instead_of_preserving_old_slots():
    policy = TaskFollowUpPolicy()
    now = datetime(2026, 8, 30, 15, 0, tzinfo=UTC)

    old = policy.evaluate(
        task(due=datetime(2026, 8, 30, 10, 0, tzinfo=UTC)),
        now,
    )
    moved = policy.evaluate(
        task(due=datetime(2026, 8, 30, 14, 0, tzinfo=UTC)),
        now,
    )

    assert {request.key for request in old}.isdisjoint(
        {request.key for request in moved}
    )
    assert moved[0].when == datetime(2026, 8, 30, 14, 20, tzinfo=UTC)
    assert moved[1].when == datetime(2026, 8, 30, 15, 20, tzinfo=UTC)


def test_floating_due_uses_the_injected_clock_timezone_consistently():
    policy = TaskFollowUpPolicy()
    due = datetime(2026, 8, 30, 10, 0)
    now = datetime(2026, 8, 30, 10, 20, tzinfo=UTC)

    request = policy.evaluate(task(due=due), now)[0]

    assert request.when == datetime(2026, 8, 30, 10, 20, tzinfo=UTC)
