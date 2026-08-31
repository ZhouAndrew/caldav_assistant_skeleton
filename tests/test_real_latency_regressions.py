from __future__ import annotations

from datetime import datetime, timezone
from threading import get_ident
from time import sleep
from types import SimpleNamespace

import pytest

from caldav_assistant.api import Event, Task
from caldav_assistant.api.v1.errors import UnavailableError
from caldav_assistant.internal.agenda.service import AgendaService
from caldav_assistant.internal.caldav.routing import CollectionRoutingCalDAVAdapter
from caldav_assistant.internal.cli import latency_guard
from caldav_assistant.internal.cli.live_command import run_with_live_progress
from caldav_assistant.internal.runtime.ipc import IPCTimeoutError
from caldav_assistant.internal.session.caldav import CalDAVSessionService
from caldav_assistant.internal.worklog.service import WorkLogService


class _Calendar:
    def __init__(self, url, *, todos=(), events=()):
        self.url = url
        self.todos = list(todos)
        self.events = list(events)
        self.todo_reads = 0
        self.event_reads = 0

    def get_todos(self, *, include_completed=True):
        assert include_completed is True
        self.todo_reads += 1
        return list(self.todos)

    def get_events(self):
        self.event_reads += 1
        return list(self.events)


class _ConcreteAdapter:
    base_url = "https://dav.example/"

    def __init__(self, calendars):
        self.calendars = list(calendars)
        self.discovery_calls = 0
        self.generic_task_reads = 0
        self.generic_event_reads = 0

    def _calendars(self):
        self.discovery_calls += 1
        return list(self.calendars)

    @staticmethod
    def _to_task(resource, calendar):
        task = Task(
            id=resource.id,
            summary=resource.summary,
            status=resource.status,
            categories=list(resource.categories),
        )
        setattr(task, "_caldav_collection_url", calendar.url)
        return task

    @staticmethod
    def _to_event(resource, calendar):
        event = Event(
            id=resource.id,
            summary=resource.summary,
            start=resource.start,
            end=resource.end,
            description=resource.description,
            categories=list(resource.categories),
        )
        setattr(event, "_caldav_collection_url", calendar.url)
        return event

    def list_tasks(self, **filters):
        self.generic_task_reads += 1
        raise AssertionError("selected Task role must not scan generic collections")

    def list_events(self, **filters):
        self.generic_event_reads += 1
        raise AssertionError("selected Event/Work role must not scan generic collections")


WORK_DESCRIPTION = "CalDAV Assistant Work Segment\nTask-UID: t1"


def test_selected_roles_share_one_collection_discovery_and_skip_decoys():
    task_calendar = _Calendar(
        "https://dav.example/tasks/",
        todos=[Task(id="t1", summary="Homework")],
    )
    event_calendar = _Calendar(
        "https://dav.example/events/",
        events=[Event(id="e1", summary="Class")],
    )
    work_calendar = _Calendar(
        "https://dav.example/work/",
        events=[
            Event(
                id="w1",
                summary="Work — Homework",
                description=WORK_DESCRIPTION,
                categories=[WorkLogService.CATEGORY, WorkLogService.OPEN_CATEGORY],
            )
        ],
    )
    decoy = _Calendar(
        "https://dav.example/decoy/",
        todos=[Task(id="x", summary="Do not scan")],
        events=[Event(id="x", summary="Do not scan")],
    )
    inner = _ConcreteAdapter([task_calendar, event_calendar, work_calendar, decoy])
    routed = CollectionRoutingCalDAVAdapter(
        inner,
        task_collection_url=lambda: "https://dav.example/tasks/",
        event_collection_url=lambda: "https://dav.example/events/",
    )

    tasks = routed.list_tasks()
    events = routed.list_events()
    work = routed.list_events_in_collection(
        "https://dav.example/work/",
        category=WorkLogService.CATEGORY,
    )

    assert [item.id for item in tasks] == ["t1"]
    assert [item.id for item in events] == ["e1"]
    assert [item.id for item in work] == ["w1"]
    assert inner.discovery_calls == 1
    assert inner.generic_task_reads == 0
    assert inner.generic_event_reads == 0
    assert task_calendar.todo_reads == 1
    assert event_calendar.event_reads == 1
    assert work_calendar.event_reads == 1
    assert decoy.todo_reads == 0
    assert decoy.event_reads == 0


class _ScopedWorkAdapter:
    def __init__(self, event):
        self.event = event
        self.scoped_calls = []

    def list_events_in_collection(self, collection_url, **filters):
        self.scoped_calls.append((collection_url, filters))
        return [self.event]

    def list_events(self, **filters):
        raise AssertionError("WorkLog must use its configured collection fast path")


def test_worklog_reads_only_its_configured_collection_when_supported():
    event = Event(
        id="w1",
        summary="Work — Homework",
        description=WORK_DESCRIPTION,
        categories=[WorkLogService.CATEGORY],
    )
    setattr(event, "_caldav_collection_url", "https://dav.example/work/")
    adapter = _ScopedWorkAdapter(event)
    service = WorkLogService(adapter, lambda: "https://dav.example/work/")

    assert [item.id for item in service._all_work_events()] == ["w1"]
    assert adapter.scoped_calls == [
        ("https://dav.example/work/", {"category": WorkLogService.CATEGORY})
    ]


class _Query:
    def __init__(self, values):
        self.values = list(values)
        self.calls = 0

    def list(self, **filters):
        self.calls += 1
        return list(self.values)


class _AgendaEngine:
    def build(self, tasks, events, **kwargs):
        return SimpleNamespace(items=[])

    def candidates(self, tasks, events):
        return "candidates"


class _NextEngine:
    def __init__(self):
        self.kwargs = None

    def choose(self, agenda, **kwargs):
        self.kwargs = kwargs
        return "recommended"


class _StartupSession:
    def __init__(self, current):
        self.current = current
        self.snapshot_calls = 0

    def startup_snapshot(self, tasks):
        self.snapshot_calls += 1
        assert self.current in tasks
        return {
            "current_task_id": self.current.id,
            "current_task": self.current,
            "paused_task_ids": ("paused",),
        }

    def current_task_id(self):
        raise AssertionError("startup must not re-read current Session state")

    def paused_task_ids(self):
        raise AssertionError("startup must not re-read paused Session state")


def test_agenda_startup_reuses_one_source_set_and_one_session_snapshot():
    current = Task(id="current", summary="Current", status="IN-PROCESS")
    tasks = _Query([current, Task(id="paused", summary="Paused", status="IN-PROCESS")])
    events = _Query([])
    session = _StartupSession(current)
    next_engine = _NextEngine()
    service = AgendaService(
        tasks,
        events,
        _AgendaEngine(),
        next_engine,
        {},
        session=session,
    )

    result = service.startup_snapshot(days=2, kind="task")

    assert tasks.calls == 1
    assert events.calls == 1
    assert session.snapshot_calls == 1
    assert result["current_task"] is current
    assert result["recommendation"] == "recommended"
    assert next_engine.kwargs["current_task_uid"] == "current"
    assert next_engine.kwargs["skipped_uids"] == ("paused",)


class _WorkSnapshot:
    def __init__(self, events):
        self.events = list(events)
        self.reads = 0

    def configured(self):
        return True

    def _all_work_events(self):
        self.reads += 1
        return list(self.events)

    @staticmethod
    def _is_open(event):
        return WorkLogService._is_open(event)

    @staticmethod
    def _task_id_from_event(event):
        return WorkLogService._task_id_from_event(event)


def _work_event(event_id, task_id, *, open_segment):
    categories = [WorkLogService.CATEGORY]
    if open_segment:
        categories.append(WorkLogService.OPEN_CATEGORY)
    return Event(
        id=event_id,
        summary=f"Work — {task_id}",
        start=datetime(2026, 8, 31, 1, 0, tzinfo=timezone.utc),
        end=None if open_segment else datetime(2026, 8, 31, 1, 10, tzinfo=timezone.utc),
        description=f"{WorkLogService.DESCRIPTION_HEADER}\n{WorkLogService.TASK_PREFIX}{task_id}",
        categories=categories,
    )


def test_session_startup_reads_worklog_once_and_reuses_supplied_tasks():
    work = _WorkSnapshot(
        [
            _work_event("w1", "t1", open_segment=True),
            _work_event("w2", "t2", open_segment=False),
        ]
    )
    session = CalDAVSessionService(work, tasks=SimpleNamespace(list=lambda **_: pytest.fail("task re-read")))
    t1 = Task(id="t1", summary="One", status="IN-PROCESS")
    t2 = Task(id="t2", summary="Two", status="IN-PROCESS")

    result = session.startup_snapshot([t1, t2])

    assert work.reads == 1
    assert result["current_task"] is t1
    assert result["current_task_id"] == "t1"
    assert result["paused_task_ids"] == ("t2",)


class _ProgressRuntime:
    def call(self, method, **payload):
        if method == "runtime.events.cursor":
            return {"cursor": 0}
        if method == "runtime.events.list":
            return []
        raise AssertionError(method)


class _HumanWaitIO:
    def __init__(self):
        self.waiting_for_input = False


def test_live_progress_never_calls_human_think_time_still_working():
    io = _HumanWaitIO()
    app = SimpleNamespace(io=io, runtime=_ProgressRuntime())
    heartbeats = []

    def operation():
        io.waiting_for_input = True
        sleep(0.08)
        return "chosen"

    value = run_with_live_progress(
        app,
        operation,
        on_progress=lambda event: None,
        on_heartbeat=heartbeats.append,
        poll_interval=0.005,
        heartbeat_after=0.0,
        heartbeat_every=0.01,
    )

    assert value == "chosen"
    assert heartbeats == []


def test_startup_read_has_a_separate_read_only_latency_budget():
    class Runtime:
        def __init__(self):
            self.timeout = None

        def ping(self, *, timeout=None):
            return True

        def _execute(self, method, payload, *, timeout=None):
            self.timeout = timeout
            return {"ok": True}

    runtime = Runtime()
    app = SimpleNamespace(runtime=runtime)

    assert latency_guard._bounded_read_call(app, "agenda.startup_snapshot") == {"ok": True}
    assert runtime.timeout == latency_guard.STARTUP_READ_TIMEOUT_SECONDS


def test_startup_read_timeout_is_reported_as_unavailable_not_a_fake_empty_agenda():
    class Runtime:
        def ping(self, *, timeout=None):
            return True

        def _execute(self, method, payload, *, timeout=None):
            raise IPCTimeoutError("slow")

    with pytest.raises(UnavailableError, match="Startup live read exceeded 8s"):
        latency_guard._bounded_read_call(
            SimpleNamespace(runtime=Runtime()),
            "agenda.startup_snapshot",
        )


def test_modal_shell_execution_runs_on_the_calling_main_thread():
    caller = get_ident()
    seen = []
    shown = []
    rendered = []

    def execute_command(app, parsed):
        seen.append(get_ident())
        return SimpleNamespace(exit_code=0, should_exit=False, result="ok")

    module = SimpleNamespace(
        conversation=SimpleNamespace(_show=lambda app, text: shown.append(text)),
        legacy=SimpleNamespace(_split_lifecycle_duration=lambda parsed: (parsed, None)),
        base=SimpleNamespace(
            execute_command=execute_command,
            _render_result=lambda app, result, paginate=True: rendered.append(result),
        ),
        _execute_user_unbounded=lambda app, parsed, paginate=True: pytest.fail("unexpected worker path"),
    )
    parsed = SimpleNamespace(raw="history", name="history", args=())

    code, should_exit = latency_guard._execute_shell_on_main(
        module,
        SimpleNamespace(),
        parsed,
        paginate=False,
    )

    assert (code, should_exit) == (0, False)
    assert seen == [caller]
    assert rendered == ["ok"]
    assert not any("Still working" in line for line in shown)
