from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from caldav_assistant.api import Agenda, AgendaItem, Event, Task
from caldav_assistant.api.v1.errors import ValidationError
from caldav_assistant.internal.agenda.next_engine import NextEngine


NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


def task_item(
    uid: str,
    summary: str,
    **fields,
) -> AgendaItem:
    task = Task(id=uid, summary=summary, **fields)
    return AgendaItem(value=task, when=task.due or task.start, kind="task")


def event_item(
    uid: str,
    summary: str,
    *,
    start,
    end=None,
) -> AgendaItem:
    event = Event(
        id=uid,
        summary=summary,
        start=start,
        end=end,
    )
    return AgendaItem(value=event, when=start, kind="event")


def choose(*items, **options):
    return NextEngine().choose(
        Agenda(list(items)),
        now=NOW,
        **options,
    )


def test_empty_agenda_returns_none():
    assert choose() is None


def test_current_task_wins_over_other_urgent_work():
    current = task_item("current", "Current work")
    overdue = task_item(
        "late",
        "Late report",
        due=NOW - timedelta(days=3),
    )

    result = choose(
        overdue,
        current,
        current_task_uid="current",
    )

    assert result.value.id == "current"


def test_skipped_current_task_is_not_selected():
    current = task_item("current", "Current work")
    overdue = task_item(
        "late",
        "Late report",
        due=NOW - timedelta(days=1),
    )

    result = choose(
        current,
        overdue,
        current_task_uid="current",
        skipped_uids={"current"},
    )

    assert result.value.id == "late"


def test_ongoing_event_beats_overdue_task():
    event = event_item(
        "meeting",
        "Meeting",
        start=NOW - timedelta(minutes=15),
        end=NOW + timedelta(minutes=45),
    )
    overdue = task_item(
        "late",
        "Late task",
        due=NOW - timedelta(days=1),
    )

    result = choose(overdue, event)

    assert result.value.id == "meeting"


def test_imminent_event_beats_overdue_task():
    event = event_item(
        "lesson",
        "English lesson",
        start=NOW + timedelta(minutes=30),
        end=NOW + timedelta(hours=1),
    )
    overdue = task_item(
        "late",
        "Late task",
        due=NOW - timedelta(days=1),
    )

    result = choose(overdue, event)

    assert result.value.id == "lesson"


def test_overdue_task_beats_due_soon_task():
    overdue = task_item(
        "late",
        "Late task",
        due=NOW - timedelta(hours=1),
    )
    soon = task_item(
        "soon",
        "Due soon",
        due=NOW + timedelta(hours=2),
    )

    result = choose(soon, overdue)

    assert result.value.id == "late"


def test_due_soon_beats_high_priority_task_without_deadline():
    soon = task_item(
        "soon",
        "Due soon",
        due=NOW + timedelta(hours=3),
        priority=8,
    )
    high_priority = task_item(
        "important",
        "Important but no deadline",
        priority=1,
    )

    result = choose(high_priority, soon)

    assert result.value.id == "soon"


def test_priority_orders_ordinary_available_tasks():
    low = task_item(
        "low",
        "Low priority",
        priority=8,
    )
    high = task_item(
        "high",
        "High priority",
        priority=1,
    )

    result = choose(low, high)

    assert result.value.id == "high"


def test_completed_and_cancelled_tasks_are_never_suggested():
    completed = task_item(
        "done",
        "Done",
        completed=True,
        status="COMPLETED",
    )
    cancelled = task_item(
        "cancelled",
        "Cancelled",
        status="CANCELLED",
    )
    valid = task_item("valid", "Valid")

    result = choose(completed, cancelled, valid)

    assert result.value.id == "valid"


def test_kind_filter_supports_next_task_and_next_event():
    task = task_item("task", "Task")
    event = event_item(
        "event",
        "Later event",
        start=NOW + timedelta(hours=5),
        end=NOW + timedelta(hours=6),
    )

    assert choose(task, event, kind="task").value.id == "task"
    assert choose(task, event, kind="event").value.id == "event"


def test_far_future_event_does_not_displace_available_task():
    task = task_item("task", "Do useful work")
    event = event_item(
        "event",
        "Tonight",
        start=NOW + timedelta(hours=6),
        end=NOW + timedelta(hours=7),
    )

    result = choose(event, task)

    assert result.value.id == "task"


def test_future_start_task_waits_behind_available_task():
    future = task_item(
        "future",
        "Not available yet",
        start=NOW + timedelta(hours=3),
        priority=1,
    )
    available = task_item(
        "available",
        "Available now",
        priority=8,
    )

    result = choose(future, available)

    assert result.value.id == "available"


def test_date_only_due_today_is_not_treated_as_overdue():
    today = task_item(
        "today",
        "Due today",
        due=date(2026, 8, 24),
    )
    ordinary = task_item(
        "ordinary",
        "Ordinary",
        priority=1,
    )

    result = choose(ordinary, today)

    assert result.value.id == "today"


def test_all_day_event_is_ongoing_during_its_date():
    event = event_item(
        "all-day",
        "All day",
        start=date(2026, 8, 24),
        end=date(2026, 8, 25),
    )
    overdue = task_item(
        "late",
        "Late task",
        due=date(2026, 8, 23),
    )

    result = choose(overdue, event)

    assert result.value.id == "all-day"


def test_invalid_kind_is_rejected_instead_of_silently_guessed():
    with pytest.raises(ValidationError):
        choose(
            task_item("1", "Task"),
            kind="something-else",
        )
