from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from caldav_assistant.api import Reminder, Task
from caldav_assistant.api.v1.errors import ValidationError
from caldav_assistant.internal.cli import monitor_app
from caldav_assistant.internal.runtime.observable_service import ObservableAssistantService
from caldav_assistant.internal.work_period import (
    WorkPeriodService,
    maybe_work_duration,
    parse_work_duration,
)


class FakeReminders:
    def __init__(self):
        self.items = []
        self.cancelled = []
        self.sequence = 0

    def list(self, **filters):
        result = list(self.items)
        for key, expected in filters.items():
            result = [item for item in result if item.metadata.get(key) == expected]
        return result

    def create(self, title, when, **metadata):
        self.sequence += 1
        item = Reminder(
            id=f"rem-{self.sequence}",
            title=title,
            when=when,
            metadata=dict(metadata),
        )
        self.items.append(item)
        return item

    def cancel(self, reminder):
        self.items = [item for item in self.items if item.id != reminder.id]
        self.cancelled.append(reminder)
        return reminder


class FakeActivity:
    def __init__(self):
        self.records = []

    def record(self, action, object_id=None, **metadata):
        self.records.append((action, object_id, metadata))


class FakeSession:
    def __init__(self, task_id):
        self.task_id = task_id

    def current_task_id(self):
        return self.task_id


class FakeTasks:
    def __init__(self, task):
        self.task = task

    def get(self, task_id):
        assert task_id == self.task.id
        return self.task


def test_duration_parser_is_explicit_and_does_not_guess_titles():
    assert parse_work_duration("30m") == 1800
    assert parse_work_duration("1.5h") == 5400
    assert parse_work_duration("45s") == 45
    assert maybe_work_duration("30m") == 1800
    assert maybe_work_duration("chapter-30") is None
    with pytest.raises(ValidationError):
        parse_work_duration("30")


def test_allocate_creates_persistent_explicit_reminder_without_touching_task_due():
    task = Task(
        id="t1",
        summary="Anki",
        due=datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc),
        status="IN-PROCESS",
    )
    reminders = FakeReminders()
    activity = FakeActivity()
    now = datetime(2026, 8, 30, 7, 0, tzinfo=timezone.utc)
    service = WorkPeriodService(
        reminders,
        activity=activity,
        session=FakeSession("t1"),
        tasks=FakeTasks(task),
        clock=lambda: now,
    )
    original_due = task.due

    status = service.allocate("t1", 1800)

    assert status["state"] == "scheduled"
    assert status["deadline"] == (now + timedelta(minutes=30)).isoformat()
    assert status["task_due_changed"] is False
    assert task.due == original_due
    assert len(reminders.items) == 1
    reminder = reminders.items[0]
    assert reminder.metadata["kind"] == "work_period"
    assert reminder.metadata["source"] == "work_period_end"
    assert reminder.metadata["task_id"] == "t1"
    assert reminder.metadata["duration_seconds"] == 1800
    assert "Task is still in progress" in reminder.metadata["body"]
    assert activity.records[-1][0] == "work_period_allocated"
    assert activity.records[-1][2]["storage"] == "assistant_state/reminders.items.v1"


def test_reallocating_replaces_old_period_and_pause_cleanup_can_cancel_by_task():
    task = Task(id="t1", summary="Anki", status="IN-PROCESS")
    reminders = FakeReminders()
    now = datetime(2026, 8, 30, 7, 0, tzinfo=timezone.utc)
    service = WorkPeriodService(
        reminders,
        session=FakeSession("t1"),
        tasks=FakeTasks(task),
        clock=lambda: now,
    )

    first = service.allocate("t1", 1800)
    second = service.allocate("t1", 900)

    assert first["reminder_id"] != second["reminder_id"]
    assert len(reminders.cancelled) == 1
    assert len(reminders.items) == 1
    assert service.cancel_for("t1", reason="task_paused")
    assert service.status("t1")["state"] == "none"


def test_work_period_rejects_non_current_task():
    task = Task(id="t2", summary="Other")
    service = WorkPeriodService(
        FakeReminders(),
        session=FakeSession("t1"),
        tasks=FakeTasks(task),
        clock=lambda: datetime(2026, 8, 30, 7, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(ValidationError, match="only be assigned"):
        service.allocate("t2", 1800)


def test_work_period_rejects_allocation_without_current_work():
    task = Task(id="t1", summary="Anki", status="IN-PROCESS")
    service = WorkPeriodService(
        FakeReminders(),
        session=FakeSession(None),
        tasks=FakeTasks(task),
        clock=lambda: datetime(2026, 8, 30, 7, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(ValidationError, match="currently being worked on"):
        service.allocate("t1", 1800)


def test_lifecycle_start_duration_is_removed_before_core_start_command():
    parsed = monitor_app.base.ParsedCommand(
        raw="start Anki 30m",
        name="start",
        args=("Anki", "30m"),
    )

    effective, seconds = monitor_app._split_lifecycle_duration(parsed)

    assert effective.args == ("Anki",)
    assert seconds == 1800


def test_observable_delivery_uses_work_period_semantic_source_and_task_id():
    request = SimpleNamespace(
        key="rem-1",
        when=datetime(2026, 8, 30, 7, 30, tzinfo=timezone.utc),
        title="Work period finished — Anki",
        body="period ended",
        source="reminder",
        object_id="rem-1",
        metadata={
            "kind": "work_period",
            "source": "work_period_end",
            "task_id": "t1",
            "duration_seconds": 1800,
        },
    )

    class Reminders:
        notifications = SimpleNamespace(adapter=SimpleNamespace())

    service = object.__new__(ObservableAssistantService)
    service.reminders = Reminders()
    from collections import deque
    from threading import RLock
    service._lock = RLock()
    service._event_seq = 0
    service.event_limit = 20
    service._delivery_events = deque(maxlen=20)

    service._publish_delivery(request)
    event = service.delivery_events()[0]

    assert event["source"] == "work_period_end"
    assert event["object_id"] == "t1"
    assert event["metadata"]["duration_seconds"] == 1800
