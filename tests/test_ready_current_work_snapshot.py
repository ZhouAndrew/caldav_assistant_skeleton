from __future__ import annotations

from types import SimpleNamespace

from caldav_assistant.api import Task
from caldav_assistant.internal.caldav import SyncEngine
from caldav_assistant.internal.session import CalDAVSessionService


class MemoryCache:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


class Source:
    def list_tasks(self, **filters):
        return [Task(id="t1", summary="Task")]

    def list_events(self, **filters):
        return []


class WorkLog:
    def __init__(self, sync):
        self.adapter = SimpleNamespace(sync=sync)

    def configured(self):
        return True


class NoopActivity:
    def for_task(self, task):
        return []


def test_sync_success_runs_failure_isolated_ready_hooks():
    sync = SyncEngine(Source(), MemoryCache())
    calls = []

    def broken():
        calls.append("broken")
        raise RuntimeError("auxiliary refresh failed")

    def healthy():
        calls.append("healthy")

    sync.register_post_sync_hook(broken)
    sync.register_post_sync_hook(healthy)

    report = sync.refresh()

    assert report["state"] == "ok"
    assert calls == ["broken", "healthy"]


def test_session_current_work_snapshot_is_local_and_write_through():
    sync = SyncEngine(Source(), MemoryCache())
    session = CalDAVSessionService(WorkLog(sync), activity=NoopActivity())
    task = Task(id="current", summary="Current", status="IN-PROCESS")

    session.set_current(task)
    facts = session.cached_startup_snapshot([task])

    assert facts["current_task_id"] == "current"
    assert facts["current_work_verified"] is True
    assert facts["verified_at"]

    session.mark_paused(task)
    cleared = session.cached_startup_snapshot([task])
    assert cleared["current_task_id"] is None
    assert cleared["current_work_verified"] is True
