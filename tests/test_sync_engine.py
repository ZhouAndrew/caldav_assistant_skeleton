from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from caldav_assistant.api import Event, Task
from caldav_assistant.api.v1.errors import ConflictError
from caldav_assistant.internal.caldav.sync import SyncEngine


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
        self.error = None

    def list_tasks(self):
        if self.error:
            raise self.error

        return list(self.tasks)

    def list_events(self):
        if self.error:
            raise self.error

        return list(self.events)


def test_refresh_writes_stable_cache_snapshot():
    task = Task(
        id="task-1",
        summary="Report",
        due=date(2026, 8, 25),
        completed_at=datetime(
            2026,
            8,
            24,
            8,
            30,
            tzinfo=timezone.utc,
        ),
        categories=["work"],
        raw=object(),
    )

    task._caldav_etag = '"abc"'
    task._caldav_collection_url = (
        "http://server/calendar/"
    )

    event = Event(
        id="event-1",
        summary="Meeting",
        start=datetime(
            2026,
            8,
            24,
            9,
            0,
            tzinfo=timezone.utc,
        ),
        raw=object(),
    )

    cache = MemoryCache()

    engine = SyncEngine(
        FakeAdapter(
            [task],
            [event],
        ),
        cache,
    )

    report = engine.refresh()

    snapshot = cache.get(
        SyncEngine.SNAPSHOT_KEY
    )

    assert report["state"] == "ok"
    assert report["effective_mode"] == "full"
    assert report["task_count"] == 1
    assert report["event_count"] == 1

    assert (
        snapshot["tasks"][0]["due"]
        == "2026-08-25"
    )

    assert (
        snapshot["tasks"][0]["completed_at"]
        == "2026-08-24T08:30:00+00:00"
    )

    assert (
        snapshot["tasks"][0]["_caldav"]["etag"]
        == '"abc"'
    )

    assert "raw" not in snapshot["tasks"][0]
    assert "raw" not in snapshot["events"][0]


def test_incremental_sync_reports_changes():
    cache = MemoryCache()

    adapter = FakeAdapter(
        tasks=[
            Task(
                id="a",
                summary="A",
            )
        ],
        events=[
            Event(
                id="e",
                summary="E",
            )
        ],
    )

    engine = SyncEngine(
        adapter,
        cache,
    )

    engine.refresh()

    adapter.tasks = [
        Task(
            id="a",
            summary="A changed",
        ),
        Task(
            id="b",
            summary="B",
        ),
    ]

    adapter.events = []

    report = engine.incremental_sync()

    assert (
        report["requested_mode"]
        == "incremental"
    )

    assert (
        report["effective_mode"]
        == "full-scan"
    )

    assert report["changes"]["tasks"] == {
        "added": ["b"],
        "updated": ["a"],
        "removed": [],
    }

    assert report["changes"]["events"] == {
        "added": [],
        "updated": [],
        "removed": ["e"],
    }


def test_duplicate_uid_is_conflict():
    cache = MemoryCache()

    adapter = FakeAdapter(
        tasks=[
            Task(
                id="safe",
                summary="Safe",
            )
        ]
    )

    engine = SyncEngine(
        adapter,
        cache,
    )

    engine.refresh()

    previous = cache.get(
        SyncEngine.SNAPSHOT_KEY
    )

    first = Task(
        id="duplicate",
        summary="First",
    )

    first._caldav_collection_url = (
        "http://server/a/"
    )

    second = Task(
        id="duplicate",
        summary="Second",
    )

    second._caldav_collection_url = (
        "http://server/b/"
    )

    adapter.tasks = [
        first,
        second,
    ]

    with pytest.raises(
        ConflictError
    ):
        engine.refresh()

    # Bad remote state must not overwrite good cache.
    assert (
        cache.get(
            SyncEngine.SNAPSHOT_KEY
        )
        == previous
    )

    status = cache.get(
        SyncEngine.STATUS_KEY
    )

    assert status["state"] == "error"

    assert (
        status["error_type"]
        == "ConflictError"
    )


def test_failure_preserves_last_good_cache():
    cache = MemoryCache()

    adapter = FakeAdapter(
        tasks=[
            Task(
                id="task-1",
                summary="Stored",
            )
        ]
    )

    engine = SyncEngine(
        adapter,
        cache,
    )

    engine.refresh()

    previous = cache.get(
        SyncEngine.SNAPSHOT_KEY
    )

    adapter.error = RuntimeError(
        "server offline"
    )

    with pytest.raises(
        RuntimeError,
        match="server offline",
    ):
        engine.incremental_sync()

    assert (
        cache.get(
            SyncEngine.SNAPSHOT_KEY
        )
        == previous
    )

    status = cache.get(
        SyncEngine.STATUS_KEY
    )

    assert status["state"] == "error"

    assert (
        status["requested_mode"]
        == "incremental"
    )

    assert (
        status["error_type"]
        == "RuntimeError"
    )

def test_cached_fact_views_restore_date_only_and_datetime_without_remote_reads():
    due = date(2026, 8, 28)
    start = datetime(2026, 8, 28, 9, 30, tzinfo=timezone.utc)
    adapter = FakeAdapter(
        tasks=[Task(id="t", summary="Task", due=due, categories=["school"])],
        events=[Event(id="e", summary="Event", start=start)],
    )
    cache = MemoryCache()
    engine = SyncEngine(adapter, cache)
    engine.refresh()

    adapter.error = AssertionError("cached reminder facts must not re-read CalDAV")
    tasks = engine.cached_tasks()
    events = engine.cached_events()

    assert tasks[0].due == due
    assert not isinstance(tasks[0].due, datetime)
    assert tasks[0].categories == ["school"]
    assert events[0].start == start
