from __future__ import annotations

from caldav_assistant.api import Event, Task
from caldav_assistant.internal.caldav.sync import SyncEngine
from caldav_assistant.internal.caldav.sync_token import (
    SyncTokenStale,
    SyncTokenTransport,
    SyncTokenUnavailable,
)


TASKS_URL = "https://dav.example/tasks"
EVENTS_URL = "https://dav.example/events"


class MemoryCache:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


def _task(uid: str, summary: str) -> Task:
    item = Task(id=uid, summary=summary)
    item._caldav_url = f"{TASKS_URL}/{uid}.ics"
    item._caldav_collection_url = TASKS_URL
    return item


def _event(uid: str, summary: str) -> Event:
    item = Event(id=uid, summary=summary)
    item._caldav_url = f"{EVENTS_URL}/{uid}.ics"
    item._caldav_collection_url = EVENTS_URL
    return item


class CountingAdapter:
    def __init__(self):
        self.tasks = [_task("t1", "One")]
        self.events = [_event("e1", "Event")]
        self.task_reads = 0
        self.event_reads = 0
        self.order = []

    def list_tasks(self):
        self.task_reads += 1
        self.order.append("tasks")
        return list(self.tasks)

    def list_events(self):
        self.event_reads += 1
        self.order.append("events")
        return list(self.events)


class FakeTokenTransport:
    def __init__(self, adapter):
        self.adapter = adapter
        self.urls = {"tasks": TASKS_URL, "events": EVENTS_URL}
        self.seed_calls = 0
        self.change_calls = 0
        self.seed_error = None
        self.change_error = None
        self.next_changes = {
            "role_urls": dict(self.urls),
            "tokens": {TASKS_URL: "t2", EVENTS_URL: "e2"},
            "tasks": [],
            "events": [],
            "deleted_urls": [],
        }

    def role_urls(self):
        return dict(self.urls)

    def available(self):
        return True

    def seed(self):
        self.seed_calls += 1
        self.adapter.order.append("seed")
        if self.seed_error:
            raise self.seed_error
        return {
            "role_urls": dict(self.urls),
            "tokens": {TASKS_URL: f"t-seed-{self.seed_calls}", EVENTS_URL: f"e-seed-{self.seed_calls}"},
        }

    def changes(self, state):
        self.change_calls += 1
        if self.change_error:
            raise self.change_error
        result = dict(self.next_changes)
        result["role_urls"] = dict(self.urls)
        return result


def _engine():
    cache = MemoryCache()
    adapter = CountingAdapter()
    engine = SyncEngine(adapter, cache)
    tokens = FakeTokenTransport(adapter)
    engine._token_transport = tokens
    return engine, adapter, cache, tokens


def test_first_incremental_seeds_token_before_full_snapshot_then_no_change_avoids_full_reads():
    engine, adapter, _cache, tokens = _engine()

    first = engine.incremental_sync()
    assert first["effective_mode"] == "full-scan"
    assert adapter.order[:3] == ["seed", "tasks", "events"]
    assert adapter.task_reads == 1
    assert adapter.event_reads == 1

    adapter.order.clear()
    second = engine.incremental_sync()
    assert second["effective_mode"] == "sync-token"
    assert adapter.task_reads == 1
    assert adapter.event_reads == 1
    assert tokens.change_calls == 1
    assert adapter.order == []


def test_sync_token_delta_merges_updates_additions_and_deletions_without_full_scan():
    engine, adapter, _cache, tokens = _engine()
    engine.incremental_sync()

    changed = _task("t1", "One changed")
    added = _task("t2", "Two")
    tokens.next_changes = {
        "role_urls": dict(tokens.urls),
        "tokens": {TASKS_URL: "t-next", EVENTS_URL: "e-next"},
        "tasks": [changed, added],
        "events": [],
        "deleted_urls": [f"{EVENTS_URL}/e1.ics"],
    }

    report = engine.incremental_sync()
    assert report["effective_mode"] == "sync-token"
    assert report["changes"]["tasks"] == {
        "added": ["t2"],
        "updated": ["t1"],
        "removed": [],
    }
    assert report["changes"]["events"] == {
        "added": [],
        "updated": [],
        "removed": ["e1"],
    }
    assert [item.id for item in engine.cached_tasks()] == ["t1", "t2"]
    assert engine.cached_events() == []
    assert adapter.task_reads == 1
    assert adapter.event_reads == 1


def test_stale_token_reseeds_before_safe_full_scan():
    engine, adapter, cache, tokens = _engine()
    engine.incremental_sync()
    previous_seed_calls = tokens.seed_calls
    tokens.change_error = SyncTokenStale("expired")
    adapter.tasks = [_task("t1", "Server truth")]

    adapter.order.clear()
    report = engine.incremental_sync()
    assert report["effective_mode"] == "full-scan"
    assert "SyncTokenStale" in report["fallback_reason"]
    assert tokens.seed_calls == previous_seed_calls + 1
    assert adapter.order[:3] == ["seed", "tasks", "events"]
    assert engine.cached_tasks()[0].summary == "Server truth"
    assert cache.get(SyncEngine.TOKEN_KEY)["supported"] is True


def test_unsupported_server_is_not_reprobed_every_background_cycle():
    engine, adapter, cache, tokens = _engine()
    tokens.seed_error = SyncTokenUnavailable("unsupported")

    first = engine.incremental_sync()
    assert first["effective_mode"] == "full-scan"
    assert tokens.seed_calls == 1
    state = cache.get(SyncEngine.TOKEN_KEY)
    assert state["supported"] is False
    assert state["retry_at"]

    second = engine.incremental_sync()
    assert second["effective_mode"] == "full-scan"
    assert tokens.seed_calls == 1
    assert adapter.task_reads == 2
    assert adapter.event_reads == 2


def test_incremental_transport_failure_preserves_last_good_snapshot_and_token():
    engine, _adapter, cache, tokens = _engine()
    engine.incremental_sync()
    previous_snapshot = cache.get(SyncEngine.SNAPSHOT_KEY)
    previous_tokens = cache.get(SyncEngine.TOKEN_KEY)
    tokens.change_error = RuntimeError("network down")

    try:
        engine.incremental_sync()
    except RuntimeError as exc:
        assert str(exc) == "network down"
    else:
        raise AssertionError("incremental transport failure must propagate")

    assert cache.get(SyncEngine.SNAPSHOT_KEY) == previous_snapshot
    assert cache.get(SyncEngine.TOKEN_KEY) == previous_tokens
    assert cache.get(SyncEngine.STATUS_KEY)["state"] == "error"


class FakeComponent(dict):
    def __init__(self, name):
        super().__init__()
        self.name = name


class FakeURL:
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return self.value


class FakeResource:
    def __init__(self, url, component=None, *, deleted=False):
        self.url = FakeURL(url)
        self._component = component
        self._data = None if deleted else "BEGIN:VCALENDAR"

    def get_icalendar_component(self):
        return self._component


class FakeSyncResult(list):
    def __init__(self, items, token):
        super().__init__(items)
        self.sync_token = token


class FakeCalendar:
    def __init__(self):
        self.calls = []
        self.result = FakeSyncResult([], "seed")

    def get_objects_by_sync_token(self, token, *, load_objects, disable_fallback):
        self.calls.append((token, load_objects, disable_fallback))
        return self.result


class FakeInner:
    def _to_task(self, resource, calendar):
        return _task("t", "Task")

    def _to_event(self, resource, calendar):
        return _event("e", "Event")


class FakeRouted:
    def __init__(self, calendar):
        self.adapter = FakeInner()
        self.calendar = calendar
        self.task_collection_url = lambda: TASKS_URL
        self.event_collection_url = lambda: TASKS_URL

    def _selected_calendar(self, url):
        assert url == TASKS_URL
        return self.calendar


def test_transport_groups_shared_task_event_collection_into_one_report():
    calendar = FakeCalendar()
    routed = FakeRouted(calendar)
    transport = SyncTokenTransport(routed)

    seeded = transport.seed()
    assert seeded["tokens"] == {TASKS_URL: "seed"}
    assert len(calendar.calls) == 1

    calendar.result = FakeSyncResult(
        [
            FakeResource(f"{TASKS_URL}/t.ics", FakeComponent("VTODO")),
            FakeResource(f"{TASKS_URL}/e.ics", FakeComponent("VEVENT")),
            FakeResource(f"{TASKS_URL}/gone.ics", deleted=True),
        ],
        "next",
    )
    changes = transport.changes(seeded)
    assert len(calendar.calls) == 2
    assert [item.id for item in changes["tasks"]] == ["t"]
    assert [item.id for item in changes["events"]] == ["e"]
    assert changes["deleted_urls"] == [f"{TASKS_URL}/gone.ics"]
    assert changes["tokens"] == {TASKS_URL: "next"}
