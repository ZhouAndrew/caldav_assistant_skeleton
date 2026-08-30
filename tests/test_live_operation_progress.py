from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from threading import Event as ThreadEvent
from types import SimpleNamespace

from caldav_assistant.api import Event, Task
from caldav_assistant.internal.cli import monitor_app
from caldav_assistant.internal.cli.actions import BuiltinActions
from caldav_assistant.internal.cli.presenter import render_lines
from caldav_assistant.internal.session import CalDAVSessionService
from caldav_assistant.internal.tasks import CalDAVWorkTaskService
from caldav_assistant.internal.worklog import WorkLogService


class _IO:
    def __init__(self):
        self.out: list[str] = []

    def write(self, value=""):
        self.out.append(str(value))


class _Runtime:
    def __init__(self):
        self.started = ThreadEvent()
        self.release = ThreadEvent()
        self.operation_id = None
        self.sent_progress = False

    def call(self, method: str, **payload):
        if method == "runtime.events.cursor":
            return {"cursor": 0}
        if method == "runtime.events.list":
            if self.started.is_set() and not self.sent_progress:
                self.sent_progress = True
                self.release.set()
                return [
                    {
                        "seq": 1,
                        "kind": "operation_progress",
                        "operation_id": self.operation_id,
                        "stage": "worklog.close",
                        "state": "done",
                        "message": "CalDAV Work interval closed.",
                    }
                ]
            return []
        if method == "tasks.pause":
            self.operation_id = payload.get("__operation_id")
            self.started.set()
            assert self.release.wait(1.0)
            return None
        raise AssertionError(method)


def test_execute_visible_prints_progress_before_command_finishes(monkeypatch):
    io = _IO()
    runtime = _Runtime()
    app = SimpleNamespace(
        io=io,
        runtime=runtime,
        ctx=SimpleNamespace(
            ui=SimpleNamespace(show=io.write),
            session=SimpleNamespace(current_task=lambda: None, current_selection=None),
        ),
    )

    def execute(_app, _parsed, *, paginate=True):
        _app.runtime.call("tasks.pause", task="t1")
        return 0, False

    monkeypatch.setattr(monitor_app.base, "_execute", execute)

    code, should_exit = monitor_app._execute_visible(
        app,
        monitor_app._parsed("pause"),
        paginate=False,
    )

    assert code == 0
    assert should_exit is False
    text = "\n".join(io.out)
    assert "Primary access path" not in text
    assert "CalDAV Work interval closed." in text
    assert text.index("CalDAV Work interval closed.") < text.index("=== Command result ===")
    assert runtime.operation_id


class _Adapter:
    def __init__(self):
        self.task = Task(id="t1", summary="clear math question queue", status="NEEDS-ACTION")
        self.events: list[Event] = []

    def get_task(self, task_id):
        return self.task

    def list_tasks(self, **filters):
        items = [self.task]
        for key, value in filters.items():
            items = [item for item in items if getattr(item, key) == value]
        return items

    def update_task(self, task_id, changes, *, etag=None):
        values = {k: v for k, v in self.task.__dict__.items() if not k.startswith("_")}
        values.update({k: v for k, v in changes.items() if k in values})
        self.task = Task(**values)
        return self.task

    def list_events(self, **filters):
        result = list(self.events)
        category = filters.get("category")
        if category is not None:
            result = [item for item in result if category in item.categories]
        return result

    def create_event(self, event):
        created = replace(event, id="w1", categories=list(event.categories))
        setattr(created, "_caldav_collection_url", getattr(event, "_caldav_collection_url", None))
        self.events.append(created)
        return created

    def update_event(self, event_id, changes, *, etag=None):
        event = self.events[0]
        values = {k: v for k, v in event.__dict__.items() if not k.startswith("_")}
        values.update({k: v for k, v in changes.items() if k in values})
        updated = Event(**values)
        setattr(updated, "_caldav_collection_url", getattr(event, "_caldav_collection_url", None))
        self.events[0] = updated
        return updated


class _Activity:
    def __init__(self):
        self.items = []

    def record(self, action, object_id=None, **metadata):
        self.items.append(SimpleNamespace(action=action, object_id=object_id, metadata=metadata))

    def for_task(self, task):
        uid = str(getattr(task, "id", task))
        return [item for item in self.items if item.object_id == uid]


def test_pause_then_current_is_not_the_paused_in_process_task():
    adapter = _Adapter()
    activity = _Activity()
    worklog = WorkLogService(
        adapter,
        lambda: "https://dav.example/work/",
        clock=lambda: datetime(2026, 8, 30, 13, 32, tzinfo=timezone.utc),
    )
    session = CalDAVSessionService(worklog, activity=activity)
    tasks = CalDAVWorkTaskService(adapter, activity, None, session, worklog=worklog)
    session.bind_tasks(tasks)

    tasks.start("t1")
    assert session.current_task_id() == "t1"
    tasks.pause("t1")

    assert adapter.task.status == "IN-PROCESS"
    assert session.current_task_id() is None
    assert session.paused_task_ids() == ("t1",)

    ctx = SimpleNamespace(session=session, activity=activity)
    current = BuiltinActions(ctx).current()
    lines = render_lines(current)
    text = "\n".join(lines or [str(current)])
    assert "No task is active right now" in text
    assert "paused work" in text
    assert "clear math question queue" not in text
