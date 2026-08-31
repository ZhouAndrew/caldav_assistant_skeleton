from __future__ import annotations

from datetime import datetime, timezone

from caldav_assistant.api import Event, Task
from caldav_assistant.internal.caldav.routing import CollectionRoutingCalDAVAdapter
from caldav_assistant.internal.worklog.service import WorkLogService


class Resource:
    def __init__(self, uid, *, summary="Item", etag="v1"):
        self.uid = uid
        self.summary = summary
        self.etag = etag
        self.saved = 0
        self.deleted = 0
        self.changes = {}

    def save(self):
        self.saved += 1

    def delete(self):
        self.deleted += 1


class Calendar:
    def __init__(self, url):
        self.url = url
        self.todos = {}
        self.events = {}
        self.todo_gets = []
        self.event_gets = []
        self.added_events = 0

    def get_todo_by_uid(self, uid):
        self.todo_gets.append(uid)
        return self.todos[uid]

    def get_event_by_uid(self, uid):
        self.event_gets.append(uid)
        return self.events[uid]

    def add_event(self, **kwargs):
        self.added_events += 1
        uid = kwargs.get("uid") or f"created-{self.added_events}"
        resource = Resource(uid, summary=kwargs["summary"])
        resource.changes.update(kwargs)
        self.events[uid] = resource
        return resource


class ConcreteAdapter:
    base_url = "https://dav.example/"

    def __init__(self, calendars):
        self.calendars = list(calendars)
        self.discovery_calls = 0
        self.generic_task_updates = 0
        self.generic_event_updates = 0
        self.generic_event_creates = 0
        self.generic_deletes = 0

    def _calendars(self):
        self.discovery_calls += 1
        return list(self.calendars)

    @staticmethod
    def _check_etag(resource, expected):
        if expected is not None:
            assert resource.etag == expected

    @staticmethod
    def _edit_task(resource, changes):
        resource.changes.update(changes)
        if "summary" in changes:
            resource.summary = changes["summary"]

    @staticmethod
    def _edit_event(resource, changes):
        resource.changes.update(changes)

    @staticmethod
    def _to_task(resource, calendar):
        task = Task(id=resource.uid, summary=resource.summary)
        setattr(task, "_caldav_collection_url", calendar.url)
        return task

    @staticmethod
    def _to_event(resource, calendar):
        event = Event(id=resource.uid, summary=resource.summary)
        setattr(event, "_caldav_collection_url", calendar.url)
        return event

    def update_task(self, *args, **kwargs):
        self.generic_task_updates += 1
        raise AssertionError("selected Task update must not use generic cross-calendar find")

    def update_event(self, *args, **kwargs):
        self.generic_event_updates += 1
        raise AssertionError("selected Event update must not use generic cross-calendar find")

    def create_event(self, *args, **kwargs):
        self.generic_event_creates += 1
        raise AssertionError("explicit Work collection create must not scan compatible calendars")

    def delete_event(self, *args, **kwargs):
        self.generic_deletes += 1
        raise AssertionError("scoped Work delete must not use generic cross-calendar find")


def _routed():
    tasks = Calendar("https://dav.example/tasks/")
    events = Calendar("https://dav.example/events/")
    work = Calendar("https://dav.example/work/")
    decoy = Calendar("https://dav.example/decoy/")
    tasks.todos["t1"] = Resource("t1", summary="Old")
    events.events["e1"] = Resource("e1", summary="Event")
    work.events["w1"] = Resource("w1", summary="Work")
    inner = ConcreteAdapter([tasks, events, work, decoy])
    routed = CollectionRoutingCalDAVAdapter(
        inner,
        task_collection_url=lambda: tasks.url,
        event_collection_url=lambda: events.url,
    )
    return routed, inner, tasks, events, work, decoy


def test_selected_task_and_event_updates_do_not_cross_scan_collections():
    routed, inner, tasks, events, work, decoy = _routed()

    task = routed.update_task("t1", {"summary": "New"}, etag="v1")
    event = routed.update_event("e1", {"location": "Room"}, etag="v1")

    assert task.summary == "New"
    assert event.id == "e1"
    assert tasks.todo_gets == ["t1"]
    assert events.event_gets == ["e1"]
    assert work.todo_gets == [] and work.event_gets == []
    assert decoy.todo_gets == [] and decoy.event_gets == []
    assert inner.discovery_calls == 1
    assert inner.generic_task_updates == 0
    assert inner.generic_event_updates == 0


def test_explicit_work_collection_create_update_delete_stays_scoped():
    routed, inner, _tasks, events, work, decoy = _routed()
    event = Event(
        id="w2",
        summary="Work — Task",
        start=datetime.now(timezone.utc),
        categories=[WorkLogService.CATEGORY, WorkLogService.OPEN_CATEGORY],
    )
    setattr(event, "_caldav_collection_url", work.url)

    created = routed.create_event(event)
    updated = routed.update_event_in_collection(
        work.url,
        created.id,
        {"categories": [WorkLogService.CATEGORY]},
        etag="v1",
    )
    routed.delete_event_in_collection(work.url, created.id, etag="v1")

    assert created.id == "w2"
    assert updated.id == "w2"
    assert work.added_events == 1
    assert work.event_gets == ["w2", "w2"]
    assert events.event_gets == []
    assert decoy.event_gets == []
    assert inner.generic_event_creates == 0
    assert inner.generic_event_updates == 0
    assert inner.generic_deletes == 0
    assert work.events["w2"].saved == 1
    assert work.events["w2"].deleted == 1
