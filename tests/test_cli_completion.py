from __future__ import annotations

from types import SimpleNamespace

from caldav_assistant.internal.cli.completion import (
    CompletionEngine,
    ReadlineCompletionSession,
)
from caldav_assistant.internal.commands import CommandRegistry, CommandService


class FakeExtensions:
    def list(self):
        return [
            SimpleNamespace(name="demo"),
            SimpleNamespace(name="school-tools"),
        ]


def make_app():
    commands = CommandService(CommandRegistry())
    commands.register_builtin("today", lambda: None, aliases=("td",))
    commands.register_builtin("help", lambda *args: None, aliases=("?",))
    commands.register_builtin("api", lambda *args: None)
    commands.register_builtin("extension", lambda *args: None)
    commands.register_builtin("background", lambda *args: None)
    commands.register_extension("urgent", lambda: None, extension="demo")
    return SimpleNamespace(
        commands=commands,
        extensions=FakeExtensions(),
        io=SimpleNamespace(_input_fn=None),
    )


def test_root_completion_uses_live_registry_including_aliases_and_extensions():
    engine = CompletionEngine(make_app())

    assert engine.complete("to") == ("today",)
    assert engine.complete("td") == ("td",)
    assert engine.complete("ur") == ("urgent",)
    assert "help" in engine.complete("")


def test_api_completion_uses_real_public_catalog_and_layers():
    engine = CompletionEngine(make_app())

    assert "easy.complete" in engine.complete("api easy.comp")
    assert "ctx.tasks.complete" in engine.complete("api ctx.tasks.comp")
    assert engine.complete("api list o") == ("object",)
    assert "Task.start_task" in engine.complete("api exists Task.start")
    assert engine.complete("api search rem") == ()


def test_extension_and_background_subcommands_complete_without_service_io():
    engine = CompletionEngine(make_app())

    assert engine.complete("extension en") == ("enable",)
    assert engine.complete("extension enable d") == ("demo",)
    assert engine.complete("extension reload school") == ("school-tools",)
    assert engine.complete("background res") == ("restart",)


def test_help_argument_completion_reuses_command_registry():
    engine = CompletionEngine(make_app())

    assert engine.complete("help ur") == ("urgent",)
    assert engine.complete("? to") == ("today",)


class FakeReadline:
    def __init__(self):
        self.completer = "old"
        self.delims = " old-delims "
        self.buffer = "api easy.comp"
        self.end = len(self.buffer)
        self.bindings = []

    def get_completer(self):
        return self.completer

    def set_completer(self, value):
        self.completer = value

    def get_completer_delims(self):
        return self.delims

    def set_completer_delims(self, value):
        self.delims = value

    def parse_and_bind(self, value):
        self.bindings.append(value)

    def get_line_buffer(self):
        return self.buffer

    def get_endidx(self):
        return self.end


def test_readline_session_installs_completer_and_restores_previous_state():
    readline = FakeReadline()
    session = ReadlineCompletionSession(
        make_app(),
        readline_module=readline,
        force=True,
    )

    assert session.install() is True
    assert callable(readline.completer)
    assert readline.delims == " \t\n"
    assert readline.completer("easy.comp", 0) == "easy.complete"
    assert readline.completer("easy.comp", 1) is None

    session.restore()
    assert readline.completer == "old"
    assert readline.delims == " old-delims "
