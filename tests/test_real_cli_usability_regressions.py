from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

import pytest

from caldav_assistant.internal.cli.app import run_repl
from caldav_assistant.internal.cli.io import StdConsoleIO
from caldav_assistant.internal.cli.navigation import register_navigation_cli_commands
from caldav_assistant.internal.commands import CommandRegistry, CommandService
from caldav_assistant.internal.prompts import Menu, PromptKit
from caldav_assistant.internal.runtime.proxies import RemoteWordPressAPI


class StaleRuntime:
    def __init__(self, *, always_stale: bool = False):
        self.calls = []
        self.restarts = 0
        self.always_stale = always_stale

    def call(self, method, **payload):
        self.calls.append((method, payload))
        if self.always_stale or len(self.calls) == 1:
            raise RuntimeError(
                f"ValueError: IPC method is not allowed: {method}"
            )
        return {
            "id": 13554,
            "title": "August 30  Sunday  2026",
            "content": "real WordPress content",
        }

    def restart(self):
        self.restarts += 1
        return {"status": "running"}


def test_new_cli_route_recovers_from_already_running_old_background_service():
    runtime = StaleRuntime()
    wordpress = RemoteWordPressAPI(runtime)

    result = wordpress._daily_log()

    assert result["id"] == 13554
    assert result["content"] == "real WordPress content"
    assert runtime.restarts == 1
    assert runtime.calls == [
        ("wordpress.daily_log", {}),
        ("wordpress.daily_log", {}),
    ]


def test_current_code_route_failure_is_not_hidden_in_an_infinite_restart_loop():
    runtime = StaleRuntime(always_stale=True)
    wordpress = RemoteWordPressAPI(runtime)

    with pytest.raises(RuntimeError, match="IPC method is not allowed"):
        wordpress._daily_log()

    assert runtime.restarts == 1
    assert len(runtime.calls) == 2


def _scripted_input(lines):
    values = iter(lines)

    def read(prompt=""):
        try:
            return next(values)
        except StopIteration as exc:
            raise EOFError from exc

    return read


def test_direct_command_typed_inside_nested_menu_returns_to_normal_repl_execution():
    stdout = StringIO()
    stderr = StringIO()
    io = StdConsoleIO(
        input_fn=_scripted_input(
            [
                "menu",
                "3",  # Logs submenu
                "log CalDAV Assistant real log test",
            ]
        ),
        stdout=stdout,
        stderr=stderr,
    )
    prompts = PromptKit(io, Menu(io), temporal=SimpleNamespace())
    commands = CommandService(CommandRegistry())
    ctx = SimpleNamespace(ui=prompts, commands=commands, session=None)
    calls = []

    commands.register_builtin(
        "log",
        lambda *parts: calls.append(parts) or "LOG COMMAND RAN THROUGH NORMAL REPL",
    )
    register_navigation_cli_commands(commands, ctx)
    app = SimpleNamespace(
        ctx=ctx,
        commands=commands,
        io=io,
        extensions=None,
    )

    code = run_repl(app)

    assert code == 0
    assert calls == [("CalDAV", "Assistant", "real", "log", "test")]
    visible = stdout.getvalue()
    assert "CalDAV Assistant" in visible
    assert "Logs" in visible
    assert "Tip: type any normal CLI command here" in visible
    assert "LOG COMMAND RAN THROUGH NORMAL REPL" in visible
    assert "Invalid choice" not in visible
    assert stderr.getvalue() == ""


def test_invalid_numeric_menu_choice_is_recoverable_but_not_misread_as_a_command():
    stdout = StringIO()
    io = StdConsoleIO(
        input_fn=_scripted_input(["9", "0"]),
        stdout=stdout,
        stderr=StringIO(),
    )
    prompts = PromptKit(io, Menu(io), temporal=SimpleNamespace())
    commands = CommandService(CommandRegistry())
    ctx = SimpleNamespace(ui=prompts, commands=commands)
    actions = register_navigation_cli_commands(commands, ctx)

    assert actions.menu() is None
    assert "Choose 1-5, 0 to go back, or type a normal CLI command." in stdout.getvalue()
