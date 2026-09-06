from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from caldav_assistant.api import ActionResult, Event, Task
from caldav_assistant.api.v1.hooks import _bind_hook_registrar
from caldav_assistant.internal.activity import ActivityService
from caldav_assistant.internal.commands import CommandRegistry, CommandService
from caldav_assistant.internal.extensions import ExtensionManager, HookRegistry
from caldav_assistant.internal.runtime.current_context import (
    bind_current_context,
    clear_current_context,
)
from caldav_assistant.internal.session import CalDAVSessionService
from caldav_assistant.internal.tasks import CalDAVWorkTaskService
from caldav_assistant.internal.tasks.completion_log import (
    CompletionLoggingTaskService,
    TaskCompletionLogService,
)
from caldav_assistant.internal.worklog import WorkLogService


WORK_URL = "https://dav.example/work/"


class Repo:
    def __init__(self):
        self.rows = []

    def record(self, timestamp, action, object_id, metadata):
        self.rows.append((timestamp, action, object_id, metadata))

    def for_object(self, object_id):
        return []


class Settings:
    def get(self, key, default=None):
        return default

    def set(self, key, value):
        return value


class WordPress:
    def __init__(self):
        self.calls = []

    def queue_log(self, text, **metadata):
        self.calls.append((text, metadata))
        return ActionResult(True, message="queued")

    def log(self, text, **metadata):
        return self.queue_log(text, **metadata)


class Clock:
    def __init__(self):
        self.value = datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, minutes):
        self.value += timedelta(minutes=minutes)


class Adapter:
    def __init__(self):
        self.task = Task(id="t1", summary="Anki", status="NEEDS-ACTION")
        self.events: list[Event] = []
        self.task_list_reads = 0
        self.work_event_reads = 0
        self.next_event_id = 1

    def get_task(self, task_id):
        assert task_id == self.task.id
        return self.task

    def list_tasks(self, **filters):
        self.task_list_reads += 1
        values = [self.task]
        for key, value in filters.items():
            values = [item for item in values if getattr(item, key) == value]
        return values

    def update_task(self, task_id, changes, *, etag=None):
        assert task_id == self.task.id
        values = {
            key: value
            for key, value in self.task.__dict__.items()
            if not key.startswith("_")
        }
        values.update({key: value for key, value in changes.items() if key in values})
        self.task = Task(**values)
        return self.task

    def list_events(self, **filters):
        self.work_event_reads += 1
        values = list(self.events)
        category = filters.get("category")
        if category is not None:
            values = [item for item in values if category in item.categories]
        description = filters.get("description")
        if description is not None:
            values = [item for item in values if item.description == description]
        return values

    def create_event(self, event):
        copied = replace(
            event,
            id=f"w{self.next_event_id}",
            categories=list(event.categories),
        )
        self.next_event_id += 1
        setattr(copied, "_caldav_collection_url", getattr(event, "_caldav_collection_url"))
        self.events.append(copied)
        return copied

    def update_event(self, event_id, changes, *, etag=None):
        for index, event in enumerate(self.events):
            if event.id != event_id:
                continue
            values = {
                key: value
                for key, value in event.__dict__.items()
                if not key.startswith("_")
            }
            values.update({key: value for key, value in changes.items() if key in values})
            updated = Event(**values)
            setattr(updated, "_caldav_collection_url", getattr(event, "_caldav_collection_url"))
            self.events[index] = updated
            return updated
        raise KeyError(event_id)

    def delete_event(self, event_id, *, etag=None):
        self.events = [event for event in self.events if event.id != event_id]


def _bundled_extensions_dir() -> Path:
    import caldav_assistant

    return Path(caldav_assistant.__file__).resolve().parent / "builtin_extensions"


def _load_wordpress_extension(service, activity, worklog, wordpress, settings):
    hooks = HookRegistry()
    ctx = SimpleNamespace(
        tasks=service,
        activity=activity,
        session=SimpleNamespace(worklog=worklog),
        wordpress=wordpress,
        settings=settings,
    )
    bind_current_context(ctx)
    _bind_hook_registrar(hooks)
    manager = ExtensionManager(
        CommandService(CommandRegistry()),
        hooks,
        settings,
        bundled_root=_bundled_extensions_dir(),
    )
    record = manager.load("wordpress_work_session_log")
    assert record.status == "loaded"
    return manager


def _cleanup():
    _bind_hook_registrar(None)
    clear_current_context()


def _build_work_service(*, completion=False):
    adapter = Adapter()
    clock = Clock()
    worklog = WorkLogService(adapter, lambda: WORK_URL, clock=clock)
    activity = ActivityService(Repo(), clock=clock)
    session = CalDAVSessionService(worklog)
    wordpress = WordPress()
    if completion:
        completion_log = TaskCompletionLogService(worklog, wordpress, Settings())
        service = CompletionLoggingTaskService(
            adapter,
            activity,
            None,
            session,
            worklog=worklog,
            completion_log=completion_log,
        )
    else:
        service = CalDAVWorkTaskService(adapter, activity, None, session, worklog=worklog)
    session.bind_tasks(service)
    return adapter, clock, worklog, activity, service, wordpress


def test_default_wordpress_pause_hook_does_not_re_read_task_or_work_collections():
    adapter, clock, worklog, activity, service, wordpress = _build_work_service()
    settings = Settings()
    try:
        _load_wordpress_extension(service, activity, worklog, wordpress, settings)
        service.start("t1")
        clock.advance(10)

        before_work = adapter.work_event_reads
        before_tasks = adapter.task_list_reads
        service.pause(adapter.task)

        assert adapter.work_event_reads - before_work == 1
        assert adapter.task_list_reads - before_tasks == 0
        assert len(wordpress.calls) == 1
        assert wordpress.calls[0][0].endswith(" Anki")
    finally:
        _cleanup()


def test_completion_logger_reuses_just_closed_segment_without_work_history_reread():
    adapter, clock, _worklog, _activity, service, wordpress = _build_work_service(
        completion=True
    )
    service.start("t1")
    clock.advance(25)

    before_work = adapter.work_event_reads
    result = service.complete(adapter.task)

    assert result.success is True
    assert adapter.work_event_reads - before_work == 1
    assert len(wordpress.calls) == 1
    assert wordpress.calls[0][0].endswith(" Anki")


def test_completing_paused_task_uses_bounded_open_and_task_history_reads_without_duplicate_wordpress_log():
    adapter, clock, _worklog, _activity, service, wordpress = _build_work_service(
        completion=True
    )
    service.start("t1")
    clock.advance(10)
    service.pause(adapter.task)
    # This test does not load the pause extension, so WordPress is still empty.
    assert wordpress.calls == []

    before_work = adapter.work_event_reads
    result = service.complete(adapter.task)

    assert result.success is True
    # A paused completion needs two bounded facts: the global OPEN set and this
    # Task's own history.  The completion logger must not add a third history read.
    assert adapter.work_event_reads - before_work == 2
    assert wordpress.calls == []
