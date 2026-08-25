from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from caldav_assistant.api import Agenda, Event, Task
from caldav_assistant.api.v1.errors import ValidationError
from caldav_assistant.internal.agenda import AgendaEngine


NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


def summaries(agenda: Agenda) -> list[str]:
    return [item.value.summary for item in agenda.items]


def test_build_merges_tasks_and_events_in_temporal_order():
    engine = AgendaEngine()

    all_day_task = Task(
        id="t1",
        summary="Submit report",
        due=date(2026, 8, 24),
    )
    tomorrow_task = Task(
        id="t2",
        summary="Prepare lesson",
        due=datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc),
    )
    lesson = Event(
        id="e1",
        summary="English lesson",
        start=datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc),
    )

    agenda = engine.build(
        [tomorrow_task, all_day_task],
        [lesson],
        days=2,
        now=NOW,
    )

    assert summaries(agenda) == [
        "Submit report",
        "English lesson",
        "Prepare lesson",
    ]
    assert [item.kind for item in agenda.items] == [
        "task",
        "event",
        "task",
    ]


def test_date_only_is_preserved_and_not_turned_into_midnight():
    engine = AgendaEngine()
    due = date(2026, 8, 24)
    task = Task(id="t1", summary="Report", due=due)

    agenda = engine.build([task], [], now=NOW)

    assert agenda.items[0].when is due
    assert isinstance(agenda.items[0].when, date)
    assert not isinstance(agenda.items[0].when, datetime)


def test_overdue_tasks_are_grouped_before_normal_scheduled_items():
    engine = AgendaEngine()

    overdue = Task(
        id="old",
        summary="Old report",
        due=date(2026, 8, 20),
    )
    today = Task(
        id="today",
        summary="Today's report",
        due=datetime(2026, 8, 24, 16, 0, tzinfo=timezone.utc),
    )

    agenda = engine.build([today, overdue], [], now=NOW)

    assert summaries(agenda) == [
        "Old report",
        "Today's report",
    ]


def test_current_undated_task_is_kept_and_grouped_first():
    engine = AgendaEngine()

    current = Task(
        id="current",
        summary="Writing",
    )
    overdue = Task(
        id="old",
        summary="Old task",
        due=date(2026, 8, 20),
    )

    agenda = engine.build(
        [overdue, current],
        [],
        now=NOW,
        user_state={"current_task_uid": "current"},
    )

    assert summaries(agenda) == [
        "Writing",
        "Old task",
    ]
    assert agenda.items[0].when is None


def test_completed_cancelled_and_ordinary_undated_tasks_are_not_active_agenda():
    engine = AgendaEngine()

    completed = Task(
        id="done",
        summary="Done",
        due=date(2026, 8, 24),
        status="COMPLETED",
        completed=True,
    )
    cancelled = Task(
        id="cancelled",
        summary="Cancelled",
        due=date(2026, 8, 24),
        status="CANCELLED",
    )
    undated = Task(
        id="later",
        summary="No schedule",
    )

    agenda = engine.build(
        [completed, cancelled, undated],
        [],
        now=NOW,
    )

    assert agenda.items == []


def test_days_range_has_an_exclusive_end_boundary():
    engine = AgendaEngine()

    inside = Event(
        id="inside",
        summary="Inside",
        start=datetime(2026, 8, 25, 23, 0, tzinfo=timezone.utc),
    )
    outside = Event(
        id="outside",
        summary="Outside",
        start=datetime(2026, 8, 26, 0, 0, tzinfo=timezone.utc),
    )

    agenda = engine.build(
        [],
        [outside, inside],
        days=2,
        now=NOW,
    )

    assert summaries(agenda) == ["Inside"]


def test_event_spanning_into_requested_range_is_included():
    engine = AgendaEngine()

    event = Event(
        id="overnight",
        summary="Overnight maintenance",
        start=datetime(2026, 8, 23, 23, 0, tzinfo=timezone.utc),
        end=datetime(2026, 8, 24, 1, 0, tzinfo=timezone.utc),
    )

    agenda = engine.build([], [event], now=NOW)

    assert summaries(agenda) == ["Overnight maintenance"]


def test_engine_does_not_mutate_task_state_and_rejects_invalid_days():
    engine = AgendaEngine()

    task = Task(
        id="old",
        summary="Old report",
        due=date(2026, 8, 20),
        overdue=False,
    )

    agenda = engine.build([task], [], now=NOW)

    assert agenda.items[0].value is task
    assert task.overdue is False

    for invalid in (0, -1, True, 1.5):
        with pytest.raises(ValidationError):
            engine.build([], [], days=invalid, now=NOW)
