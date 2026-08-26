from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from caldav_assistant.api import Activity, Task
from caldav_assistant.api.v1.errors import ValidationError
from caldav_assistant.internal.activity import ActivityService
from caldav_assistant.internal.storage.sqlite import (
    SQLiteActivityRepository,
    SQLiteStore,
)


class FakeRepository:
    def __init__(self):
        self.items: list[Activity] = []
        self.record_calls = []

    def record(self, timestamp, action, object_id=None, metadata=None):
        self.record_calls.append((timestamp, action, object_id, metadata))
        self.items.append(Activity(timestamp, action, object_id, metadata or {}))

    def between(self, start, end):
        return [item for item in self.items if start <= item.timestamp < end]

    def for_object(self, object_id):
        return [item for item in self.items if item.object_id == object_id]


def fixed_clock():
    return datetime(2026, 8, 26, 1, 30, tzinfo=timezone.utc)


def test_record_returns_public_activity_and_persists_minimal_event():
    repo = FakeRepository()
    service = ActivityService(repo, clock=fixed_clock)

    item = service.record(
        "task_completed",
        "task-1",
        changes={"status": "COMPLETED"},
    )

    assert isinstance(item, Activity)
    assert item.timestamp == fixed_clock()
    assert item.action == "task_completed"
    assert item.object_id == "task-1"
    assert item.metadata == {"changes": {"status": "COMPLETED"}}
    assert repo.record_calls[-1][1:] == (
        "task_completed",
        "task-1",
        {"changes": {"status": "COMPLETED"}},
    )


def test_record_normalizes_text_and_uses_stable_validation_errors():
    repo = FakeRepository()
    service = ActivityService(repo, clock=fixed_clock)

    item = service.record(" task_started ", " task-1 ")
    assert item.action == "task_started"
    assert item.object_id == "task-1"

    with pytest.raises(ValidationError):
        service.record(" ")

    with pytest.raises(ValidationError):
        service.record("task_started", " ")


def test_repository_failure_is_not_reported_as_success():
    class FailingRepository(FakeRepository):
        def record(self, *args, **kwargs):
            raise OSError("disk full")

    service = ActivityService(FailingRepository(), clock=fixed_clock)

    with pytest.raises(OSError):
        service.record("task_started", "task-1")


def test_today_uses_half_open_range_and_returns_activity_objects():
    repo = FakeRepository()
    service = ActivityService(repo, clock=fixed_clock)

    # fixed_clock() is the current instant; these values are deliberately around
    # it so the test does not depend on a particular user timezone.
    local_now = fixed_clock().astimezone()
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = local_start.astimezone(timezone.utc)

    repo.items = [
        Activity(start_utc - timedelta(seconds=1), "before"),
        Activity(start_utc, "first"),
        Activity(start_utc + timedelta(hours=2), "second"),
        Activity(start_utc + timedelta(days=1), "after"),
    ]

    assert [item.action for item in service.today()] == ["first", "second"]


def test_for_task_accepts_task_or_uid_and_only_filters_journal_history():
    repo = FakeRepository()
    service = ActivityService(repo, clock=fixed_clock)
    repo.items = [
        Activity(fixed_clock(), "task_started", "task-1"),
        Activity(fixed_clock(), "task_completed", "task-2"),
    ]

    task = Task(id="task-1", summary="Report", status="NEEDS-ACTION")

    assert [item.action for item in service.for_task(task)] == ["task_started"]
    assert [item.action for item in service.for_task("task-1")] == ["task_started"]

    # A journal entry never overwrites or infers current CalDAV state.
    assert task.status == "NEEDS-ACTION"

    with pytest.raises(ValidationError):
        service.for_task(Task(summary="missing id"))


def test_sqlite_repository_round_trip_preserves_unicode_metadata_and_order(tmp_path):
    repo = SQLiteActivityRepository(SQLiteStore(tmp_path / "state.sqlite3"))
    first = datetime(2026, 8, 26, 1, 0, tzinfo=timezone.utc)
    second = first + timedelta(minutes=5)

    repo.record(first, "task_started", "task-1", {"note": "开始"})
    repo.record(second, "task_completed", "task-1", {"ok": True})

    items = repo.for_object("task-1")

    assert [item.action for item in items] == ["task_started", "task_completed"]
    assert items[0].metadata == {"note": "开始"}
    assert items[0].timestamp.tzinfo is not None


def test_sqlite_between_is_half_open_and_does_not_mix_other_days(tmp_path):
    repo = SQLiteActivityRepository(SQLiteStore(tmp_path / "state.sqlite3"))
    start = datetime(2026, 8, 26, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    repo.record(start - timedelta(seconds=1), "before")
    repo.record(start, "first")
    repo.record(end - timedelta(seconds=1), "last")
    repo.record(end, "after")

    assert [item.action for item in repo.between(start, end)] == ["first", "last"]
