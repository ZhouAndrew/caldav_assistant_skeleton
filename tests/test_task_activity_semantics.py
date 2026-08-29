from __future__ import annotations

from datetime import date, datetime

from caldav_assistant.api import Task
from caldav_assistant.internal.session import SessionService
from caldav_assistant.internal.tasks import TaskService


class Adapter:
    def __init__(self):
        self.item = Task(
            id="t1",
            summary="Report",
            start=date(2026, 8, 29),
            due=date(2026, 8, 30),
            priority=5,
        )

    def list_tasks(self, **filters):
        return [self.item]

    def get_task(self, task_id):
        assert task_id == "t1"
        return self.item

    def update_task(self, task_id, changes, *, etag=None):
        assert task_id == "t1"
        values = {
            key: value
            for key, value in self.item.__dict__.items()
            if key != "_service"
        }
        for key, value in changes.items():
            if key in values:
                values[key] = value
        self.item = Task(**values)
        return self.item

    def create_task(self, task):
        self.item = task
        self.item.id = "t1"
        return self.item

    def delete_task(self, task_id, *, etag=None):
        return None


class Activity:
    def __init__(self):
        self.entries = []

    def record(self, action, object_id=None, **metadata):
        self.entries.append((action, object_id, metadata))


class Undo:
    def remember(self, payload):
        return None


class State:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


def make_service():
    adapter = Adapter()
    activity = Activity()
    session = SessionService(State())
    service = TaskService(adapter, activity, Undo(), session)
    session.bind_tasks(service)
    return service, activity, session


def test_planning_fields_have_precise_activity_names_and_before_after_values():
    service, activity, _ = make_service()

    service.update("t1", start=date(2026, 9, 1))
    action, object_id, metadata = activity.entries[-1]
    assert action == "task_planned_start_changed"
    assert object_id == "t1"
    assert metadata["before"] == {"start": date(2026, 8, 29)}
    assert metadata["after"]["start"] == date(2026, 9, 1)

    service.update("t1", due=date(2026, 9, 2))
    action, _, metadata = activity.entries[-1]
    assert action == "task_due_changed"
    assert metadata["before"] == {"due": date(2026, 8, 30)}
    assert metadata["after"]["due"] == date(2026, 9, 2)

    service.update("t1", priority=2)
    action, _, metadata = activity.entries[-1]
    assert action == "task_priority_changed"
    assert metadata["before"] == {"priority": 5}
    assert metadata["after"]["priority"] == 2


def test_work_session_activity_records_transition_and_plan_snapshot():
    service, activity, session = make_service()

    service.start("t1")
    action, _, metadata = activity.entries[-1]
    assert action == "task_started"
    assert metadata["work_session_before"] == "none"
    assert metadata["work_session_after"] == "current"
    assert metadata["planned_start"] == date(2026, 8, 29)
    assert metadata["due"] == date(2026, 8, 30)
    assert metadata["priority"] == 5
    assert session.current_task_id() == "t1"

    service.pause("t1")
    action, _, metadata = activity.entries[-1]
    assert action == "task_paused"
    assert metadata["work_session_before"] == "current"
    assert metadata["work_session_after"] == "paused"
    assert session.paused_task_ids() == ("t1",)

    service.resume("t1")
    action, _, metadata = activity.entries[-1]
    assert action == "task_resumed"
    assert metadata["work_session_before"] == "paused"
    assert metadata["work_session_after"] == "current"
    assert session.current_task_id() == "t1"

    service.complete("t1")
    action, _, metadata = activity.entries[-1]
    assert action == "task_completed"
    assert metadata["work_session_before"] == "current"
    assert metadata["work_session_after"] == "none"
    assert session.current_task_id() is None


def test_generic_multi_field_edit_still_records_auditable_before_after():
    service, activity, _ = make_service()

    service.update("t1", summary="Final report", priority=1)

    action, _, metadata = activity.entries[-1]
    assert action == "task_updated"
    assert metadata["before"]["summary"] == "Report"
    assert metadata["before"]["priority"] == 5
    assert metadata["after"]["summary"] == "Final report"
    assert metadata["after"]["priority"] == 1
