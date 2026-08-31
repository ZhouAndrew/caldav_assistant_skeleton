from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace

from caldav_assistant.internal.agenda.service import AgendaService
from caldav_assistant.internal.cli import live_command
from caldav_assistant.internal.work_period import WorkPeriodService


class FakeReminders:
    def __init__(self):
        self.items = []

    def create(self, title, when, **metadata):
        item = SimpleNamespace(
            id=f"r{len(self.items) + 1}",
            title=title,
            when=when,
            metadata=dict(metadata),
        )
        self.items.append(item)
        return item

    def list(self, kind=None, task_id=None):
        return [
            item
            for item in self.items
            if (kind is None or item.metadata.get("kind") == kind)
            and (task_id is None or item.metadata.get("task_id") == task_id)
        ]

    def cancel(self, item):
        self.items.remove(item)
        return item


class FakeSession:
    def current_task_id(self):
        return "task-1"

    def paused_task_ids(self):
        return ()


class FakeTasks:
    def get(self, task_id):
        return SimpleNamespace(id=task_id, summary="Timing regression")


def test_work_period_deadline_is_anchored_to_actual_task_start():
    actual_start = datetime(2026, 8, 31, 1, 9, 7, tzinfo=timezone.utc)
    allocation_time = actual_start + timedelta(seconds=21)
    reminders = FakeReminders()
    service = WorkPeriodService(
        reminders,
        session=FakeSession(),
        tasks=FakeTasks(),
        clock=lambda: allocation_time,
    )

    status = service.allocate(
        "task-1",
        30,
        started_at=actual_start.isoformat(),
    )

    assert status["deadline"] == (actual_start + timedelta(seconds=30)).isoformat()
    assert status["remaining_seconds"] == 9
    assert status["duration_seconds"] == 30
    assert status["started_at"] == actual_start.isoformat()
    assert reminders.items[0].metadata["started_at"] == actual_start.isoformat()


def test_live_runner_handles_ctrl_c_without_abandoning_authoritative_result(monkeypatch):
    class Runtime:
        def call(self, method, **payload):
            if method == "runtime.events.cursor":
                return {"cursor": 0}
            if method == "runtime.events.list":
                return []
            raise AssertionError(method)

    app = SimpleNamespace(runtime=Runtime())
    interrupted = []
    finished = Event()
    real_sleep = live_command.sleep
    calls = 0

    def interrupt_once(seconds):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise KeyboardInterrupt
        real_sleep(seconds)

    monkeypatch.setattr(live_command, "sleep", interrupt_once)

    def operation():
        finished.wait(0.04)
        return "authoritative-result"

    result = live_command.run_with_live_progress(
        app,
        operation,
        on_progress=lambda event: None,
        on_interrupt=lambda: interrupted.append(True),
        poll_interval=0.01,
    )

    assert result == "authoritative-result"
    assert interrupted == [True]


def test_startup_snapshot_reads_task_and_event_sources_once():
    class CountingSource:
        def __init__(self, values):
            self.values = list(values)
            self.calls = 0

        def list(self, **filters):
            self.calls += 1
            return list(self.values)

    tasks = CountingSource([SimpleNamespace(id="t1")])
    events = CountingSource([SimpleNamespace(id="e1", categories=())])

    class Engine:
        def build(self, task_values, event_values, **kwargs):
            return (tuple(task_values), tuple(event_values), kwargs["days"])

        def candidates(self, task_values, event_values):
            return [*task_values, *event_values]

    class NextEngine:
        def choose(self, agenda, kind=None, **options):
            return agenda[0]

    service = AgendaService(
        tasks,
        events,
        Engine(),
        NextEngine(),
        state={},
        session=FakeSession(),
    )

    value = service.startup_snapshot(days=2, kind="task")

    assert tasks.calls == 1
    assert events.calls == 1
    assert value["recommendation"].id == "t1"
    assert value["agenda"][2] == 2
