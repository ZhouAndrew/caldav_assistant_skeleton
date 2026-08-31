from __future__ import annotations

from types import SimpleNamespace

from caldav_assistant.api.v1.errors import UnavailableError
from caldav_assistant.internal.cli.feature_demo import (
    register_feature_demo_command,
    run_feature_demo,
)
from caldav_assistant.internal.commands import CommandRegistry, CommandService


class FakeUI:
    def __init__(self):
        self.shown: list[str] = []

    def show(self, value=""):
        self.shown.append(str(value))


class FakeSettings:
    def __init__(self, *, configured=True, ipc_error: Exception | None = None):
        self.configured = configured
        self.ipc_error = ipc_error
        self.connection_calls = 0

    def list(self):
        if self.ipc_error is not None:
            raise self.ipc_error
        return ["ui.locale", "caldav.base_url"]

    def caldav_status(self):
        return {
            "base_url_configured": self.configured,
            "credentials_configured": True if self.configured else False,
            "base_url_source": "saved" if self.configured else None,
        }

    def test_caldav_connection(self):
        self.connection_calls += 1
        return {"ok": True, "collection_count": 3}


class ReadAPI:
    def __init__(self, values=()):
        self.values = values
        self.calls = 0

    def list(self):
        self.calls += 1
        return self.values


class AgendaAPI:
    def __init__(self, *, task=None, error: Exception | None = None):
        self.task = task
        self.error = error
        self.today_calls = 0
        self.next_calls = 0

    def today(self):
        self.today_calls += 1
        if self.error is not None:
            raise self.error
        return SimpleNamespace(items=(self.task,) if self.task is not None else ())

    def next(self):
        self.next_calls += 1
        return self.task


class SessionAPI:
    def __init__(self, current=None):
        self.current = current
        self.calls = 0

    def current_task(self):
        self.calls += 1
        return self.current


class ActivityAPI:
    def __init__(self):
        self.calls = 0

    def today(self):
        self.calls += 1
        return [SimpleNamespace(action="task_started")]


class WordPressAPI:
    def __init__(self):
        self.calls = 0

    def pending(self):
        self.calls += 1
        return []


class NeverRead:
    def __init__(self):
        self.calls = 0

    def list(self):
        self.calls += 1
        raise AssertionError("CalDAV-dependent read should have been skipped")


class NeverAgenda:
    def __init__(self):
        self.today_calls = 0
        self.next_calls = 0

    def today(self):
        self.today_calls += 1
        raise AssertionError("Agenda should have been skipped")

    def next(self):
        self.next_calls += 1
        raise AssertionError("Next should have been skipped")


def _context(*, configured=True, ipc_error=None, agenda_error=None):
    ui = FakeUI()
    commands = CommandService(CommandRegistry())
    task = SimpleNamespace(id="t1", summary="Demo task")
    settings = FakeSettings(configured=configured, ipc_error=ipc_error)
    ctx = SimpleNamespace(
        ui=ui,
        commands=commands,
        settings=settings,
        tasks=ReadAPI([task]),
        events=ReadAPI([SimpleNamespace(id="e1", summary="Demo event")]),
        agenda=AgendaAPI(task=task, error=agenda_error),
        session=SessionAPI(),
        activity=ActivityAPI(),
        wordpress=WordPressAPI(),
    )
    register_feature_demo_command(commands, ctx)
    return ctx


def test_live_demo_uses_read_only_real_namespaces_and_reports_clean_baseline():
    ctx = _context()

    result = run_feature_demo(ctx)

    assert "Live diagnosis result: PASS" in result
    assert "Safety: read-only; no Task/Event/WordPress data was changed." in result
    assert ctx.tasks.calls == 1
    assert ctx.events.calls == 1
    assert ctx.agenda.today_calls == 1
    assert ctx.agenda.next_calls == 1
    assert ctx.session.calls == 1
    assert ctx.activity.calls == 1
    assert ctx.wordpress.calls == 1
    assert ctx.settings.connection_calls == 1
    transcript = "\n".join(ctx.ui.shown)
    for stage in (
        "Command registry",
        "Background / local IPC",
        "CalDAV status",
        "Task read",
        "Event read",
        "Agenda today",
        "Next recommendation",
        "Current work / Session",
        "Activity Journal read",
        "WordPress Outbox read",
        "CalDAV authenticated connection",
    ):
        assert stage in transcript


def test_live_demo_stops_after_ipc_failure_instead_of_repeating_long_timeouts():
    ctx = _context(ipc_error=UnavailableError("runtime timed out"))
    ctx.tasks = NeverRead()
    ctx.events = NeverRead()
    ctx.agenda = NeverAgenda()

    result = run_feature_demo(ctx)

    assert "Live diagnosis result: ISSUE FOUND" in result
    assert "fault begins at Background Service / local IPC" in result
    assert "caldav-assistant background status" in result
    assert ctx.tasks.calls == 0
    assert ctx.events.calls == 0
    assert ctx.agenda.today_calls == 0
    assert ctx.agenda.next_calls == 0
    assert ctx.settings.connection_calls == 0
    transcript = "\n".join(ctx.ui.shown)
    assert "Background / local IPC — FAIL" in transcript
    assert "Task read — SKIP — Background / IPC is unavailable" in transcript


def test_live_demo_treats_unconfigured_caldav_as_setup_state_not_empty_data():
    ctx = _context(configured=False)
    ctx.tasks = NeverRead()
    ctx.events = NeverRead()
    ctx.agenda = NeverAgenda()

    result = run_feature_demo(ctx)

    assert "Live diagnosis result: SETUP NEEDED" in result
    assert "CalDAV is not configured yet" in result
    assert "Settings & setup" in result
    assert ctx.tasks.calls == 0
    assert ctx.events.calls == 0
    assert ctx.agenda.today_calls == 0
    assert ctx.agenda.next_calls == 0
    assert ctx.settings.connection_calls == 0
    # Local Assistant record paths are still useful and safe to inspect.
    assert ctx.session.calls == 1
    assert ctx.activity.calls == 1
    assert ctx.wordpress.calls == 1


def test_live_demo_localises_agenda_failure_above_successful_raw_reads():
    ctx = _context(agenda_error=RuntimeError("agenda composition exploded"))

    result = run_feature_demo(ctx)

    assert "Live diagnosis result: ISSUE FOUND" in result
    assert "Raw Task/Event reads are healthy" in result
    assert "problem is above basic CalDAV reads" in result
    assert "caldav-assistant today ; caldav-assistant next" in result


def test_demo_registration_is_protected_and_has_human_aliases():
    ctx = _context()

    entry = ctx.commands.resolve("demo")
    assert entry.protected is True
    assert entry.metadata.get("help_category") == "system"
    assert ctx.commands.resolve("doctor").name == "demo"
    assert ctx.commands.resolve("diagnose").name == "demo"
