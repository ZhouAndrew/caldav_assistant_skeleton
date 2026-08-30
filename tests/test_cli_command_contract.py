from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from caldav_assistant.api import Agenda, AgendaItem, Event, Task
from caldav_assistant.api.v1.errors import ValidationError
from caldav_assistant.internal.cli.actions import EXIT_REPL, register_cli_builtin_commands
from caldav_assistant.internal.cli.app import run_repl
from caldav_assistant.internal.commands import CommandRegistry, CommandService
from caldav_assistant.internal.extensions.cli import (
    ExtensionActions,
    register_extension_cli_commands,
)
from caldav_assistant.internal.runtime.cli import register_background_cli_command
from caldav_assistant.internal.runtime.proxies import RemoteSessionAPI
from caldav_assistant.internal.settings.cli import register_settings_cli_command
from caldav_assistant.internal.undo.cli import register_undo_cli_command


class FakeIO:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.out = []
        self.err = []

    def read(self, prompt=""):
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)

    def write(self, value="", end="\n"):
        self.out.append(str(value))

    def error(self, value):
        self.err.append(str(value))


class FakeUI:
    def __init__(self, io=None):
        self.io = io
        self.shown = []

    def show(self, value):
        text = str(value)
        self.shown.append(text)
        if self.io is not None:
            self.io.write(text)


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def call(self, route, **payload):
        self.calls.append((route, payload))
        return f"called:{route}"

    def status(self):
        return {"status": "stopped"}

    def ensure_running(self):
        return {"status": "running", "pid": 42, "maintenance_alive": True}

    def stop(self):
        return True

    def restart(self):
        return {"status": "running", "pid": 43, "maintenance_alive": True}


class FakeAutostart:
    def __init__(self):
        self.enabled = False

    def is_enabled(self):
        return self.enabled

    def enable(self):
        self.enabled = True

    def disable(self, *, stop=True):
        self.enabled = False


class FakeExtensionManager:
    manager_error = None

    def __init__(self):
        self.calls = []
        self.records = []

    @staticmethod
    def _record(name="demo", status="loaded", enabled=True, error=None):
        return SimpleNamespace(
            name=name,
            status=status,
            enabled=enabled,
            error=error,
        )

    def list(self):
        return list(self.records)

    def add(self, path):
        self.calls.append(("add", path))
        return self._record(path.stem, "disabled", False)

    def load(self, name):
        self.calls.append(("load", name))
        return self._record(name)

    def enable(self, name):
        self.calls.append(("enable", name))
        return self._record(name)

    def disable(self, name):
        self.calls.append(("disable", name))
        return self._record(name, "disabled", False)

    def reload(self, name):
        self.calls.append(("reload", name))
        return self._record(name)

    def unload(self, name):
        self.calls.append(("unload", name))
        return self._record(name, "unloaded", False)

    def errors(self):
        return []

    def hook_failures(self):
        return []


class FakeSettings:
    def get(self, key, default=None):
        return default

    def list(self, category=None):
        return []


class ProxyRuntime:
    def call(self, route, **payload):
        return None


def _repl_app(*answers):
    io = FakeIO(*answers)
    commands = CommandService(CommandRegistry())
    session = SimpleNamespace(last_items=[], current_selection=None)
    ctx = SimpleNamespace(ui=FakeUI(io), commands=commands, session=session)
    app = SimpleNamespace(
        io=io,
        ctx=ctx,
        commands=commands,
        extensions=None,
        runtime=None,
    )
    return app, commands, session, io


def test_numbered_task_reference_uses_last_visible_agenda_even_from_pager():
    app, commands, session, _ = _repl_app("today", "start 1", "exit")
    tasks = [Task(id=str(index), summary=f"Task {index}") for index in range(1, 13)]
    agenda = Agenda(items=[AgendaItem(value=task, kind="task") for task in tasks])
    seen = []

    commands.register_builtin("today", lambda: agenda)
    commands.register_builtin("start", lambda *parts: seen.append(parts) or "started")
    commands.register_builtin("exit", lambda: EXIT_REPL)

    assert run_repl(app) == 0
    assert seen == [(tasks[0],)]
    assert session.last_items == tasks
    assert session.current_selection is tasks[0]


def test_numbered_task_reference_rejects_event_and_out_of_range_selection():
    task = Task(id="t1", summary="Task")
    event = Event(id="e1", summary="Class")

    app, commands, _, io = _repl_app("today", "start 2", "start 9", "exit")
    agenda = Agenda(
        items=[
            AgendaItem(value=task, kind="task"),
            AgendaItem(value=event, kind="event"),
        ]
    )
    seen = []
    commands.register_builtin("today", lambda: agenda)
    commands.register_builtin("start", lambda *parts: seen.append(parts) or "started")
    commands.register_builtin("exit", lambda: EXIT_REPL)

    assert run_repl(app) == 0
    assert seen == []
    assert any("not a task" in message for message in io.err)
    assert any("out of range" in message for message in io.err)


def test_next_result_populates_frozen_session_selection_context():
    app, commands, session, _ = _repl_app("next", "exit")
    task = Task(id="t1", summary="Report")
    commands.register_builtin("next", lambda: AgendaItem(value=task, kind="task"))
    commands.register_builtin("exit", lambda: EXIT_REPL)

    assert run_repl(app) == 0
    assert session.last_items == [task]
    assert session.current_selection is task


def test_remote_session_proxy_exposes_local_last_items_and_current_selection():
    session = RemoteSessionAPI(ProxyRuntime())
    assert session.last_items == []
    assert session.current_selection is None


def _fully_registered_commands():
    commands = CommandService(CommandRegistry())
    runtime = FakeRuntime()
    extensions = FakeExtensionManager()
    ctx = SimpleNamespace(
        commands=commands,
        ui=FakeUI(),
        session=SimpleNamespace(last_items=[], current_selection=None),
        settings=FakeSettings(),
        tasks=SimpleNamespace(),
        agenda=SimpleNamespace(),
        wordpress=SimpleNamespace(),
        time=SimpleNamespace(),
    )
    register_cli_builtin_commands(commands, ctx)
    register_settings_cli_command(commands, ctx)
    register_background_cli_command(
        commands,
        runtime,
        autostart=FakeAutostart(),
        ui=ctx.ui,
    )
    register_undo_cli_command(commands, runtime)
    register_extension_cli_commands(commands, extensions)
    return commands, runtime, extensions


def test_every_user_visible_top_level_command_is_registered_protected_and_documented():
    commands, _, _ = _fully_registered_commands()
    visible = {
        "today",
        "next",
        "current",
        "edit",
        "done",
        "start",
        "pause",
        "resume",
        "log",
        "help",
        "exit",
        "settings",
        "background",
        "undo",
        "extensions",
        "extension",
    }
    canonical = set(commands.names())

    assert canonical == visible | {"edit-due"}
    assert all(commands.resolve(name).protected for name in canonical)

    help_text = commands.run("help")
    assert "Help · Action Library" in help_text
    assert "start —" not in help_text

    all_help = commands.run("help", "all")
    for name in visible:
        assert f"  {name}" in all_help
        detail = commands.run("help", name)
        assert commands.resolve(name).description in detail
        assert "source:" in detail
    assert "edit-due" not in help_text
    assert "edit-due" not in all_help

    assert commands.resolve("now").name == "current"
    assert commands.resolve("complete").name == "done"
    assert commands.resolve("?").name == "help"
    assert commands.resolve("quit").name == "exit"
    assert commands.resolve("q").name == "exit"


def test_management_commands_have_user_facing_usage_and_undo_route():
    commands, runtime, _ = _fully_registered_commands()

    settings_help = commands.run("settings", "help")
    assert "settings categories" in settings_help
    assert "settings caldav status|test|collections|roles" in settings_help
    assert "settings caldav credentials" in settings_help

    background_help = commands.run("background", "help")
    for action in ("status", "start", "stop", "restart", "enable", "disable"):
        assert f"background {action}" in background_help

    assert "Usage: extension" in commands.run("extension")
    assert "No extensions found" in commands.run("extensions")

    assert commands.run("undo") == "called:undo.last"
    assert runtime.calls[-1] == ("undo.last", {})
    with pytest.raises(ValidationError, match="does not take arguments"):
        commands.run("undo", "extra")


def test_extension_management_dispatches_every_supported_lifecycle_action():
    manager = FakeExtensionManager()
    actions = ExtensionActions(manager)

    assert "Added demo" in actions.extension("add", "demo.py")
    assert manager.calls[-1] == ("add", Path("demo.py"))

    for verb in ("load", "enable", "disable", "reload", "unload"):
        text = actions.extension(verb, "demo")
        assert text.startswith("demo:")
        assert manager.calls[-1] == (verb, "demo")

    assert actions.extension("errors") == "No extension errors."
    with pytest.raises(ValidationError, match="Unknown extension action"):
        actions.extension("explode")
    with pytest.raises(ValidationError, match="requires one extension name"):
        actions.extension("enable")
