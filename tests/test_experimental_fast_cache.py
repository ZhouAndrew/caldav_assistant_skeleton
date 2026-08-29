from __future__ import annotations

from datetime import date

from caldav_assistant.api import Event, Task
from caldav_assistant.internal.caldav.experimental_cache import (
    ExperimentalCacheCalDAVAdapter,
)
from caldav_assistant.internal.caldav.sync import SyncEngine
from caldav_assistant.internal.settings.keys import EXPERIMENTAL_FAST_QUERY_CACHE
from caldav_assistant.internal.settings.schema import DEFAULT_SETTINGS_SCHEMA


class MemoryCache:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


class FakeAdapter:
    def __init__(self, tasks=(), events=()):
        self.tasks = list(tasks)
        self.events = list(events)
        self.task_list_calls = 0
        self.event_list_calls = 0
        self.task_get_calls = 0
        self.event_get_calls = 0
        self.task_update_calls = 0

    def list_tasks(self, **filters):
        self.task_list_calls += 1
        return list(self.tasks)

    def list_events(self, **filters):
        self.event_list_calls += 1
        return list(self.events)

    def get_task(self, task_id):
        self.task_get_calls += 1
        for task in self.tasks:
            if str(task.id) == str(task_id):
                return task
        raise KeyError(task_id)

    def get_event(self, event_id):
        self.event_get_calls += 1
        for event in self.events:
            if str(event.id) == str(event_id):
                return event
        raise KeyError(event_id)

    def create_task(self, task):
        self.tasks.append(task)
        return task

    def update_task(self, task_id, changes, *, etag=None):
        self.task_update_calls += 1
        task = self.get_task(task_id)
        for key, value in changes.items():
            setattr(task, key, value)
        return task

    def delete_task(self, task_id, *, etag=None):
        self.tasks = [task for task in self.tasks if str(task.id) != str(task_id)]

    def create_event(self, event):
        self.events.append(event)
        return event

    def update_event(self, event_id, changes, *, etag=None):
        event = self.get_event(event_id)
        for key, value in changes.items():
            setattr(event, key, value)
        return event

    def delete_event(self, event_id, *, etag=None):
        self.events = [event for event in self.events if str(event.id) != str(event_id)]


def make_system(*, enabled=False):
    state = {"enabled": enabled}
    adapter = FakeAdapter(
        tasks=[
            Task(
                id="t1",
                summary="Cached task",
                due=date.today(),
                categories=["school"],
            )
        ],
        events=[Event(id="e1", summary="Cached event")],
    )
    cache = MemoryCache()
    sync = SyncEngine(adapter, cache)
    wrapped = ExperimentalCacheCalDAVAdapter(
        adapter,
        sync,
        enabled=lambda: state["enabled"],
    )
    return state, adapter, sync, wrapped


def test_fast_query_cache_setting_is_experimental_and_off_by_default():
    spec = DEFAULT_SETTINGS_SCHEMA.get(EXPERIMENTAL_FAST_QUERY_CACHE)

    assert spec.category == "Experimental"
    assert spec.kind == "bool"
    assert spec.default_value() is False


def test_disabled_experiment_preserves_authoritative_read_path():
    _, adapter, sync, wrapped = make_system(enabled=False)
    sync.refresh()
    calls_after_refresh = adapter.task_list_calls

    result = wrapped.list_tasks()

    assert [task.id for task in result] == ["t1"]
    assert adapter.task_list_calls == calls_after_refresh + 1


def test_enabled_experiment_serves_verified_snapshot_without_remote_read():
    state, adapter, sync, wrapped = make_system(enabled=False)
    sync.refresh()
    state["enabled"] = True
    calls_after_refresh = adapter.task_list_calls

    result = wrapped.list_tasks()

    assert [task.id for task in result] == ["t1"]
    assert adapter.task_list_calls == calls_after_refresh


def test_enabled_experiment_without_snapshot_falls_back_to_caldav():
    _, adapter, _, wrapped = make_system(enabled=True)

    result = wrapped.list_tasks()

    assert [task.id for task in result] == ["t1"]
    assert adapter.task_list_calls == 1


def test_cache_miss_is_not_treated_as_authoritative_not_found():
    _, adapter, sync, wrapped = make_system(enabled=True)
    sync.refresh()
    adapter.tasks.append(Task(id="new", summary="Arrived after sync"))
    calls_before = adapter.task_get_calls

    task = wrapped.get_task("new")

    assert task.summary == "Arrived after sync"
    assert adapter.task_get_calls == calls_before + 1


def test_cached_list_applies_normal_filters_without_network():
    _, adapter, sync, wrapped = make_system(enabled=True)
    sync.refresh()
    calls_after_refresh = adapter.task_list_calls

    school = wrapped.list_tasks(category="school")
    missing = wrapped.list_tasks(category="work")
    today = wrapped.list_tasks(today=True)

    assert [task.id for task in school] == ["t1"]
    assert missing == []
    assert [task.id for task in today] == ["t1"]
    assert adapter.task_list_calls == calls_after_refresh


def test_successful_authoritative_update_patches_enabled_cache():
    _, adapter, sync, wrapped = make_system(enabled=True)
    sync.refresh()
    calls_after_refresh = adapter.task_list_calls

    updated = wrapped.update_task("t1", {"summary": "Updated on server"})
    cached = wrapped.list_tasks()
    snapshot = sync.cached_snapshot()

    assert updated.summary == "Updated on server"
    assert [task.summary for task in cached] == ["Updated on server"]
    assert adapter.task_update_calls == 1
    assert adapter.task_list_calls == calls_after_refresh
    assert snapshot["synced_at"]
    assert snapshot["cache_update_reason"] == "authoritative-write"
    assert snapshot["cache_updated_at"]


def test_disabled_experiment_does_not_write_through_snapshot():
    _, adapter, sync, wrapped = make_system(enabled=False)
    sync.refresh()
    before = sync.cached_snapshot()

    wrapped.update_task("t1", {"summary": "Server only until next sync"})
    after = sync.cached_snapshot()

    assert adapter.task_update_calls == 1
    assert after == before


def test_diagnostics_explain_cache_hits_and_caldav_fallbacks():
    state, adapter, sync, wrapped = make_system(enabled=False)
    sync.refresh()

    wrapped.list_tasks()
    state["enabled"] = True
    wrapped.list_tasks()
    adapter.tasks.append(Task(id="new", summary="New after snapshot"))
    wrapped.get_task("new")

    status = wrapped.diagnostics()

    assert status["enabled"] is True
    assert status["snapshot_available"] is True
    assert status["task_count"] == 1
    assert status["event_count"] == 1
    assert status["synced_at"]
    assert status["sync_status"]["state"] == "ok"
    assert status["read_counts"] == {"cache": 1, "caldav": 2}
    assert [item["reason"] for item in status["recent_reads"][-3:]] == [
        "experiment-disabled",
        "snapshot-hit",
        "cache-miss",
    ]


def test_no_snapshot_diagnostic_names_the_fallback_reason():
    _, adapter, _, wrapped = make_system(enabled=True)

    wrapped.list_events()
    status = wrapped.diagnostics()

    assert adapter.event_list_calls == 1
    assert status["snapshot_available"] is False
    assert status["recent_reads"][-1]["operation"] == "events.list"
    assert status["recent_reads"][-1]["source"] == "caldav"
    assert status["recent_reads"][-1]["reason"] == "no-snapshot"
