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
from caldav_assistant.internal.session import SessionService
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
        items = list(self.items.values())
        for key, wanted in filters.items():
            items = [item for item in items if getattr(item, key) == wanted]
        return items

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


class MemoryState:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


def make_service(*, with_session=False):
    adapter = FakeAdapter()
    activity = FakeActivity()
    undo = FakeUndo()
    state = MemoryState() if with_session else None
    session = SessionService(state) if with_session else None
    service = TaskService(adapter, activity, undo, session)
    if session is not None:
        session.bind_tasks(service)
    return service, adapter, activity, undo, session


def test_list_binds_service_and_find_prefers_exact_match():
    service, _, _, _, _ = make_service()

    items = service.list()

    assert items[0]._service is service
    assert service.find("report").id == "1"


def test_find_uses_stable_public_errors():
    service, _, _, _, _ = make_service()

    with pytest.raises(NotFoundError):
        service.find("missing")

    with pytest.raises(AmbiguousError):
        service.find("repo")

    with pytest.raises(ValidationError):
        service.find(" ")


def test_create_returns_action_result_and_records_side_effects():
    service, _, activity, undo, _ = make_service()

    result = service.create(" New task ")

    assert isinstance(result, ActionResult)
    assert result.success is True
    assert result.affected.summary == "New task"
    assert result.affected._service is service
    assert result.undo_available is True
    assert activity.calls[-1][0][0] == "task_created"
    assert undo.calls[-1]["action"] == "task.create"


def test_update_does_not_mutate_before_authoritative_write_succeeds():
    service, adapter, _, _, _ = make_service()
    task = service.get("1")
    adapter.fail_update = True

    with pytest.raises(ConflictError):
        service.update(task, summary="Changed")

    assert task.summary == "Report"


def test_due_update_records_specific_activity():
    service, _, activity, _, _ = make_service()

    result = service.update("1", due=date(2026, 8, 30))

    assert result.affected.due == date(2026, 8, 30)
    assert activity.calls[-1][0][0] == "task_due_changed"


def test_complete_writes_standard_vtodo_completion_fields():
    service, adapter, activity, _, _ = make_service()

    result = service.complete("1")
    changes = adapter.calls[-1][2]

    assert changes["status"] == "COMPLETED"
    assert changes["completed"] is True
    assert changes["completed_at"].tzinfo is not None
    assert result.affected.status == "COMPLETED"
    assert activity.calls[-1][0][0] == "task_completed"


def test_planned_task_cannot_be_paused():
    service, adapter, _, _, session = make_service(with_session=True)

    with pytest.raises(ValidationError, match="planned Task"):
        service.pause("1")

    assert session.current_task_id() is None
    assert session.paused_task_ids() == ()
    assert adapter.calls == []


def test_start_pause_resume_tracks_human_work_session():
    service, adapter, activity, _, session = make_service(with_session=True)

    started = service.start("1")
    assert started.affected.status == "IN-PROCESS"
    assert session.current_task_id() == "1"
    assert session.paused_task_ids() == ()
    assert adapter.calls[-1][2]["status"] == "IN-PROCESS"

    writes_before_pause = len(adapter.calls)
    paused = service.pause("1")
    assert paused.success is True
    assert len(adapter.calls) == writes_before_pause
    assert session.current_task_id() is None
    assert session.paused_task_ids() == ("1",)
    assert activity.calls[-1][0][0] == "task_paused"

    resumed = service.resume("1")
    assert resumed.success is True
    assert session.current_task_id() == "1"
    assert session.paused_task_ids() == ()
    assert adapter.calls[-1][2]["status"] == "IN-PROCESS"
    assert activity.calls[-1][0][0] == "task_resumed"


def test_only_current_work_can_be_paused_and_only_paused_work_resumed():
    service, _, _, _, session = make_service(with_session=True)

    service.start("1")

    with pytest.raises(ValidationError, match="planned Task"):
        service.pause("2")

    with pytest.raises(ValidationError, match="Another Task"):
        service.resume("2")

    service.pause("1")
    with pytest.raises(ValidationError, match="previously paused"):
        service.resume("2")

    assert session.paused_task_ids() == ("1",)


def test_starting_second_task_requires_finishing_or_pausing_current_work():
    service, _, _, _, session = make_service(with_session=True)

    service.start("1")

    with pytest.raises(ValidationError, match="Another Task"):
        service.start("2")

    assert session.current_task_id() == "1"


def test_completing_current_task_clears_work_session():
    service, _, _, _, session = make_service(with_session=True)

    service.start("1")
    service.complete("1")

    assert session.current_task_id() is None
    assert session.paused_task_ids() == ()


def test_delete_records_snapshot_for_undo_and_clears_session():
    service, adapter, activity, undo, session = make_service(with_session=True)
    service.start("1")

    result = service.delete("1")

    assert "1" not in adapter.items
    assert result.undo_available is True
    assert undo.calls[-1]["action"] == "task.delete"
    assert undo.calls[-1]["task"]["summary"] == "Report"
    assert activity.calls[-1][0][0] == "task_deleted"
    assert session.current_task_id() is None
