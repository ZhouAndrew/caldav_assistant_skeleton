from __future__ import annotations

from datetime import datetime, timezone

from caldav_assistant.api import Event, Task
from caldav_assistant.internal.caldav.routing import CollectionRoutingCalDAVAdapter
from caldav_assistant.internal.tasks.work_service import CalDAVWorkTaskService
from caldav_assistant.internal.worklog.service import WorkLogService


WORK_URL = "https://dav.example/work/"
TASK_URL = "https://dav.example/tasks/"


class _SearchCalendar:
    url = WORK_URL

    def __init__(self, resource):
        self.resource = resource
        self.search_calls = []
        self.get_events_calls = 0

    def search(self, **kwargs):
        self.search_calls.append(kwargs)
        return [self.resource]

    def get_events(self):
        self.get_events_calls += 1
        raise AssertionError("category lookup must use server-side search")


class _SearchAdapter:
    base_url = "https://dav.example/"

    def __init__(self, calendar):
        self.calendar = calendar

    def _calendars(self):
        return [self.calendar]

    @staticmethod
    def _to_event(resource, calendar):
        event = Event(
            id=resource.id,
            summary=resource.summary,
            description=resource.description,
            categories=list(resource.categories),
        )
        setattr(event, "_caldav_collection_url", calendar.url)
        return event

    def list_events(self, **filters):
        raise AssertionError("configured Work collection must not use generic list_events")


def _open_event(event_id="w1", task_id="t1"):
    event = Event(
        id=event_id,
        summary="Work — Task",
        description=(
            f"{WorkLogService.DESCRIPTION_HEADER}\n"
            f"{WorkLogService.TASK_PREFIX}{task_id}"
        ),
        categories=[WorkLogService.CATEGORY, WorkLogService.OPEN_CATEGORY],
    )
    # Production LibraryCalDAVAdapter._to_event attaches the private collection
    # routing metadata. The test double must do the same or WorkLog correctly rejects
    # an event that cannot be proven to come from the configured Work collection.
    setattr(event, "_caldav_collection_url", WORK_URL)
    return event


def test_open_work_lookup_uses_server_side_category_search():
    calendar = _SearchCalendar(_open_event())
    routed = CollectionRoutingCalDAVAdapter(
        _SearchAdapter(calendar),
        task_collection_url=lambda: TASK_URL,
        event_collection_url=lambda: "https://dav.example/events/",
    )

    result = routed.list_events_in_collection(
        WORK_URL,
        category=WorkLogService.OPEN_CATEGORY,
    )

    assert [event.id for event in result] == ["w1"]
    assert calendar.search_calls == [
        {"event": True, "category": WorkLogService.OPEN_CATEGORY}
    ]
    assert calendar.get_events_calls == 0


class _ScopedWorkAdapter:
    def __init__(self):
        self.calls = []
        self.open = _open_event()

    def list_events_in_collection(self, collection_url, **filters):
        self.calls.append(("list", collection_url, filters))
        if filters.get("category") == WorkLogService.OPEN_CATEGORY:
            return [self.open]
        return [self.open]

    def update_event_in_collection(self, collection_url, event_id, changes, *, etag=None):
        self.calls.append(("update", collection_url, event_id, changes))
        return Event(
            id=event_id,
            summary=self.open.summary,
            start=self.open.start,
            end=changes.get("end"),
            description=self.open.description,
            categories=list(changes.get("categories", self.open.categories)),
        )

    def update_event(self, *args, **kwargs):
        raise AssertionError("Work update must stay in the configured Work collection")


def test_close_work_interval_reads_open_marker_and_updates_target_collection():
    adapter = _ScopedWorkAdapter()
    service = WorkLogService(
        adapter,
        lambda: WORK_URL,
        clock=lambda: datetime(2026, 8, 31, 3, 0, tzinfo=timezone.utc),
    )

    closed = service.close_segment("t1")

    assert closed is not None
    assert closed.end == datetime(2026, 8, 31, 3, 0, tzinfo=timezone.utc)
    assert adapter.calls[0] == (
        "list",
        WORK_URL,
        {"category": WorkLogService.OPEN_CATEGORY},
    )
    assert adapter.calls[1][0:3] == ("update", WORK_URL, "w1")


class _TaskAdapter:
    def __init__(self):
        self.updates = []

    def update_task(self, task_id, changes, *, etag=None):
        self.updates.append((task_id, dict(changes)))
        return Task(
            id=task_id,
            summary="Task",
            status=changes.get("status", "IN-PROCESS"),
            completed=bool(changes.get("completed", False)),
            completed_at=changes.get("completed_at"),
        )


class _LifecycleWorkLog:
    def __init__(self):
        self.started = 0
        self.closed = 0

    def configured(self):
        return True

    def start_segment(self, task):
        self.started += 1
        return Event(id="segment", summary="Work — Task")

    def close_segment(self, task, *, required=True):
        self.closed += 1
        return Event(id="segment", summary="Work — Task")

    def discard_segment(self, event):
        raise AssertionError("successful start must not roll back")


class _ExplodingSession:
    def current_task_id(self):
        raise AssertionError("lifecycle action must not pre-read current Work state")


def test_start_and_pause_do_not_pre_read_current_state_before_worklog_action():
    adapter = _TaskAdapter()
    worklog = _LifecycleWorkLog()
    service = CalDAVWorkTaskService(
        adapter,
        session=_ExplodingSession(),
        worklog=worklog,
    )

    started = service.start(Task(id="t1", summary="Task", status="NEEDS-ACTION"))
    paused = service.pause(Task(id="t1", summary="Task", status="IN-PROCESS"))

    assert started.success is True
    assert paused.success is True
    assert worklog.started == 1
    assert worklog.closed == 1
    assert len(adapter.updates) == 1
