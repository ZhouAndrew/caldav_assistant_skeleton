from __future__ import annotations

from types import SimpleNamespace

from caldav_assistant.api.v1.errors import NotFoundError
from caldav_assistant.internal.cli.app import run_one_shot
from caldav_assistant.internal.commands import CommandRegistry, CommandService


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


class DisabledDeveloperTools:
    def get(self, name):
        assert name == "developer_tools"
        return SimpleNamespace(enabled=False, status="disabled")


def test_help_uses_the_same_supported_but_disabled_classification():
    io = FakeIO()
    ui = FakeUI(io)
    commands = CommandService(CommandRegistry())
    commands.register_builtin("help", lambda name: (_ for _ in ()).throw(NotFoundError(name)))
    ctx = SimpleNamespace(ui=ui, commands=commands)
    app = SimpleNamespace(
        io=io,
        ctx=ctx,
        commands=commands,
        extensions=DisabledDeveloperTools(),
        runtime=None,
    )

    code = run_one_shot(app, ["help", "run"])

    assert code == 2
    message = str(io.err[-1])
    assert "Command 'run' is supported" in message
    assert "developer_tools" in message
    assert "extension enable developer_tools" in message
    assert "NotFoundError" not in message
