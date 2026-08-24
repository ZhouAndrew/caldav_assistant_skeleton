from __future__ import annotations

from datetime import date

import pytest

from caldav_assistant.api import ActionResult, Task
from caldav_assistant.api.v1.errors import (
    AmbiguousError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from caldav_assistant.internal.tasks import TaskService


class FakeAdapter:
    def __init__(self):
        self.items = {
            "1": Task(id="1", summary="Report"),
            "2": Task(id="2", summary="Report notes"),
        }
        self.calls = []
        self.fail_update = False

    def list_tasks(self, **filters):
        return list(self.items.values())

    def get_task(self, task_id):
        if task_id not in self.items:
            raise KeyError(task_id)
        return self.items[task_id]

    def create_task(self, task):
        self.calls.append(("create", task))
        created = Task(
            **{
                key: value
                for key, value in task.__dict__.items()
                if key != "_service"
            }
        )
        created.id = "3"
        self.items[created.id] = created
        return created

    def update_task(self, task_id, changes, *, etag=None):
        self.calls.append(("update", task_id, changes))
        if self.fail_update:
            raise ConflictError(task_id)

        old = self.items[task_id]
        values = {
            key: value
            for key, value in old.__dict__.items()
            if key != "_service"
        }
        for key, value in changes.items():
            if hasattr(old, key):
                values[key] = value
        updated = Task(**values)
        self.items[task_id] = updated
        return updated

    def delete_task(self, task_id, *, etag=None):
        self.calls.append(("delete", task_id))
        del self.items[task_id]


class FakeActivity:
    def __init__(self):
        self.calls = []

    def record(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class FakeUndo:
    def __init__(self):
        self.calls = []

    def remember(self, payload):
        self.calls.append(payload)


def make_service():
    adapter = FakeAdapter()
    activity = FakeActivity()
    undo = FakeUndo()
    return (
        TaskService(adapter, activity, undo),
        adapter,
        activity,
        undo,
    )


def test_list_binds_service_and_find_prefers_exact_match():
    service, _, _, _ = make_service()

    items = service.list()

    assert items[0]._service is service
    assert service.find("report").id == "1"


def test_find_uses_stable_public_errors():
    service, _, _, _ = make_service()

    with pytest.raises(NotFoundError):
        service.find("missing")

    with pytest.raises(AmbiguousError):
        service.find("repo")

    with pytest.raises(ValidationError):
        service.find(" ")


def test_create_returns_action_result_and_records_side_effects():
    service, _, activity, undo = make_service()

    result = service.create(" New task ")

    assert isinstance(result, ActionResult)
    assert result.success is True
    assert result.affected.summary == "New task"
    assert result.affected._service is service
    assert result.undo_available is True
    assert activity.calls[-1][0][0] == "task_created"
    assert undo.calls[-1]["action"] == "task.create"


def test_update_does_not_mutate_before_authoritative_write_succeeds():
    service, adapter, _, _ = make_service()
    task = service.get("1")
    adapter.fail_update = True

    with pytest.raises(ConflictError):
        service.update(task, summary="Changed")

    assert task.summary == "Report"


def test_due_update_records_specific_activity():
    service, _, activity, _ = make_service()

    result = service.update("1", due=date(2026, 8, 30))

    assert result.affected.due == date(2026, 8, 30)
    assert activity.calls[-1][0][0] == "task_due_changed"


def test_complete_writes_standard_vtodo_completion_fields():
    service, adapter, activity, _ = make_service()

    result = service.complete("1")
    changes = adapter.calls[-1][2]

    assert changes["status"] == "COMPLETED"
    assert changes["completed"] is True
    assert changes["completed_at"].tzinfo is not None
    assert result.affected.status == "COMPLETED"
    assert activity.calls[-1][0][0] == "task_completed"


def test_pause_is_task_business_state_not_sync_state():
    service, adapter, activity, _ = make_service()

    service.start("1")
    result = service.pause("1")

    assert adapter.calls[-1][2] == {
        "X-CALDAV-ASSISTANT-PAUSED": True
    }
    assert result.undo_available is False
    assert activity.calls[-1][0][0] == "task_paused"


def test_delete_records_snapshot_for_undo():
    service, adapter, activity, undo = make_service()

    result = service.delete("1")

    assert "1" not in adapter.items
    assert result.undo_available is True
    assert undo.calls[-1]["action"] == "task.delete"
    assert undo.calls[-1]["task"]["summary"] == "Report"
    assert activity.calls[-1][0][0] == "task_deleted"