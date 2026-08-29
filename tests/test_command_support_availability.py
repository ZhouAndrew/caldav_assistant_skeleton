from __future__ import annotations

from types import SimpleNamespace

from caldav_assistant.internal.cli.app import run_one_shot
from caldav_assistant.internal.commands import CommandRegistry, CommandService
from caldav_assistant.internal.extensions.availability import find_extension_command_support


class FakeIO:
    def __init__(self):
        self.out = []
        self.err = []

    def write(self, value=""):
        self.out.append(value)

    def error(self, value):
        self.err.append(value)


class FakeUI:
    def __init__(self, io):
        self.io = io

    def show(self, value):
        self.io.write(value)


class FakeExtensions:
    def __init__(self, *, enabled=False, status="disabled"):
        self.record = SimpleNamespace(enabled=enabled, status=status)

    def get(self, name):
        assert name == "developer_tools"
        return self.record


def make_app(extensions=None):
    io = FakeIO()
    ui = FakeUI(io)
    commands = CommandService(CommandRegistry())
    ctx = SimpleNamespace(ui=ui, commands=commands)
    return SimpleNamespace(
        io=io,
        ctx=ctx,
        commands=commands,
        extensions=extensions,
        runtime=None,
    )


def test_catalog_knows_run_is_supported_by_developer_tools_when_disabled():
    support = find_extension_command_support(FakeExtensions(), "run")

    assert support is not None
    assert support.command == "run"
    assert support.extension == "developer_tools"
    assert support.enabled is False
    assert support.status == "disabled"


def test_disabled_supported_command_is_not_reported_as_unknown_or_unsupported():
    app = make_app(FakeExtensions(enabled=False, status="disabled"))

    code = run_one_shot(app, ["run", "echo", "hello"])

    assert code == 2
    message = str(app.io.err[-1])
    assert "is supported" in message
    assert "developer_tools" in message
    assert "extension enable developer_tools" in message
    assert "Unsupported command" not in message


def test_extension_error_is_distinguished_from_disabled_state():
    app = make_app(FakeExtensions(enabled=True, status="error"))

    code = run_one_shot(app, ["run", "echo", "hello"])

    assert code == 2
    message = str(app.io.err[-1])
    assert "is supported" in message
    assert "failed to load" in message
    assert "extension errors developer_tools" in message


def test_genuinely_unknown_command_is_explicitly_unsupported():
    app = make_app(FakeExtensions())

    code = run_one_shot(app, ["this-command-does-not-exist"])

    assert code == 2
    assert "Unsupported command" in str(app.io.err[-1])
