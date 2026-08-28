from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from caldav_assistant.api import ActionResult, Event, Task
from caldav_assistant.api.v1.errors import NotFoundError
from caldav_assistant.internal.storage.sqlite import SQLiteStore, SQLiteUndoRepository
from caldav_assistant.internal.undo.service import UndoManager


class MemoryRepo:
    def __init__(self):
        self.items = []
        self.next_id = 1

    def remember(self, payload):
        self.items.append({"id": self.next_id, "payload": payload})
        self.next_id += 1

    def latest(self):
        return dict(self.items[-1]) if self.items else None

    def discard(self, item_id):
        self.items = [item for item in self.items if item["id"] != item_id]


class FakeTasks:
    def __init__(self, undo):
        self.undo = undo
        self.calls = []

    def update(self, task_id, **changes):
        self.calls.append(("update", task_id, changes))
        self.undo.remember({"action": "nested"})
        return ActionResult(True, affected=Task(id=task_id, summary="Task"), undo_available=True)

    def delete(self, task_id):
        self.calls.append(("delete", task_id))
        self.undo.remember({"action": "nested"})
        return ActionResult(True, affected=Task(id=task_id, summary="Task"), undo_available=True)

    def create(self, task):
        self.calls.append(("create", task))
        self.undo.remember({"action": "nested"})
        return ActionResult(True, affected=task, undo_available=True)


class FakeEvents:
    def __init__(self, undo):
        self.undo = undo
        self.calls = []

    def update(self, event_id, **changes):
        self.calls.append(("update", event_id, changes))
        return ActionResult(True, affected=Event(id=event_id, summary="Event"))

    def delete(self, event_id):
        self.calls.append(("delete", event_id))
        return ActionResult(True, affected=Event(id=event_id, summary="Event"))

    def create(self, event):
        self.calls.append(("create", event))
        return ActionResult(True, affected=event)


def test_undo_update_applies_before_snapshot_and_consumes_only_after_success():
    repo = MemoryRepo()
    undo = UndoManager(repo)
    tasks = FakeTasks(undo)
    events = FakeEvents(undo)
    undo.bind(tasks=tasks, events=events)
    undo.remember({"action": "task.update", "task_id": "t1", "before": {"due": date(2026, 8, 30)}})

    result = undo.undo_last()

    assert result.success is True
    assert result.message == "Undone."
    assert result.undo_available is False
    assert tasks.calls == [("update", "t1", {"due": date(2026, 8, 30)})]
    assert repo.items == []


def test_undo_delete_recreates_same_uid():
    repo = MemoryRepo()
    undo = UndoManager(repo)
    tasks = FakeTasks(undo)
    undo.bind(tasks=tasks, events=FakeEvents(undo))
    undo.remember({
        "action": "task.delete",
        "task_id": "same-uid",
        "task": {
            "id": "same-uid",
            "summary": "Report",
            "description": "",
            "start": None,
            "due": date(2026, 9, 1),
            "status": "NEEDS-ACTION",
            "completed": False,
            "completed_at": None,
            "priority": None,
            "categories": [],
        },
    })

    undo.undo_last()

    recreated = tasks.calls[0][1]
    assert recreated.id == "same-uid"
    assert recreated.due == date(2026, 9, 1)


def test_empty_undo_stack_uses_stable_not_found_error():
    undo = UndoManager(MemoryRepo())
    undo.bind(tasks=FakeTasks(undo), events=FakeEvents(undo))
    with pytest.raises(NotFoundError):
        undo.undo_last()


def test_sqlite_undo_round_trips_date_and_datetime(tmp_path):
    repo = SQLiteUndoRepository(SQLiteStore(tmp_path / "state.sqlite3"))
    when = datetime(2026, 8, 28, 12, 30, tzinfo=timezone.utc)
    due = date(2026, 9, 2)
    repo.remember({"action": "task.update", "before": {"start": when, "due": due}})

    entry = repo.latest()

    assert entry is not None
    assert entry["payload"]["before"]["start"] == when
    assert entry["payload"]["before"]["due"] == due
    repo.discard(entry["id"])
    assert repo.latest() is None
