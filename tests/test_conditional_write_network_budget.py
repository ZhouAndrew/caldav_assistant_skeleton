from __future__ import annotations

from caldav_assistant.api import Event, Task
from caldav_assistant.internal.caldav.conditional_write import (
    update_event_from_snapshot,
    update_task_from_snapshot,
)
from caldav_assistant.internal.caldav.routing import CollectionRoutingCalDAVAdapter


TASKS = "https://dav.example/tasks"
EVENTS = "https://dav.example/events"
ETAG = "{DAV:}getetag"


class ETagMismatchError(Exception):
    pass


class FakeResource:
    saves = []
    fail_next = False

    def __init__(self, client, *, url, data, parent, props):
        self.client = client
        self.url = url
        self.data = data
        self.parent = parent
        self.props = dict(props)
        self.summary = "Old"

    def save(self):
        FakeResource.saves.append((self.url, dict(self.props)))
        if FakeResource.fail_next:
            FakeResource.fail_next = False
            raise ETagMismatchError("stale")
        self.props[ETAG] = '"new-etag"'
        return self


class FakeCalendar:
    def __init__(self, url):
        self.url = url
        self.client = object()

    def _calendar_comp_class_by_data(self, raw):
        assert raw
        return FakeResource


class FakeInner:
    base_url = "https://dav.example"

    @staticmethod
    def _edit_task(resource, changes):
        if "summary" in changes:
            resource.summary = changes["summary"]

    @staticmethod
    def _edit_event(resource, changes):
        if "summary" in changes:
            resource.summary = changes["summary"]

    @staticmethod
    def _mapped(resource, cls):
        result = cls(id="x", summary=resource.summary, raw=resource.data)
        result._caldav_url = str(resource.url)
        result._caldav_collection_url = str(resource.parent.url)
        result._caldav_etag = resource.props.get(ETAG)
        return result

    def _to_task(self, resource, calendar):
        return self._mapped(resource, Task)

    def _to_event(self, resource, calendar):
        return self._mapped(resource, Event)


class Wrapper:
    def __init__(self, routed):
        self.adapter = routed
        self.task_fallbacks = 0
        self.event_fallbacks = 0
        self.patches = []

    def update_task(self, task_id, changes, **kwargs):
        self.task_fallbacks += 1
        return Task(id=task_id, summary=changes.get("summary", "fallback"))

    def update_event(self, event_id, changes, **kwargs):
        self.event_fallbacks += 1
        return Event(id=event_id, summary=changes.get("summary", "fallback"))

    def _patch_snapshot(self, kind, *, obj):
        self.patches.append((kind, obj.id))


def _stack():
    inner = FakeInner()
    routed = CollectionRoutingCalDAVAdapter(
        inner,
        task_collection_url=lambda: TASKS,
        event_collection_url=lambda: EVENTS,
    )
    calendars = {TASKS: FakeCalendar(TASKS), EVENTS: FakeCalendar(EVENTS)}
    routed._selected_calendar = lambda url: calendars[str(url).rstrip("/")]
    return Wrapper(routed)


def _live_task():
    task = Task(id="x", summary="Old", raw="BEGIN:VCALENDAR\nBEGIN:VTODO\nEND:VTODO\nEND:VCALENDAR")
    task._caldav_url = f"{TASKS}/x.ics"
    task._caldav_collection_url = TASKS
    task._caldav_etag = '"old-etag"'
    return task


def _live_event():
    event = Event(id="x", summary="Old", raw="BEGIN:VCALENDAR\nBEGIN:VEVENT\nEND:VEVENT\nEND:VCALENDAR")
    event._caldav_url = f"{EVENTS}/x.ics"
    event._caldav_collection_url = EVENTS
    event._caldav_etag = '"old-etag"'
    return event


def setup_function():
    FakeResource.saves = []
    FakeResource.fail_next = False


def test_live_task_snapshot_writes_once_with_if_match_without_fallback_read():
    wrapper = _stack()
    updated = update_task_from_snapshot(wrapper, _live_task(), {"summary": "New"})

    assert updated is not None
    assert updated.summary == "New"
    assert updated._caldav_etag == '"new-etag"'
    assert wrapper.task_fallbacks == 0
    assert wrapper.patches == [("task", "x")]
    assert FakeResource.saves == [
        (f"{TASKS}/x.ics", {ETAG: '"old-etag"'})
    ]


def test_live_event_snapshot_writes_once_with_if_match_without_fallback_read():
    wrapper = _stack()
    updated = update_event_from_snapshot(wrapper, _live_event(), {"summary": "New"})

    assert updated is not None
    assert updated.summary == "New"
    assert wrapper.event_fallbacks == 0
    assert wrapper.patches == [("event", "x")]
    assert FakeResource.saves[0][1][ETAG] == '"old-etag"'


def test_missing_raw_or_transport_metadata_preserves_ordinary_update_path():
    wrapper = _stack()
    task = _live_task()
    task.raw = None

    assert update_task_from_snapshot(wrapper, task, {"summary": "New"}) is None
    assert wrapper.task_fallbacks == 0
    assert FakeResource.saves == []


def test_stale_fast_write_falls_back_to_old_fresh_read_update_semantics():
    wrapper = _stack()
    FakeResource.fail_next = True

    updated = update_task_from_snapshot(wrapper, _live_task(), {"summary": "Merged"})

    assert updated is not None
    assert updated.summary == "Merged"
    assert wrapper.task_fallbacks == 1
    # The ordinary fallback wrapper owns its own cache patching in production; the
    # fast helper must not patch a second time after returning from that path.
    assert wrapper.patches == []
    assert len(FakeResource.saves) == 1


def test_resource_url_outside_claimed_collection_never_uses_fast_write():
    wrapper = _stack()
    task = _live_task()
    task._caldav_url = "https://evil.example/x.ics"

    assert update_task_from_snapshot(wrapper, task, {"summary": "No"}) is None
    assert FakeResource.saves == []
