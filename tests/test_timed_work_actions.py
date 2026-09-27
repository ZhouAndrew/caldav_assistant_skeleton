from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from caldav_assistant.api import Event, Task
from caldav_assistant.api.v1.errors import ValidationError
from caldav_assistant.internal.activity import ActivityService
from caldav_assistant.internal.session import CalDAVSessionService
from caldav_assistant.internal.tasks import CalDAVWorkTaskService
from caldav_assistant.internal.worklog import WorkLogService


class Adapter:
    def __init__(self):
        self.task = Task(id="t1", summary="Prepare Python course", status="NEEDS-ACTION")
        self.events: list[Event] = []
        self.next_id = 1

    def get_task(self, task_id):
        assert task_id == "t1"
        return self.task

    def list_tasks(self, **filters):
        values = [self.task]
        for key, value in filters.items():
            values = [item for item in values if getattr(item, key) == value]
        return values

    def update_task(self, task_id, changes, *, etag=None):
        values = {
            key: value
            for key, value in self.task.__dict__.items()
            if not key.startswith("_")
        }
        values.update({key: value for key, value in changes.items() if key in values})
        self.task = Task(**values)
        return self.task

    def list_events(self, **filters):
        values = list(self.events)
        category = filters.get("category")
        if category is not None:
            values = [item for item in values if category in item.categories]
        return values

    def create_event(self, event):
        value = replace(event, id=f"w{self.next_id}", categories=list(event.categories))
        self.next_id += 1
        setattr(value, "_caldav_collection_url", "https://dav.example/work/")
        self.events.append(value)
        return value

    def update_event(self, event_id, changes, *, etag=None):
        for index, event in enumerate(self.events):
            if event.id != event_id:
                continue
            values = {
                key: value
                for key, value in event.__dict__.items()
                if not key.startswith("_")
            }
            values.update({key: value for key, value in changes.items() if key in values})
            updated = Event(**values)
            setattr(updated, "_caldav_collection_url", "https://dav.example/work/")
            self.events[index] = updated
            return updated
        raise KeyError(event_id)


class ActivityRepo:
    def __init__(self):
        self.rows = []

    def record(self, timestamp, action, object_id, metadata):
        self.rows.append((timestamp, action, object_id, metadata))

    def between(self, start, end):
        return []

    def for_object(self, object_id):
        return []


def build():
    adapter = Adapter()
    repo = ActivityRepo()
    activity = ActivityService(repo)
    worklog = WorkLogService(adapter, lambda: "https://dav.example/work/")
    session = CalDAVSessionService(worklog, activity=activity)
    service = CalDAVWorkTaskService(
        adapter,
        activity,
        None,
        session,
        worklog=worklog,
    )
    session.bind_tasks(service)
    return adapter, repo, worklog, service


def test_user_times_define_each_work_event_and_cancel_preserves_history():
    adapter, repo, _, service = build()
    t0 = datetime(2026, 9, 27, 9, 20, tzinfo=timezone.utc)
    t1 = datetime(2026, 9, 27, 10, 5, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 27, 10, 30, tzinfo=timezone.utc)
    t3 = datetime(2026, 9, 27, 11, 10, tzinfo=timezone.utc)

    service.start("t1", at=t0.isoformat())
    service.pause("t1", at=t1.isoformat())
    service.resume("t1", at=t2.isoformat())
    service.cancel("t1", at=t3.isoformat())

    assert adapter.task.status == "CANCELLED"
    assert [(item.start, item.end) for item in adapter.events] == [
        (t0, t1),
        (t2, t3),
    ]
    assert [row[0] for row in repo.rows] == [t0, t1, t2, t3]
    assert [row[1] for row in repo.rows] == [
        "task_started",
        "task_paused",
        "task_resumed",
        "task_cancelled",
    ]


def test_complete_uses_same_user_time_for_event_end_and_vtodo_completed_at():
    adapter, repo, _, service = build()
    start = datetime(2026, 9, 27, 13, 40, tzinfo=timezone.utc)
    end = datetime(2026, 9, 27, 14, 25, tzinfo=timezone.utc)

    service.start("t1", at=start)
    service.complete("t1", at=end)

    assert adapter.task.status == "COMPLETED"
    assert adapter.task.completed is True
    assert adapter.task.completed_at == end
    assert adapter.events[0].start == start
    assert adapter.events[0].end == end
    assert repo.rows[-1][0] == end
    assert repo.rows[-1][1] == "task_completed"


def test_end_before_start_is_rejected_without_rewriting_the_open_event():
    adapter, _, _, service = build()
    start = datetime(2026, 9, 27, 10, 0, tzinfo=timezone.utc)
    service.start("t1", at=start)

    with pytest.raises(ValidationError, match="earlier than its start"):
        service.pause(
            "t1",
            at=datetime(2026, 9, 27, 9, 59, tzinfo=timezone.utc),
        )

    assert adapter.events[0].start == start
    assert adapter.events[0].end is None
