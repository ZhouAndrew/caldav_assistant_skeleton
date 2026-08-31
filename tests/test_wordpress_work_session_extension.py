from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from caldav_assistant.api import ActionResult, Activity, Task
from caldav_assistant.api.v1.hooks import _bind_hook_registrar
from caldav_assistant.internal.activity import ActivityService
from caldav_assistant.internal.bootstrap import _DEFAULT_ENABLED_EXTENSIONS
from caldav_assistant.internal.commands import CommandRegistry, CommandService
from caldav_assistant.internal.extensions import ExtensionManager, HookRegistry
from caldav_assistant.internal.runtime.current_context import (
    bind_current_context,
    clear_current_context,
)
from caldav_assistant.internal.settings.keys import (
    WORDPRESS_WORKLOG_STYLE,
    WORDPRESS_WORKLOG_TEMPLATE,
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

    def _activities(self):
        return [
            Activity(timestamp=timestamp, action=action, object_id=object_id, metadata=metadata)
            for timestamp, action, object_id, metadata in self.rows
        ]

    def between(self, start, end):
        return [item for item in self._activities() if start <= item.timestamp < end]

    def for_object(self, object_id):
        return [item for item in self._activities() if item.object_id == object_id]


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

    def queue_log(self, text, **metadata):
        self.calls.append((text, metadata))
        if self.fail:
            raise RuntimeError("wordpress unavailable")
        return ActionResult(True, message="queued")

    def log(self, text, **metadata):
        return self.queue_log(text, **metadata)


class SequenceClock:
    def __init__(self, *values):
        self.values = list(values)

    def __call__(self):
        assert self.values, "test clock exhausted"
        return self.values.pop(0)


def _local_clock(value: datetime) -> str:
    local = value.astimezone()
    return f"{local.hour}:{local.minute:02d}"


def _bundled_extensions_dir() -> Path:
    import caldav_assistant

    return Path(caldav_assistant.__file__).resolve().parent / "builtin_extensions"


def _load_extension(tasks, activity, wordpress, settings=None):
    commands = CommandService(CommandRegistry())
    hooks = HookRegistry()
    settings = settings or FakeSettings()
    ctx = SimpleNamespace(
        tasks=tasks,
        activity=activity,
        wordpress=wordpress,
        settings=settings,
    )

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
    return manager, hooks, settings


def _cleanup_extension_runtime():
    _bind_hook_registrar(None)
    clear_current_context()


def test_default_worklog_writes_one_line_only_when_segment_closes():
    task = Task(
        id="t1",
        summary="Anki",
        start=date(2026, 5, 18),
        due=date(2026, 5, 19),
        priority=4,
    )
    adapter = FakeTaskAdapter(task)
    repo = FakeActivityRepo()
    t0 = datetime(2026, 8, 31, 5, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 8, 31, 5, 10, tzinfo=timezone.utc)
    t2 = datetime(2026, 8, 31, 5, 20, tzinfo=timezone.utc)
    t3 = datetime(2026, 8, 31, 5, 30, tzinfo=timezone.utc)
    activity = ActivityService(
        repo,
        clock=SequenceClock(t0, t1, t2, t3),
    )
    tasks = TaskService(adapter, activity=activity)
    wordpress = FakeWordPress()

    try:
        _load_extension(tasks, activity, wordpress)

        assert tasks.start(task).success is True
        assert wordpress.calls == []

        assert tasks.pause(task).success is True
        assert wordpress.calls == [
            (f"{_local_clock(t0)}-{_local_clock(t1)} Anki", {"_show_clock": False}),
        ]

        assert tasks.resume(task).success is True
        assert len(wordpress.calls) == 1

        assert tasks.pause(task).success is True
        assert wordpress.calls[-1] == (
            f"{_local_clock(t2)}-{_local_clock(t3)} Anki",
            {"_show_clock": False},
        )

        # Detailed facts are still preserved locally rather than dumped into WP.
        assert [row[1] for row in repo.rows] == [
            "task_started",
            "task_paused",
            "task_resumed",
            "task_paused",
        ]
        text = "\n".join(call[0] for call in wordpress.calls)
        assert "Task UID" not in text
        assert "Planned start" not in text
        assert "Priority" not in text
    finally:
        _cleanup_extension_runtime()


def test_worklog_format_is_customizable_per_user_settings():
    task = Task(id="t1", summary="Anki")
    repo = FakeActivityRepo()
    t0 = datetime(2026, 8, 31, 5, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 8, 31, 5, 10, tzinfo=timezone.utc)
    activity = ActivityService(
        repo,
        clock=SequenceClock(t0, t1),
    )
    tasks = TaskService(FakeTaskAdapter(task), activity=activity)
    wordpress = FakeWordPress()
    settings = FakeSettings()
    settings.set(WORDPRESS_WORKLOG_STYLE, "custom")
    settings.set(
        WORDPRESS_WORKLOG_TEMPLATE,
        "{task} | {duration_minutes} min | {start}->{end}",
    )

    try:
        _load_extension(tasks, activity, wordpress, settings)
        tasks.start(task)
        tasks.pause(task)

        assert wordpress.calls == [
            (
                f"Anki | 10 min | {_local_clock(t0)}->{_local_clock(t1)}",
                {"_show_clock": False},
            ),
        ]
    finally:
        _cleanup_extension_runtime()


def test_worklog_can_be_disabled_without_disabling_activity_history():
    task = Task(id="t1", summary="Report")
    repo = FakeActivityRepo()
    activity = ActivityService(
        repo,
        clock=SequenceClock(
            datetime(2026, 8, 31, 5, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 31, 5, 10, tzinfo=timezone.utc),
        ),
    )
    tasks = TaskService(FakeTaskAdapter(task), activity=activity)
    wordpress = FakeWordPress()
    settings = FakeSettings()
    settings.set(WORDPRESS_WORKLOG_STYLE, "off")

    try:
        _load_extension(tasks, activity, wordpress, settings)
        tasks.start(task)
        tasks.pause(task)

        assert wordpress.calls == []
        assert [row[1] for row in repo.rows] == ["task_started", "task_paused"]
    finally:
        _cleanup_extension_runtime()


def test_disabling_extension_stops_wordpress_side_effect():
    task = Task(id="t1", summary="Report")
    repo = FakeActivityRepo()
    activity = ActivityService(repo)
    tasks = TaskService(FakeTaskAdapter(task), activity=activity)
    wordpress = FakeWordPress()

    try:
        manager, _, _ = _load_extension(tasks, activity, wordpress)
        manager.disable("wordpress_work_session_log")

        result = tasks.start(task)

        assert result.success is True
        assert wordpress.calls == []
        assert [row[1] for row in repo.rows] == ["task_started"]
    finally:
        _cleanup_extension_runtime()


def test_wordpress_extension_failure_never_rolls_back_successful_pause():
    task = Task(id="t1", summary="Physics")
    repo = FakeActivityRepo()
    activity = ActivityService(
        repo,
        clock=SequenceClock(
            datetime(2026, 8, 31, 5, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 31, 5, 10, tzinfo=timezone.utc),
        ),
    )
    tasks = TaskService(FakeTaskAdapter(task), activity=activity)
    wordpress = FakeWordPress(fail=True)

    try:
        _, hooks, _ = _load_extension(tasks, activity, wordpress)
        tasks.start(task)
        result = tasks.pause(task)

        assert result.success is True
        assert task.status == "IN-PROCESS"
        assert [row[1] for row in repo.rows] == ["task_started", "task_paused"]
        failures = hooks.failures()
        assert len(failures) == 1
        assert failures[0].event == "task.paused"
        assert failures[0].owner == "wordpress_work_session_log"
        assert failures[0].error_type == "RuntimeError"
    finally:
        _cleanup_extension_runtime()


def test_wordpress_work_session_extension_is_default_enabled_but_disableable():
    assert "wordpress_work_session_log" in _DEFAULT_ENABLED_EXTENSIONS
