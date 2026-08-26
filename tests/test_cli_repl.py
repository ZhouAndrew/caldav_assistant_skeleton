from __future__ import annotations

from types import SimpleNamespace

from caldav_assistant.internal.cli.app import (
    parse_command_line,
    run_cli,
    run_one_shot,
    run_repl,
)
from caldav_assistant.internal.commands import CommandRegistry, CommandService


class FakeIO:
    def __init__(self, lines=()):
        self.lines = iter(lines)
        self.out = []
        self.err = []

    def read(self, prompt=""):
        try:
            return next(self.lines)
        except StopIteration:
            raise EOFError

    def write(self, value=""):
        self.out.append(value)

    def error(self, value):
        self.err.append(value)


class FakeUI:
    def __init__(self, io):
        self.io = io
        self.shown = []

    def show(self, value):
        self.shown.append(value)
        self.io.write(value)


def make_app(lines=()):
    io = FakeIO(lines)
    ui = FakeUI(io)
    registry = CommandRegistry()
    commands = CommandService(registry)
    ctx = SimpleNamespace(ui=ui, commands=commands)
    return SimpleNamespace(
        io=io,
        ctx=ctx,
        commands=commands,
        extensions=None,
        runtime=None,
    )


def test_repl_parser_preserves_quoted_arguments():
    parsed = parse_command_line('log "finished report" now')
    assert parsed.name == "log"
    assert parsed.args == ("finished report", "now")


def test_one_shot_and_repl_both_end_at_command_service_run():
    one = make_app()
    calls = []
    one.commands.register_builtin(
        "echo",
        lambda *args: calls.append(args) or " ".join(args),
    )

    assert run_one_shot(one, ["echo", "a", "b"]) == 0
    assert calls == [("a", "b")]
    assert one.io.out[-1] == "a b"

    repl = make_app(["echo x y", "exit"])
    repl_calls = []
    repl.commands.register_builtin(
        "echo",
        lambda *args: repl_calls.append(args) or " ".join(args),
    )
    repl.commands.register_builtin("exit", lambda: __import__(
        "caldav_assistant.internal.cli.actions",
        fromlist=["EXIT_REPL"],
    ).EXIT_REPL)

    assert run_repl(repl) == 0
    assert repl_calls == [("x", "y")]


def test_unknown_and_bad_syntax_do_not_kill_repl():
    app = make_app(['log "unterminated', "missing", "ok", "exit"])
    app.commands.register_builtin("ok", lambda: "worked")
    from caldav_assistant.internal.cli.actions import EXIT_REPL
    app.commands.register_builtin("exit", lambda: EXIT_REPL)

    code = run_repl(app)

    assert code == 0
    assert any("Invalid input" in str(item) for item in app.io.err)
    assert any("Unknown command" in str(item) for item in app.io.err)
    assert "worked" in app.io.out


def test_alias_resolution_is_transparently_shown():
    app = make_app()
    app.commands.register_builtin("exit", lambda: None, aliases=("q",))

    code = run_one_shot(app, ["q"])

    assert code == 0
    assert "Command → exit" in app.io.out


def test_run_cli_uses_one_shot_when_argv_present_and_repl_when_empty(monkeypatch):
    one = make_app()
    one.commands.register_builtin("today", lambda: "agenda")
    monkeypatch.setattr(
        "caldav_assistant.internal.cli.app.register_cli_builtin_commands",
        lambda commands, ctx: None,
    )
    assert run_cli(["today"], app=one) == 0
    assert one.io.out[-1] == "agenda"

    repl = make_app(["exit"])
    from caldav_assistant.internal.cli.actions import EXIT_REPL
    repl.commands.register_builtin("exit", lambda: EXIT_REPL)
    assert run_cli([], app=repl) == 0
