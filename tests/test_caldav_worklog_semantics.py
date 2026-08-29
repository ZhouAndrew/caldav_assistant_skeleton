from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from caldav_assistant.api import Event, Task
from caldav_assistant.api.v1.errors import AmbiguousError, ValidationError
from caldav_assistant.internal.session import CalDAVSessionService
from caldav_assistant.internal.tasks import CalDAVWorkTaskService
from caldav_assistant.internal.worklog import WorkLogService


class Adapter:
    def __init__(self):
        self.task = Task(id="t1", summary="Report", status="NEEDS-ACTION")
        self.events: list[Event] = []
        self.created_collection_urls: list[str | None] = []
        self.next_event_id = 1

    def get_task(self, task_id):
        assert task_id == "t1"
        return self.task

    def list_tasks(self, **filters):
        items = [self.task]
        for key, value in filters.items():
            items = [item for item in items if getattr(item, key) == value]
        return items

    def update_task(self, task_id, changes, *, etag=None):
        values = {
            key: value
            for key, value in self.task.__dict__.items()
            if not key.startswith("_")
        }
        values.update({key: value for key, value in changes.items() if key in values})
        self.task = Task(**values)
        return self.task

    def create_task(self, task):
        raise AssertionError("not used")

    def delete_task(self, task_id, *, etag=None):
        raise AssertionError("not used")

    def list_events(self, **filters):
        result = list(self.events)
        category = filters.get("category")
        if category is not None:
            result = [event for event in result if category in event.categories]
        return result

    def create_event(self, event):
        copied = replace(event, id=f"w{self.next_event_id}", categories=list(event.categories))
        self.next_event_id += 1
        url = getattr(event, "_caldav_collection_url", None)
        if url is not None:
            setattr(copied, "_caldav_collection_url", url)
        self.created_collection_urls.append(url)
        self.events.append(copied)
        return copied

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
            url = getattr(event, "_caldav_collection_url", None)
            if url is not None:
                setattr(updated, "_caldav_collection_url", url)
            self.events[index] = updated
            return updated
        raise KeyError(event_id)

    def delete_event(self, event_id, *, etag=None):
        self.events = [event for event in self.events if event.id != event_id]


class Activity:
    def __init__(self):
        self.records = []

    def record(self, action, object_id=None, **metadata):
        self.records.append((action, object_id, metadata))


class Clock:
    def __init__(self):
        self.value = datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, minutes):
        self.value += timedelta(minutes=minutes)


def build():
    adapter = Adapter()
    activity = Activity()
    clock = Clock()
    worklog = WorkLogService(adapter, lambda: "https://dav.example/work/", clock=clock)
    session = CalDAVSessionService(worklog)
    service = CalDAVWorkTaskService(adapter, activity, None, session, worklog=worklog)
    session.bind_tasks(service)
    return adapter, activity, clock, worklog, session, service


def test_work_intervals_live_in_selected_caldav_collection_and_drive_session_state():
    adapter, activity, clock, worklog, session, service = build()

    service.start("t1")
    assert adapter.task.status == "IN-PROCESS"
    assert session.current_task_id() == "t1"
    assert adapter.created_collection_urls == ["https://dav.example/work/"]
    assert len(adapter.events) == 1
    assert adapter.events[0].start == datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc)
    assert adapter.events[0].end is None
    assert WorkLogService.CATEGORY in adapter.events[0].categories
    assert WorkLogService.OPEN_CATEGORY in adapter.events[0].categories

    clock.advance(30)
    service.pause("t1")
    assert session.current_task_id() is None
    assert session.paused_task_ids() == ("t1",)
    assert adapter.events[0].end == datetime(2026, 8, 29, 10, 30, tzinfo=timezone.utc)

    clock.advance(30)
    service.resume("t1")
    assert session.current_task_id() == "t1"
    assert len(adapter.events) == 2
    assert adapter.events[1].start == datetime(2026, 8, 29, 11, 0, tzinfo=timezone.utc)

    clock.advance(60)
    service.complete("t1")
    assert adapter.task.status == "COMPLETED"
    assert session.current_task_id() is None
    assert adapter.events[1].end == datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)

    # Work VEVENTs retain detailed cross-device intervals, while the Activity
    # Journal also keeps the lightweight lifecycle history required by the public
    # Activity API and recovery/context features.
    actions = [row[0] for row in activity.records]
    assert actions == [
        "task_started",
        "task_paused",
        "task_resumed",
        "task_completed",
    ]


def test_worklog_refuses_to_guess_collection():
    adapter = Adapter()
    worklog = WorkLogService(adapter, lambda: None)

    with pytest.raises(ValidationError, match="Work log collection is not configured"):
        worklog.start_segment(adapter.task)

    assert adapter.events == []


def test_multiple_open_caldav_work_intervals_are_reported_not_guessed():
    adapter = Adapter()
    worklog = WorkLogService(adapter, lambda: "https://dav.example/work/")
    for uid in ("t1", "t2"):
        event = Event(
            id=f"w-{uid}",
            summary=f"Work — {uid}",
            start=datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc),
            end=None,
            description=worklog._description(uid),
            categories=[worklog.CATEGORY, worklog.OPEN_CATEGORY],
        )
        setattr(event, "_caldav_collection_url", "https://dav.example/work/")
        adapter.events.append(event)

    with pytest.raises(AmbiguousError, match="More than one open CalDAV work interval"):
        worklog.current_task_id()


def test_worklog_ignores_marker_events_from_other_collections():
    adapter = Adapter()
    worklog = WorkLogService(adapter, lambda: "https://dav.example/work/")
    event = Event(
        id="foreign",
        summary="Work — Report",
        start=datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc),
        end=None,
        description=worklog._description("t1"),
        categories=[worklog.CATEGORY, worklog.OPEN_CATEGORY],
    )
    setattr(event, "_caldav_collection_url", "https://dav.example/personal/")
    adapter.events.append(event)

    assert worklog.current_task_id() is None
