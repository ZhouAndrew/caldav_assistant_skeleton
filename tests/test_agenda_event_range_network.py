from __future__ import annotations

from datetime import datetime, timedelta, timezone

from caldav_assistant.api import Event
from caldav_assistant.internal.agenda import AgendaEngine, AgendaService, NextEngine
from caldav_assistant.internal.caldav.routing import CollectionRoutingCalDAVAdapter


class Tasks:
    def __init__(self):
        self.calls = []

    def list(self, **filters):
        self.calls.append(filters)
        return []


class Events:
    def __init__(self):
        self.full_reads = 0
        self.range_reads = []

    def list(self, **filters):
        self.full_reads += 1
        return []

    def list_between(self, start, end, **filters):
        self.range_reads.append((start, end, filters))
        return []


class State:
    def get(self, key, default=None):
        return default


class Session:
    def startup_snapshot(self, tasks):
        return {
            "current_task_id": None,
            "current_task": None,
            "paused_task_ids": (),
        }

    def current_task_id(self):
        return None

    def paused_task_ids(self):
        return ()


def _agenda():
    tasks = Tasks()
    events = Events()
    service = AgendaService(
        tasks,
        events,
        AgendaEngine(),
        NextEngine(),
        State(),
        session=Session(),
    )
    return service, tasks, events


def test_today_and_range_use_bounded_event_reader_not_full_history():
    agenda, _tasks, events = _agenda()

    agenda.today()
    assert events.full_reads == 0
    assert len(events.range_reads) == 1
    start, end, filters = events.range_reads[-1]
    assert end - start == timedelta(days=1)
    assert start.hour == start.minute == start.second == 0
    assert filters == {}

    agenda.range(days=3)
    assert events.full_reads == 0
    assert len(events.range_reads) == 2
    start, end, _ = events.range_reads[-1]
    assert end - start == timedelta(days=3)


def test_default_startup_bounds_events_but_generic_next_keeps_broad_candidates():
    agenda, _tasks, events = _agenda()

    agenda.startup_snapshot(days=2, kind="task")
    assert events.full_reads == 0
    assert len(events.range_reads) == 1
    assert events.range_reads[0][1] - events.range_reads[0][0] == timedelta(days=2)

    agenda.next(kind=None)
    assert events.full_reads == 1


class Resource:
    def __init__(self, uid):
        self.uid = uid


class Calendar:
    def __init__(self, url):
        self.url = url
        self.search_calls = []

    def search(self, **kwargs):
        self.search_calls.append(kwargs)
        return [Resource("e1")]


class Client:
    def __init__(self, calendar):
        self._calendar = calendar

    def calendar(self, url):
        assert url.rstrip("/") == self._calendar.url.rstrip("/")
        return self._calendar


class Inner:
    base_url = "https://dav.example/"

    def __init__(self, calendar):
        self.calendar = calendar
        self.client = Client(calendar)

    def _client_now(self):
        return self.client

    @staticmethod
    def _to_event(resource, calendar):
        event = Event(
            id=resource.uid,
            summary="Meeting",
            start=datetime(2026, 9, 6, 9, 0, tzinfo=timezone.utc),
        )
        setattr(event, "_caldav_collection_url", calendar.url)
        return event

    def list_events(self, **filters):
        raise AssertionError("range path must not fall back to full Event list")


def test_collection_routing_translates_range_read_to_server_search():
    calendar = Calendar("https://dav.example/events/")
    inner = Inner(calendar)
    routed = CollectionRoutingCalDAVAdapter(
        inner,
        task_collection_url=lambda: "https://dav.example/tasks/",
        event_collection_url=lambda: calendar.url,
    )
    start = datetime(2026, 9, 6, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    values = routed.list_events_between(start, end)

    assert [event.id for event in values] == ["e1"]
    assert calendar.search_calls == [
        {
            "event": True,
            "start": start,
            "end": end,
            "expand": False,
        }
    ]
