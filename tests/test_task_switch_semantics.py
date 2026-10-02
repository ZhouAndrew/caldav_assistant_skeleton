from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from caldav_assistant.api import Event, Task
from caldav_assistant.api.v1.errors import ValidationError
from caldav_assistant.internal.cli import conversation_app
from caldav_assistant.internal.session.caldav import CalDAVSessionService
from caldav_assistant.internal.session.service import SessionService
from caldav_assistant.internal.tasks.service import TaskService
from caldav_assistant.internal.tasks.work_service import CalDAVWorkTaskService
from caldav_assistant.internal.worklog import WorkLogService


class Adapter:
    def __init__(self):
        self.tasks = {
            "a": Task(id="a", summary="Task A", status="NEEDS-ACTION"),
            "b": Task(id="b", summary="Task B", status="NEEDS-ACTION"),
        }
        self.events = {}
        self.next_event = 1

    def get_task(self, task_id):
        return self.tasks[str(task_id)]

    def list_tasks(self, **filters):
        values = list(self.tasks.values())
        status = filters.get("status")
        if status:
            values = [item for item in values if item.status == status]
        return values

    def update_task(self, task_id, changes, *, etag=None):
        task = self.tasks[str(task_id)]
        for key, value in changes.items():
            setattr(task, key, value)
        return task

    def create_event(self, event):
        event.id = f"work-{self.next_event}"
        self.next_event += 1
        self.events[event.id] = event
        return event

    def list_events_in_collection(self, collection_url, **filters):
        category = filters.get("category")
        values = list(self.events.values())
        if category:
            values = [
                item
                for item in values
                if category in set(getattr(item, "categories", ()) or ())
            ]
        return values

    def update_event_in_collection(self, collection_url, event_id, changes):
        event = self.events[str(event_id)]
        for key, value in changes.items():
            setattr(event, key, value)
        return event


class State:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


class Activity:
    def __init__(self):
        self.rows = []

    def record(self, action, object_id=None, **metadata):
        self.rows.append((action, object_id, metadata))


def test_switch_away_returns_old_task_to_incomplete_not_paused():
    adapter = Adapter()
    session = SessionService(State())
    activity = Activity()
    service = TaskService(adapter, activity=activity, session=session)
    session.bind_tasks(service)

    service.start("a")
    assert adapter.tasks["a"].status == "IN-PROCESS"
    assert session.current_task_id() == "a"

    service.switch_away("a")

    assert adapter.tasks["a"].status == "NEEDS-ACTION"
    assert adapter.tasks["a"].completed is False
    assert session.current_task_id() is None
    assert session.paused_task_ids() == ()
    assert activity.rows[-1][0] == "task_switched_away"
    with pytest.raises(ValidationError, match="paused"):
        service.resume("a")

    service.start("b")
    assert adapter.tasks["b"].status == "IN-PROCESS"
    assert session.current_task_id() == "b"
    assert adapter.tasks["a"].status == "NEEDS-ACTION"


def test_switch_away_closes_work_event_and_is_not_resumable_in_production_session():
    adapter = Adapter()
    activity = Activity()
    worklog = WorkLogService(
        adapter,
        lambda: "http://example.invalid/work/",
        clock=lambda: datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
    )
    service = CalDAVWorkTaskService(
        adapter,
        activity=activity,
        worklog=worklog,
    )
    session = CalDAVSessionService(worklog, tasks=service)
    service.session = session

    service.start("a")
    opened = next(iter(adapter.events.values()))
    assert WorkLogService.OPEN_CATEGORY in opened.categories
    assert session.current_task_id() == "a"

    service.switch_away("a")

    assert adapter.tasks["a"].status == "NEEDS-ACTION"
    assert session.current_task_id() is None
    assert session.paused_task_ids() == ()
    closed = adapter.events[opened.id]
    assert closed.end is not None
    assert WorkLogService.OPEN_CATEGORY not in closed.categories
    with pytest.raises(ValidationError):
        service.resume("a")

    service.start("b")
    assert session.current_task_id() == "b"
    assert adapter.tasks["a"].status == "NEEDS-ACTION"


def test_waiting_menu_routes_start_another_task_to_switch_flow(monkeypatch):
    current = Task(id="a", summary="Task A", status="IN-PROCESS")
    target = SimpleNamespace(summary="Task A", value=current)
    calls = []

    class UI:
        def choose(self, title, items, **kwargs):
            assert "Start another Task" in tuple(items)
            return "Start another Task"

    app = SimpleNamespace(ctx=SimpleNamespace(ui=UI()))
    monkeypatch.setattr(
        conversation_app,
        "_guided_switch",
        lambda app, selected: calls.append(selected) or "wait",
    )

    assert conversation_app._wait_interrupt(app, target) == "wait"
    assert calls == [current]
