from __future__ import annotations

from types import SimpleNamespace

import pytest

from caldav_assistant.api import Event, Task
from caldav_assistant.api.v1.errors import UnavailableError
from caldav_assistant.internal.agenda import AgendaService
from caldav_assistant.internal.caldav import (
    ExperimentalCacheCalDAVAdapter,
    OfflineFallbackCalDAVAdapter,
    SyncEngine,
)


class BuildEngine:
    def build(self, tasks, events, **options):
        return SimpleNamespace(items=())

    def candidates(self, tasks, events):
        return ()


class NextEngine:
    def choose(self, agenda, **options):
        return None


class CachedSession:
    def __init__(self):
        self.cached_calls = 0

    def cached_startup_snapshot(self, tasks):
        self.cached_calls += 1
        return {"current_task_id": None, "worked_task_ids": ()}

    def startup_snapshot(self, tasks, *, work_facts=None):
        assert work_facts == {"current_task_id": None, "worked_task_ids": ()}
        return {
            "current_task_id": None,
            "current_task": None,
            "paused_task_ids": (),
        }


class StartupAdapter:
    def __init__(self):
        self.calls = 0

    def cached_startup_items(self, **task_filters):
        self.calls += 1
        assert task_filters == {"completed": False}
        return (
            [
                Task(id="active", summary="Active", status="NEEDS-ACTION", stale=True),
                Task(id="done", summary="Done", status="COMPLETED", stale=True),
                Task(id="cancelled", summary="Cancelled", status="CANCELLED", stale=True),
            ],
            [Event(id="event", summary="Event", stale=True)],
        )


class LiveTasksMustNotRun:
    def __init__(self, adapter):
        self.adapter = adapter

    def list(self, **filters):
        pytest.fail("CLI startup must not perform a live Task read")


class LiveEventsMustNotRun:
    def list(self, **filters):
        pytest.fail("CLI startup must not perform a live Event read")


def test_production_startup_reads_background_snapshot_not_live_caldav():
    adapter = StartupAdapter()
    session = CachedSession()
    service = AgendaService(
        LiveTasksMustNotRun(adapter),
        LiveEventsMustNotRun(),
        BuildEngine(),
        NextEngine(),
        {},
        session=session,
    )

    result = service.startup_snapshot(days=2, kind="task")

    assert adapter.calls == 1
    assert session.cached_calls == 1
    assert result["stale"] is True
    assert [task.id for task in result["tasks"]] == ["active"]


def test_missing_background_snapshot_fails_without_falling_through_to_live_reads():
    class Adapter:
        def cached_startup_items(self, **filters):
            raise UnavailableError("No verified Task/Event snapshot is available")

    service = AgendaService(
        LiveTasksMustNotRun(Adapter()),
        LiveEventsMustNotRun(),
        BuildEngine(),
        NextEngine(),
        {},
    )

    with pytest.raises(UnavailableError, match="No verified"):
        service.startup_snapshot()


class CountingSync:
    SCHEMA_VERSION = 1

    def __init__(self):
        self.calls = 0

    def cached_snapshot(self):
        self.calls += 1
        return {
            "schema_version": 1,
            "synced_at": "2026-09-13T06:00:00+00:00",
            "tasks": [
                {
                    "id": "t1",
                    "summary": "Task",
                    "description": "",
                    "start": None,
                    "due": None,
                    "status": "NEEDS-ACTION",
                    "completed": False,
                    "completed_at": None,
                    "priority": None,
                    "categories": [],
                    "etag": None,
                }
            ],
            "events": [
                {
                    "id": "e1",
                    "summary": "Event",
                    "start": None,
                    "end": None,
                    "location": "",
                    "description": "",
                    "categories": [],
                    "etag": None,
                }
            ],
        }

    @staticmethod
    def _cached_task(data):
        return SyncEngine._cached_task(data)

    @staticmethod
    def _cached_event(data):
        return SyncEngine._cached_event(data)


class NeverLiveAdapter:
    pass


def test_startup_task_and_event_models_share_one_snapshot_read():
    sync = CountingSync()
    adapter = OfflineFallbackCalDAVAdapter(NeverLiveAdapter(), sync)

    tasks, events = adapter.cached_startup_items(completed=False)

    assert sync.calls == 1
    assert [task.id for task in tasks] == ["t1"]
    assert [event.id for event in events] == ["e1"]
    assert tasks[0].stale is True
    assert events[0].stale is True


class MemoryCache:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


class MutableAdapter:
    def __init__(self):
        self.tasks = [Task(id="t1", summary="Before")]

    def list_tasks(self, **filters):
        return list(self.tasks)

    def list_events(self, **filters):
        return []

    def get_task(self, task_id):
        return next(task for task in self.tasks if task.id == task_id)

    def update_task(self, task_id, changes, *, etag=None):
        task = self.get_task(task_id)
        for key, value in changes.items():
            setattr(task, key, value)
        return task


def test_authoritative_write_updates_startup_snapshot_even_when_fast_reads_disabled():
    source = MutableAdapter()
    sync = SyncEngine(source, MemoryCache())
    sync.refresh()
    wrapped = ExperimentalCacheCalDAVAdapter(
        source,
        sync,
        enabled=lambda: False,
    )

    wrapped.update_task("t1", {"summary": "After"})

    cached = sync.cached_tasks()
    snapshot = sync.cached_snapshot()
    assert [task.summary for task in cached] == ["After"]
    assert snapshot["cache_update_reason"] == "authoritative-write"
    assert snapshot["cache_updated_at"]
