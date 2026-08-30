from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
from types import SimpleNamespace

import pytest

from caldav_assistant.api import Event, Task
from caldav_assistant.internal.cli import monitor_app
from caldav_assistant.internal.runtime.observable_service import ObservableAssistantService


class FakeScheduler:
    def __init__(self):
        self.value = 10.0

    def monotonic(self):
        return self.value

    def reminder_delay(self, reminders, *, max_delay):
        return 7.0

    def wait(self, delay, stop_event):
        return None


class FakeReminders:
    def __init__(self, sent=(), error=None):
        self.sent = list(sent)
        self.error = error
        self.notifications = SimpleNamespace(adapter=FakeNotificationAdapter())

    def process_due(self):
        if self.error is not None:
            raise self.error
        return list(self.sent)


class FakeNotificationAdapter:
    pass


class DummyIPC:
    def serve_forever(self, handler, stop_event, on_ready=None):
        if on_ready:
            on_ready()

    def close(self):
        return None


class DummyDispatcher:
    def handle(self, method, payload):
        return {"method": method, "payload": payload}


def make_service(reminders):
    return ObservableAssistantService(
        sync=SimpleNamespace(),
        reminders=reminders,
        wordpress=SimpleNamespace(),
        ipc_server=DummyIPC(),
        dispatcher=DummyDispatcher(),
        scheduler=FakeScheduler(),
        max_idle=30,
    )


def test_observable_service_publishes_only_confirmed_deliveries():
    request = SimpleNamespace(
        key="task:t1:due",
        when=datetime(2026, 8, 30, 15, 0, tzinfo=timezone.utc),
        title="Task due: Anki",
        body="Anki is due now.",
        source="task_due",
        object_id="t1",
        metadata={"kind": "task"},
    )
    service = make_service(FakeReminders([request]))

    service._run_reminder_cycle()

    events = service.delivery_events(after=0)
    assert len(events) == 1
    event = events[0]
    assert event["source"] == "task_due"
    assert event["object_id"] == "t1"
    assert event["title"] == "Task due: Anki"
    assert event["adapter"] == "FakeNotificationAdapter"
    assert event["result"] == "delivered"
    assert service.delivery_cursor() == 1
    assert service._next_reminder_wake == 17.0


def test_observable_service_does_not_publish_failed_delivery_cycle():
    service = make_service(FakeReminders(error=RuntimeError("notify failed")))

    service._run_reminder_cycle()

    assert service.delivery_events() == []
    assert "reminders.process_due" in service.status()["last_errors"]


def test_runtime_event_feed_is_read_only_and_cursor_based():
    first = SimpleNamespace(
        key="a",
        when=datetime(2026, 8, 30, 15, 0, tzinfo=timezone.utc),
        title="A",
        body="",
        source="event_start",
        object_id="e1",
        metadata={},
    )
    second = SimpleNamespace(
        key="b",
        when=datetime(2026, 8, 30, 16, 0, tzinfo=timezone.utc),
        title="B",
        body="",
        source="task_due",
        object_id="t2",
        metadata={},
    )
    service = make_service(FakeReminders())
    service._publish_delivery(first)
    service._publish_delivery(second)

    assert service._handle_request("runtime.events.cursor") == {"cursor": 2}
    events = service._handle_request("runtime.events.list", {"after": 1})
    assert [item["seq"] for item in events] == [2]
    assert service.delivery_cursor() == 2


class FakeIO:
    def __init__(self, choices=()):
        self.stdout = StringIO()
        self.out = []
        self.choices = iter(choices)

    def write(self, value=""):
        self.out.append(str(value))

    def read(self, prompt=""):
        return next(self.choices)


class FakeUI:
    def __init__(self, io):
        self.io = io

    def show(self, value):
        self.io.write(value)


def make_monitor_app(*, current=None, selected=None, choices=()):
    io = FakeIO(choices)

    class Session:
        current_selection = selected

        def current_task(self):
            return current

    ctx = SimpleNamespace(session=Session(), ui=FakeUI(io))
    return SimpleNamespace(ctx=ctx, io=io)


def test_monitor_target_prioritizes_actual_current_work_over_selection():
    current = Task(id="t1", summary="Anki", status="IN-PROCESS")
    selected = Event(id="e1", summary="Class")
    app = make_monitor_app(current=current, selected=selected)

    target = monitor_app._monitor_target(app)

    assert target.kind == "task"
    assert target.object_id == "t1"
    assert target.current_work is True


def test_delivered_event_rings_bell_and_prints_actual_access_report():
    task = Task(id="t1", summary="Anki", status="IN-PROCESS")
    app = make_monitor_app(current=task)
    target = monitor_app._monitor_target(app)

    monitor_app._show_delivery(
        app,
        {
            "seq": 1,
            "occurred_at": "2026-08-30T15:00:00+00:00",
            "source": "task_due",
            "object_id": "t1",
            "title": "Task due: Anki",
            "body": "Due now",
            "adapter": "LinuxNotificationAdapter",
            "result": "delivered",
        },
        target,
    )

    assert "\a" in app.io.stdout.getvalue()
    text = "\n".join(app.io.out)
    assert "Local IPC -> runtime.events.list" in text
    assert "ReminderService.process_due" in text
    assert "LinuxNotificationAdapter" in text
    assert "Task/Event state: unchanged" in text


def test_ctrl_c_menu_for_current_task_can_continue_without_mutating(monkeypatch):
    task = Task(id="t1", summary="Anki", status="IN-PROCESS")
    app = make_monitor_app(current=task, choices=["3"])
    target = monitor_app._monitor_target(app)

    assert monitor_app._interrupt_menu(app, target) == "monitor"
    assert "Complete this Task" in "\n".join(app.io.out)


def test_monitor_loop_uses_background_feed_and_ctrl_c_opens_menu(monkeypatch):
    task = Task(id="t1", summary="Anki", status="IN-PROCESS")
    app = make_monitor_app(current=task, choices=["3"])
    app.runtime = SimpleNamespace(
        call=lambda method, **payload: {"cursor": 0}
        if method == "runtime.events.cursor"
        else []
    )
    target = monitor_app._monitor_target(app)

    def interrupt(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(monitor_app, "sleep", interrupt)

    assert monitor_app._monitor(app, target) == "monitor"
    output = "\n".join(app.io.out)
    assert "No command prompt is active now" in output
    assert "Press Ctrl-C" in output
