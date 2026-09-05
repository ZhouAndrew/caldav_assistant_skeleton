from __future__ import annotations

import pytest

from caldav_assistant.api import Event, Task
from caldav_assistant.api.v1.errors import ValidationError
from caldav_assistant.internal.events import EventService
from caldav_assistant.internal.tasks.work_period_task_service import WorkPeriodAwareTaskService


class TaskAdapter:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.task = Task(
            id="t1",
            summary="Report",
            status="COMPLETED",
            completed=True,
        )

    def get_task(self, task_id: str) -> Task:
        self.calls.append(task_id)
        assert task_id == "t1"
        return self.task


class EventAdapter:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.event = Event(id="e1", summary="Authoritative title")

    def get_event(self, event_id: str) -> Event:
        self.calls.append(event_id)
        assert event_id == "e1"
        return self.event


def test_production_task_service_refreshes_detached_ipc_snapshot_before_lifecycle_check():
    adapter = TaskAdapter()
    service = WorkPeriodAwareTaskService(adapter, completion_log=object())
    stale_ipc_snapshot = Task(
        id="t1",
        summary="Report",
        status="NEEDS-ACTION",
        completed=False,
    )

    with pytest.raises(ValidationError, match="completed or cancelled"):
        service.start(stale_ipc_snapshot)

    assert adapter.calls == ["t1"]


def test_production_task_service_reuses_object_already_bound_to_itself():
    adapter = TaskAdapter()
    service = WorkPeriodAwareTaskService(adapter, completion_log=object())

    current = service.get("t1")
    assert service.get(current) is current
    assert adapter.calls == ["t1"]


def test_event_service_refreshes_detached_ipc_snapshot_from_caldav():
    adapter = EventAdapter()
    service = EventService(adapter)
    stale_ipc_snapshot = Event(id="e1", summary="Old title")

    current = service.get(stale_ipc_snapshot)

    assert current.summary == "Authoritative title"
    assert current is adapter.event
    assert adapter.calls == ["e1"]


def test_event_service_reuses_object_already_bound_to_itself():
    adapter = EventAdapter()
    service = EventService(adapter)

    current = service.get("e1")
    assert service.get(current) is current
    assert adapter.calls == ["e1"]
