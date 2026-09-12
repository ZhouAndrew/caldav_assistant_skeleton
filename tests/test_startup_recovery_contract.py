from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event as ThreadEvent
from time import sleep
from types import SimpleNamespace

import pytest

from caldav_assistant.api import Agenda, Event, Task
from caldav_assistant.api.v1.errors import UnavailableError
from caldav_assistant.internal.agenda import AgendaEngine, AgendaService, NextEngine
from caldav_assistant.internal.cli import conversation_app, latency_guard
from caldav_assistant.internal.runtime.ipc import IPCTimeoutError
from caldav_assistant.internal.runtime.service import AssistantService
from caldav_assistant.internal.session import CalDAVSessionService
from caldav_assistant.internal.worklog import WorkLogService


class _BuildEngine:
    def build(self, tasks, events, **options):
        return Agenda()

    def candidates(self, tasks, events):
        return Agenda()


class _NextEngine:
    def choose(self, agenda, **options):
        return None


class _Query:
    def __init__(self, values=()):
        self.values = list(values)
        self.calls = 0

    def list(self, **filters):
        self.calls += 1
        return list(self.values)


def test_overlapping_startup_retry_does_not_duplicate_caldav_reads():
    entered = ThreadEvent()
    release = ThreadEvent()

    class SlowTasks(_Query):
        def list(self, **filters):
            self.calls += 1
            entered.set()
            assert release.wait(1.0)
            return list(self.values)

    tasks = SlowTasks([Task(id="t1", summary="One")])
    events = _Query()
    service = AgendaService(tasks, events, _BuildEngine(), _NextEngine(), {})

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.startup_snapshot, days=2, kind="task")
        assert entered.wait(0.5)
        second = pool.submit(service.startup_snapshot, days=2, kind="task")
        sleep(0.03)
        assert tasks.calls == 1
        release.set()
        first_result = first.result(timeout=1.0)
        second_result = second.result(timeout=1.0)

    assert first_result is second_result
    assert tasks.calls == 1
    assert events.calls == 1


def test_live_startup_deadline_falls_back_to_explicitly_stale_snapshot():
    task = Task(id="cached", summary="Cached Task", stale=True)

    class Runtime:
        def __init__(self):
            self.calls = []

        def ping(self, *, timeout=None):
            return True

        def call(self, method, **payload):
            raise AssertionError("private bounded path must be used")

        def _execute(self, method, payload, *, timeout=None):
            self.calls.append((method, timeout))
            if method == "agenda.startup_snapshot":
                raise IPCTimeoutError("slow live read")
            assert method == "agenda.cached_startup_snapshot"
            return {
                "agenda": Agenda(),
                "recommendation": task,
                "current_task": None,
                "tasks": (task,),
                "stale": True,
            }

    runtime = Runtime()
    snapshot = latency_guard._read_snapshot(
        SimpleNamespace(conversation=conversation_app),
        SimpleNamespace(runtime=runtime, ctx=SimpleNamespace(settings=None)),
    )

    assert runtime.calls == [
        ("agenda.startup_snapshot", latency_guard.STARTUP_READ_TIMEOUT_SECONDS),
        (
            "agenda.cached_startup_snapshot",
            latency_guard.STARTUP_CACHE_FALLBACK_TIMEOUT_SECONDS,
        ),
    ]
    assert snapshot.stale is True
    assert [task.id for task in snapshot.tasks] == ["cached"]
    assert snapshot.recommended.id == "cached"


def test_live_timeout_without_verified_snapshot_remains_unknown_not_empty():
    class Runtime:
        def ping(self, *, timeout=None):
            return True

        def _execute(self, method, payload, *, timeout=None):
            if method == "agenda.startup_snapshot":
                raise IPCTimeoutError("slow live read")
            raise UnavailableError("No verified snapshot")

    with pytest.raises(UnavailableError, match="no verified cache fallback"):
        latency_guard._bounded_read_call(
            SimpleNamespace(runtime=Runtime()),
            "agenda.startup_snapshot",
        )


def test_cached_startup_route_never_calls_live_task_event_or_work_services():
    cached_task = Task(id="t1", summary="Cached", stale=True)
    cached_event = Event(
        id="e1",
        summary="Cached Event",
        start=datetime.now(timezone.utc) + timedelta(hours=1),
        stale=True,
    )

    class Session:
        cached_calls = 0

        def cached_startup_snapshot(self, tasks):
            self.cached_calls += 1
            return {"current_task_id": None, "worked_task_ids": ()}

        def startup_snapshot(self, tasks, *, work_facts=None):
            assert work_facts == {"current_task_id": None, "worked_task_ids": ()}
            return {
                "current_task_id": None,
                "current_task": None,
                "paused_task_ids": (),
            }

    live_tasks = SimpleNamespace(list=lambda **filters: pytest.fail("live Task read"))
    live_events = SimpleNamespace(list=lambda **filters: pytest.fail("live Event read"))
    session = Session()
    service = AgendaService(
        live_tasks,
        live_events,
        AgendaEngine(),
        NextEngine(),
        {},
        session=session,
        cached_tasks=lambda **filters: [cached_task],
        cached_events=lambda: [cached_event],
    )

    result = service.cached_startup_snapshot(days=2, kind="task")

    assert result["stale"] is True
    assert result["agenda"].stale is True
    assert [task.id for task in result["tasks"]] == ["t1"]
    assert session.cached_calls == 1


def test_startup_work_read_requests_only_open_intervals_not_closed_history():
    work_url = "https://dav.example/work"
    now = datetime(2026, 9, 12, 8, 0, tzinfo=timezone.utc)
    open_event = Event(
        id="open",
        summary="Work",
        start=now,
        description=WorkLogService._description("t1"),
        categories=[WorkLogService.CATEGORY, WorkLogService.OPEN_CATEGORY],
    )
    setattr(open_event, "_caldav_collection_url", work_url)

    class Adapter:
        def __init__(self):
            self.calls = []

        def list_events_in_collection(self, collection_url, **filters):
            self.calls.append((collection_url, dict(filters)))
            return [open_event]

    adapter = Adapter()
    session = CalDAVSessionService(WorkLogService(adapter, lambda: work_url))

    facts = session.startup_work_facts()

    assert facts == {"current_task_id": "t1", "worked_task_ids": None}
    assert adapter.calls == [
        (work_url, {"category": WorkLogService.OPEN_CATEGORY})
    ]


def test_guided_start_reuses_snapshot_tasks_and_known_current(monkeypatch):
    task = Task(id="t1", summary="Cached choice", stale=True)
    chosen = []

    class UI:
        def choose(self, title, items, **options):
            chosen.extend(items)
            return items[0]

        def choose_task(self, **options):
            raise AssertionError("must not perform a second tasks.list")

        def show(self, value):
            return None

    app = SimpleNamespace(
        ctx=SimpleNamespace(
            ui=UI(),
            session=SimpleNamespace(
                current_task=lambda: pytest.fail("must reuse known current state")
            ),
        )
    )
    monkeypatch.setattr(conversation_app, "_duration_choice", lambda app: False)

    result = conversation_app._guided_start(
        app,
        known_current=None,
        task_choices=(task,),
    )

    assert result == "console"
    assert chosen == [task]


def test_background_startup_grace_prevents_foreground_contention():
    sync_started = ThreadEvent()
    reminder_started = ThreadEvent()
    wordpress_started = ThreadEvent()

    class Scheduler:
        def __init__(self):
            self.now = 100.0
            self.waits = 0

        def monotonic(self):
            return self.now

        def reminder_delay(self, reminders, *, max_delay):
            return max_delay

        def wait(self, seconds, stop_event):
            self.waits += 1
            if self.waits == 1:
                assert seconds == pytest.approx(10.0)
                assert not sync_started.is_set()
                assert not reminder_started.is_set()
                assert not wordpress_started.is_set()
                self.now += seconds
                return False
            deadline = datetime.now().timestamp() + 0.5
            while datetime.now().timestamp() < deadline:
                if all(
                    event.is_set()
                    for event in (sync_started, reminder_started, wordpress_started)
                ):
                    break
                sleep(0.005)
            stop_event.set()
            return True

    service = AssistantService(
        SimpleNamespace(incremental_sync=sync_started.set),
        SimpleNamespace(process_due=reminder_started.set),
        SimpleNamespace(flush=wordpress_started.set),
        SimpleNamespace(),
        SimpleNamespace(),
        Scheduler(),
        maintenance_startup_grace=10.0,
    )

    service._maintenance_loop()

    assert sync_started.is_set()
    assert reminder_started.is_set()
    assert wordpress_started.is_set()
