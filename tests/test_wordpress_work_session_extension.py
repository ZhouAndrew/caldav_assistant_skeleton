from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from caldav_assistant.api import ActionResult, Task
from caldav_assistant.api.v1.hooks import _bind_hook_registrar
from caldav_assistant.internal.activity import ActivityService
from caldav_assistant.internal.bootstrap import _DEFAULT_ENABLED_EXTENSIONS
from caldav_assistant.internal.commands import CommandRegistry, CommandService
from caldav_assistant.internal.extensions import ExtensionManager, HookRegistry
from caldav_assistant.internal.runtime.current_context import (
    bind_current_context,
    clear_current_context,
)
from caldav_assistant.internal.tasks.service import TaskService


class FakeSettings:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        return value


class FakeActivityRepo:
    def __init__(self):
        self.rows = []

    def record(self, timestamp, action, object_id, metadata):
        self.rows.append((timestamp, action, object_id, metadata))

    def between(self, start, end):
        return []

    def for_object(self, object_id):
        return []


class FakeTaskAdapter:
    def __init__(self, task):
        self.task = task

    def list_tasks(self, **filters):
        items = [self.task]
        status = filters.get("status")
        if status is not None:
            items = [item for item in items if item.status == status]
        return items

    def get_task(self, task_id):
        assert task_id == self.task.id
        return self.task

    def update_task(self, task_id, changes):
        assert task_id == self.task.id
        for key, value in changes.items():
            setattr(self.task, key, value)
        return self.task


class FakeWordPress:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls = []

    def log(self, text, **metadata):
        self.calls.append((text, metadata))
        if self.fail:
            raise RuntimeError("wordpress unavailable")
        return ActionResult(True, message="saved")


def _bundled_extensions_dir() -> Path:
    import caldav_assistant

    return Path(caldav_assistant.__file__).resolve().parent / "builtin_extensions"


def _load_extension(tasks, wordpress):
    commands = CommandService(CommandRegistry())
    hooks = HookRegistry()
    settings = FakeSettings()
    ctx = SimpleNamespace(tasks=tasks, wordpress=wordpress)

    bind_current_context(ctx)
    _bind_hook_registrar(hooks)
    manager = ExtensionManager(
        commands,
        hooks,
        settings,
        bundled_root=_bundled_extensions_dir(),
    )
    record = manager.load("wordpress_work_session_log")
    assert record.status == "loaded"
    return manager, hooks


def _cleanup_extension_runtime():
    _bind_hook_registrar(None)
    clear_current_context()


def test_start_pause_resume_logs_start_and_resume_to_wordpress_via_extension():
    task = Task(
        id="t1",
        summary="Anki",
        start=date(2026, 5, 18),
        due=date(2026, 5, 19),
        priority=4,
    )
    adapter = FakeTaskAdapter(task)
    repo = FakeActivityRepo()
    activity = ActivityService(
        repo,
        clock=lambda: datetime(2026, 8, 29, 14, 31, tzinfo=timezone.utc),
    )
    tasks = TaskService(adapter, activity=activity)
    wordpress = FakeWordPress()

    try:
        _load_extension(tasks, wordpress)

        started = tasks.start(task)
        paused = tasks.pause(task)
        resumed = tasks.resume(task)

        assert started.success is True
        assert paused.success is True
        assert resumed.success is True
        assert [row[1] for row in repo.rows] == [
            "task_started",
            "task_paused",
            "task_resumed",
        ]
        assert len(wordpress.calls) == 2

        started_text, started_meta = wordpress.calls[0]
        resumed_text, resumed_meta = wordpress.calls[1]
        assert started_meta["title"] == "Started — Anki"
        assert resumed_meta["title"] == "Resumed — Anki"
        for text in (started_text, resumed_text):
            assert "Task: Anki" in text
            assert "Task UID: t1" in text
            assert "Actual time: 2026-08-29T14:31:00" in text
            assert "Planned start: 2026-05-18" in text
            assert "Due: 2026-05-19" in text
            assert "Priority: 4" in text
    finally:
        _cleanup_extension_runtime()


def test_disabling_extension_stops_wordpress_side_effect():
    task = Task(id="t1", summary="Report")
    adapter = FakeTaskAdapter(task)
    repo = FakeActivityRepo()
    activity = ActivityService(repo)
    tasks = TaskService(adapter, activity=activity)
    wordpress = FakeWordPress()

    try:
        manager, _ = _load_extension(tasks, wordpress)
        manager.disable("wordpress_work_session_log")

        result = tasks.start(task)

        assert result.success is True
        assert wordpress.calls == []
        assert [row[1] for row in repo.rows] == ["task_started"]
    finally:
        _cleanup_extension_runtime()


def test_wordpress_extension_failure_never_rolls_back_successful_start():
    task = Task(id="t1", summary="Physics")
    adapter = FakeTaskAdapter(task)
    repo = FakeActivityRepo()
    activity = ActivityService(repo)
    tasks = TaskService(adapter, activity=activity)
    wordpress = FakeWordPress(fail=True)

    try:
        _, hooks = _load_extension(tasks, wordpress)

        result = tasks.start(task)

        assert result.success is True
        assert task.status == "IN-PROCESS"
        assert [row[1] for row in repo.rows] == ["task_started"]
        failures = hooks.failures()
        assert len(failures) == 1
        assert failures[0].event == "task.started"
        assert failures[0].owner == "wordpress_work_session_log"
        assert failures[0].error_type == "RuntimeError"
    finally:
        _cleanup_extension_runtime()


def test_wordpress_work_session_extension_is_default_enabled_but_disableable():
    assert "wordpress_work_session_log" in _DEFAULT_ENABLED_EXTENSIONS
