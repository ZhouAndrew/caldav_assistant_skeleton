from __future__ import annotations

from types import SimpleNamespace

import pytest

from caldav_assistant.api import Task
from caldav_assistant.internal.caldav import SyncEngine
from caldav_assistant.internal.cli import conversation_app
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
        return []

    def list_events(self, **filters):
        return []


class WorkLog:
    def __init__(self, sync):
        self.adapter = SimpleNamespace(sync=sync)

    def configured(self):
        return True


def test_previous_daemon_verified_none_becomes_unknown_after_restart():
    cache = MemoryCache()
    sync = SyncEngine(Source(), cache)
    worklog = WorkLog(sync)
    old = CalDAVSessionService(worklog, snapshot_generation="daemon-a")
    task = Task(id="t1", summary="Task", status="IN-PROCESS")

    old.mark_paused(task)
    old_value = cache.get(CalDAVSessionService.CURRENT_WORK_SNAPSHOT_KEY)
    assert old_value["producer_generation"] == "daemon-a"
    assert old_value["current_task_id"] is None

    new = CalDAVSessionService(worklog, snapshot_generation="daemon-b")
    facts = new.cached_startup_snapshot([task])

    assert facts["current_work_verified"] is False
    assert facts["current_task_id"] is None
    assert facts["verified_at"] is None
    assert facts["producer_generation"] == "daemon-b"


def test_authoritative_lifecycle_write_makes_new_generation_ready_immediately():
    cache = MemoryCache()
    sync = SyncEngine(Source(), cache)
    session = CalDAVSessionService(
        WorkLog(sync),
        snapshot_generation="daemon-b",
    )
    task = Task(id="t1", summary="Task", status="IN-PROCESS")

    assert session.cached_startup_snapshot([task])["current_work_verified"] is False

    session.set_current(task)
    current = session.cached_startup_snapshot([task])
    assert current["current_work_verified"] is True
    assert current["current_task_id"] == "t1"

    session.mark_paused(task)
    paused = session.cached_startup_snapshot([task])
    assert paused["current_work_verified"] is True
    assert paused["current_task_id"] is None


def test_independent_ready_refresh_reports_failure_but_runs_other_hooks():
    sync = SyncEngine(Source(), MemoryCache())
    calls = []

    def broken():
        calls.append("broken")
        raise ValueError("work collection unavailable")

    def healthy():
        calls.append("healthy")

    sync.register_post_sync_hook(broken)
    sync.register_post_sync_hook(healthy)

    with pytest.raises(RuntimeError, match="ready-state refresh"):
        sync.refresh_ready_state()

    assert calls == ["broken", "healthy"]


class CaptureUI:
    def __init__(self):
        self.items = None

    def choose(self, title, items, **kwargs):
        self.items = tuple(items)
        return None


def test_unverified_home_cannot_offer_start_actions_or_recommendation_path():
    ui = CaptureUI()
    app = SimpleNamespace(ctx=SimpleNamespace(ui=ui))
    candidate = Task(id="anki", summary="Anki")
    snapshot = conversation_app.StartupSnapshot(
        current_task=None,
        recommended=candidate,
        tasks=(candidate,),
        current_work_verified=False,
        stale=True,
    )

    assert conversation_app._home_menu(app, snapshot) == "console"
    assert ui.items is not None
    assert ui.items[0] == "Refresh current work"
    assert not any(item.startswith("Start recommended Task") for item in ui.items)
    assert "Choose a Task and start" not in ui.items
