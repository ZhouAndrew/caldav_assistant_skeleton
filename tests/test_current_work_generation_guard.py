from __future__ import annotations

from types import SimpleNamespace

import pytest

from caldav_assistant.api import Task
from caldav_assistant.internal.caldav import SyncEngine
from caldav_assistant.internal.cli import conversation_app, conversation_live
from caldav_assistant.internal.session import CalDAVSessionService
from caldav_assistant.internal.agenda.service import AgendaService


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


def test_unverified_startup_enters_console_without_live_session_probe(monkeypatch):
    snapshot = conversation_app.StartupSnapshot(
        current_work_verified=False,
        stale=True,
    )
    shown = []
    entered = []

    monkeypatch.setattr(conversation_app, "_show_welcome", lambda app: snapshot)
    monkeypatch.setattr(
        conversation_app.legacy,
        "_monitor_target",
        lambda app: pytest.fail("startup must not re-read live Session state"),
    )
    monkeypatch.setattr(
        conversation_app,
        "_console",
        lambda app, value: (entered.append(value) or (0, "exit")),
    )

    app = SimpleNamespace()
    assert conversation_app.run_conversation_repl(app) == 0
    assert entered == [snapshot]


def test_console_prompt_does_not_live_probe_unknown_current_work(monkeypatch):
    snapshot = conversation_app.StartupSnapshot(
        current_work_verified=False,
        stale=True,
    )
    monkeypatch.setattr(
        conversation_app.legacy,
        "_monitor_target",
        lambda app: pytest.fail("idle console must not re-read live Session state"),
    )

    class EOFIO:
        def read(self, prompt=""):
            assert prompt == "> "
            raise EOFError

        def write(self, text=""):
            return None

    app = SimpleNamespace(
        io=EOFIO(),
        ctx=SimpleNamespace(ui=SimpleNamespace(show=lambda value: None)),
    )
    code, action = conversation_app._console(app, snapshot)
    assert (code, action) == (0, "exit")


def test_interactive_exit_never_probes_live_current_work(monkeypatch):
    monkeypatch.setattr(
        conversation_live.legacy,
        "_monitor_target",
        lambda app: pytest.fail("exit must not probe live Session state"),
    )
    monkeypatch.setattr(
        conversation_live.base,
        "execute_command",
        lambda app, parsed: conversation_live.base.CommandOutcome(
            0,
            should_exit=True,
        ),
    )
    app = SimpleNamespace()
    parsed = conversation_live.base.ParsedCommand(
        raw="exit",
        name="exit",
        args=(),
    )

    assert conversation_live._execute_user(app, parsed) == (0, True)


def test_failed_current_work_refresh_stays_in_cli(monkeypatch):
    shown = []

    class UI:
        def choose(self, title, items, **kwargs):
            assert items[0] == "Refresh current work"
            return "Refresh current work"

        def show(self, value):
            shown.append(str(value))

    app = SimpleNamespace(ctx=SimpleNamespace(ui=UI()))
    snapshot = conversation_app.StartupSnapshot(
        current_work_verified=False,
        stale=True,
    )
    monkeypatch.setattr(
        conversation_app,
        "_visible_call",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("temporary read failure")
        ),
    )

    assert conversation_app._home_menu(app, snapshot) == "console"
    assert any("console remains usable" in line for line in shown)
    assert any("No Task was started" in line for line in shown)


def test_verified_open_work_uid_missing_from_task_snapshot_becomes_unknown():
    class Session:
        def startup_snapshot(self, tasks, *, work_facts=None):
            return {
                "current_task_id": "new-task-from-other-client",
                "current_task": None,
                "paused_task_ids": (),
                "current_work_verified": True,
                "verified_at": "2026-09-19T06:00:00+00:00",
            }

    class Engine:
        def build(self, tasks, events, **kwargs):
            return SimpleNamespace(items=())

        def candidates(self, tasks, events):
            return "candidates"

    class Next:
        def choose(self, agenda, **kwargs):
            pytest.fail("UNKNOWN current work must suppress recommendation")

    service = AgendaService(
        tasks=SimpleNamespace(),
        events=SimpleNamespace(),
        engine=Engine(),
        next_engine=Next(),
        state={},
        session=Session(),
    )
    visible_task = Task(id="older-task", summary="Older task")

    result = service._startup_result(
        [visible_task],
        [],
        days=1,
        kind="task",
        work_facts={
            "current_task_id": "new-task-from-other-client",
            "worked_task_ids": (),
            "current_work_verified": True,
        },
    )

    assert result["current_work_verified"] is False
    assert result["current_task"] is None
    assert result["recommendation"] is None
