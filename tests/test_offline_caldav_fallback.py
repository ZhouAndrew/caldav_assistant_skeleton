from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from caldav_assistant.api import Activity, Event, Task
from caldav_assistant.api.v1.errors import UnavailableError
from caldav_assistant.internal.agenda.engine import AgendaEngine
from caldav_assistant.internal.caldav.offline_fallback import OfflineFallbackCalDAVAdapter
from caldav_assistant.internal.caldav.sync import SyncEngine
from caldav_assistant.internal.cli.presenter import render_agenda, render_task
from caldav_assistant.internal.runtime.ipc import sanitize_ipc_value
from caldav_assistant.internal.session.caldav import CalDAVSessionService


class MemoryCache:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


class FlakyAdapter:
    def __init__(self):
        self.online = True
        self.tasks = [
            Task(
                id="t1",
                summary="Last verified task",
                due=date.today(),
            )
        ]
        self.events = [
            Event(
                id="e1",
                summary="Last verified event",
                start=datetime.now().astimezone(),
            )
        ]

    def _require_online(self):
        if not self.online:
            raise UnavailableError("CalDAV temporarily unreachable")

    def list_tasks(self, **filters):
        self._require_online()
        return list(self.tasks)

    def get_task(self, task_id):
        self._require_online()
        return next(task for task in self.tasks if task.id == task_id)

    def list_events(self, **filters):
        self._require_online()
        return list(self.events)

    def list_events_between(self, start, end, **filters):
        self._require_online()
        return list(self.events)

    def get_event(self, event_id):
        self._require_online()
        return next(event for event in self.events if event.id == event_id)

    def update_task(self, task_id, changes, *, etag=None):
        self._require_online()
        task = self.get_task(task_id)
        for key, value in changes.items():
            setattr(task, key, value)
        return task


class OfflineWorkLog:
    def configured(self):
        return True

    def _all_work_events(self):
        raise UnavailableError("Work collection unavailable")


class ActivityReader:
    def for_task(self, task):
        return [
            Activity(
                timestamp=datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc),
                action="task_started",
                object_id=task.id,
            )
        ]


def make_offline_after_verified_sync():
    adapter = FlakyAdapter()
    sync = SyncEngine(adapter, MemoryCache())
    sync.refresh()
    adapter.online = False
    return adapter, sync, OfflineFallbackCalDAVAdapter(adapter, sync)


def test_offline_list_returns_last_verified_tasks_explicitly_marked_stale():
    _, _, wrapped = make_offline_after_verified_sync()

    tasks = list(wrapped.list_tasks())

    assert [task.id for task in tasks] == ["t1"]
    assert tasks[0].stale is True


def test_offline_bounded_event_read_stays_inside_fallback_boundary():
    _, _, wrapped = make_offline_after_verified_sync()

    events = list(
        wrapped.list_events_between(
            datetime.now().astimezone(),
            datetime.now().astimezone(),
        )
    )

    assert [event.id for event in events] == ["e1"]
    assert events[0].stale is True


def test_empty_offline_read_still_exposes_that_cache_fallback_was_used():
    _, sync, wrapped = make_offline_after_verified_sync()
    snapshot = dict(sync.cached_snapshot())
    snapshot["tasks"] = []
    sync.cache.set(sync.SNAPSHOT_KEY, snapshot)
    before = wrapped.fallback_generation

    assert list(wrapped.list_tasks()) == []

    assert wrapped.fallback_generation == before + 1


def test_no_verified_snapshot_keeps_unavailable_error_instead_of_inventing_data():
    adapter = FlakyAdapter()
    adapter.online = False
    sync = SyncEngine(adapter, MemoryCache())
    wrapped = OfflineFallbackCalDAVAdapter(adapter, sync)

    with pytest.raises(UnavailableError):
        wrapped.list_tasks()


def test_mutation_never_succeeds_from_cache_while_caldav_is_offline():
    _, _, wrapped = make_offline_after_verified_sync()

    with pytest.raises(UnavailableError):
        wrapped.update_task("t1", {"summary": "must not be cached as success"})


def test_stale_marker_survives_ipc_and_is_visible_in_cli_presentation():
    _, _, wrapped = make_offline_after_verified_sync()
    task = list(wrapped.list_tasks())[0]

    detached = sanitize_ipc_value(task)
    assert detached.stale is True
    assert any("CalDAV is unavailable" in line for line in render_task(detached))

    agenda = AgendaEngine().build([detached], [], days=1)
    assert any("CalDAV is unavailable" in line for line in render_agenda(agenda))


def test_work_session_read_falls_back_to_local_activity_when_worklog_is_offline():
    task = Task(
        id="t1",
        summary="Current from last local activity",
        status="IN-PROCESS",
        stale=True,
    )
    session = CalDAVSessionService(
        OfflineWorkLog(),
        activity=ActivityReader(),
    )

    snapshot = session.startup_snapshot([task])

    assert snapshot["current_task_id"] == "t1"
    assert snapshot["current_task"] is task
    assert snapshot["paused_task_ids"] == ()
