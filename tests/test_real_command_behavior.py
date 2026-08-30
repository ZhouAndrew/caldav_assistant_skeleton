from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

from caldav_assistant.api import Task
from caldav_assistant.internal.cli.actions import BuiltinActions, register_cli_builtin_commands
from caldav_assistant.internal.cli.app import run_repl
from caldav_assistant.internal.cli.crud import register_crud_cli_commands
from caldav_assistant.internal.cli.io import StdConsoleIO
from caldav_assistant.internal.cli.navigation import register_navigation_cli_commands
from caldav_assistant.internal.commands import CommandRegistry, CommandService
from caldav_assistant.internal.prompts import Menu, PromptKit
from caldav_assistant.internal.settings.cli import SettingsActions


def _scripted_input(lines):
    values = iter(lines)

    def read(prompt=""):
        try:
            return next(values)
        except StopIteration as exc:
            raise EOFError from exc

    return read


def test_nested_menu_back_really_returns_one_level_instead_of_dropping_to_repl():
    stdout = StringIO()
    stderr = StringIO()
    io = StdConsoleIO(
        input_fn=_scripted_input(
            [
                "menu",
                "2",  # root -> Work
                "0",  # Work -> root (this used to terminate menu)
                "1",  # root -> Agenda; must NOT become unsupported command: 1
                "0",  # Agenda -> root
                "0",  # root -> normal REPL
            ]
        ),
        stdout=stdout,
        stderr=stderr,
    )
    prompts = PromptKit(io, Menu(io), temporal=SimpleNamespace())
    commands = CommandService(CommandRegistry())
    ctx = SimpleNamespace(ui=prompts, commands=commands, session=None)
    register_navigation_cli_commands(commands, ctx)
    app = SimpleNamespace(ctx=ctx, commands=commands, io=io, extensions=None)

    assert run_repl(app) == 0

    visible = stdout.getvalue()
    assert "Work" in visible
    assert "Agenda" in visible
    assert visible.count("CalDAV Assistant") >= 3
    assert "Unsupported command: 1" not in visible
    assert "Unsupported command: 0" not in visible
    assert stderr.getvalue() == ""


class _Tasks:
    def __init__(self):
        self.items = [
            Task(id="t1", summary="First task"),
            Task(id="t2", summary="Second task"),
        ]
        self.completed = []

    def list(self):
        return list(self.items)

    def find(self, query):
        return next(item for item in self.items if item.summary == query)

    def complete(self, task):
        self.completed.append(task)
        return f"completed {task.summary}"


class _Events:
    def list(self):
        return []


def test_number_printed_by_tasks_is_a_real_reference_for_done():
    stdout = StringIO()
    io = StdConsoleIO(
        input_fn=_scripted_input(["tasks", "done 2"]),
        stdout=stdout,
        stderr=StringIO(),
    )
    prompts = PromptKit(io, Menu(io), temporal=SimpleNamespace())
    commands = CommandService(CommandRegistry())
    tasks = _Tasks()
    session = SimpleNamespace(last_items=[], current_selection=None)
    ctx = SimpleNamespace(
        ui=prompts,
        commands=commands,
        tasks=tasks,
        events=_Events(),
        session=session,
    )
    register_cli_builtin_commands(commands, ctx)
    register_crud_cli_commands(commands, ctx)
    app = SimpleNamespace(ctx=ctx, commands=commands, io=io, extensions=None)

    assert run_repl(app) == 0

    assert tasks.completed == [tasks.items[1]]
    assert session.last_items == tasks.items
    visible = stdout.getvalue()
    assert "2. Second task" in visible
    assert "Numbers are active references" in visible
    assert "Complete → Second task" in visible


class _SettingsUI:
    def __init__(self):
        self.choices = iter(
            [
                "Extensions",
                "Show extensions",
                None,  # back from Extensions panel
                None,  # back from Settings
            ]
        )
        self.shown = []

    def choose(self, title, items, **kwargs):
        return next(self.choices)

    def show(self, value):
        self.shown.append(str(value))

    def ask_text(self, prompt, **kwargs):
        return None


class _SettingsStore:
    def get(self, key, default=None):
        return default


def test_settings_extensions_panel_executes_real_extension_command():
    commands = CommandService(CommandRegistry())
    calls = []
    commands.register_builtin(
        "extensions",
        lambda: calls.append(("extensions",)) or "REAL EXTENSION MANAGER LIST",
    )
    ui = _SettingsUI()
    ctx = SimpleNamespace(ui=ui, commands=commands, settings=_SettingsStore())

    assert SettingsActions(ctx).interactive() is None

    assert calls == [("extensions",)]
    assert "REAL EXTENSION MANAGER LIST" in ui.shown
    assert not any("Use `extensions`" in line for line in ui.shown)


def test_help_explains_runtime_effects_and_verification_not_only_description():
    commands = CommandService(CommandRegistry())
    ctx = SimpleNamespace(commands=commands)
    register_cli_builtin_commands(commands, ctx)

    text = commands.run("help", "today")

    assert "Purpose:" in text
    assert "Runtime:" in text
    assert "Effects:" in text
    assert "Verify:" in text
    assert "AgendaService/Engine" in text
    assert "CalDAV" in text


def test_log_exposes_outbox_delivery_steps_and_how_to_check_them():
    shown = []
    calls = []
    ctx = SimpleNamespace(
        ui=SimpleNamespace(show=lambda value: shown.append(str(value))),
        wordpress=SimpleNamespace(
            log=lambda text: calls.append(text) or "UPLOADED"
        ),
    )

    assert BuiltinActions(ctx).log("code") == "UPLOADED"

    assert calls == ["code"]
    text = "\n".join(shown)
    assert "durable WordPress Outbox" in text
    assert "immediate WordPress upload" in text
    assert "history wordpress" in text
    assert "history pending" in text
