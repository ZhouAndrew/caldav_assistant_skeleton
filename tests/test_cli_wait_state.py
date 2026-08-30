from __future__ import annotations

from types import SimpleNamespace

from caldav_assistant.api import Task
from caldav_assistant.internal.cli.actions import EXIT_REPL
from caldav_assistant.internal.cli.app import run_repl
from caldav_assistant.internal.cli.wait_state import (
    WaitState,
    current_wait_state,
    message_for,
    prompt_for,
)
from caldav_assistant.internal.commands import CommandRegistry, CommandService


class FakeIO:
    def __init__(self, lines=()):
        self.lines = iter(lines)
        self.out = []
        self.err = []
        self.prompts = []

    def read(self, prompt=""):
        self.prompts.append(prompt)
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

    def show(self, value):
        self.io.write(value)


class FakeSession:
    def __init__(self):
        self.current = None
        self.last_items = []
        self.current_selection = None

    def current_task(self):
        return self.current


def make_app(lines=()):
    io = FakeIO(lines)
    ui = FakeUI(io)
    session = FakeSession()
    registry = CommandRegistry()
    commands = CommandService(registry)
    ctx = SimpleNamespace(ui=ui, commands=commands, session=session)
    app = SimpleNamespace(
        io=io,
        ctx=ctx,
        commands=commands,
        extensions=None,
        runtime=None,
    )
    return app, session


def test_wait_state_has_only_command_or_current_task_modes():
    ctx = SimpleNamespace(session=FakeSession())

    idle = current_wait_state(ctx)
    assert idle == WaitState("command")
    assert prompt_for(idle) == "> "
    assert "waiting for a command" in message_for(idle)

    ctx.session.current = Task(id="anki", summary="Anki", status="IN-PROCESS")
    working = current_wait_state(ctx)
    assert working == WaitState("task", task_id="anki", summary="Anki")
    assert prompt_for(working) == "[doing: Anki] > "
    assert "waiting for you to finish" in message_for(working)


def test_repl_follows_session_transition_without_owning_duplicate_state():
    app, session = make_app(["start", "done", "exit"])
    task = Task(id="anki", summary="Anki", status="NEEDS-ACTION")

    def start():
        task.status = "IN-PROCESS"
        session.current = task
        return "started"

    def done():
        task.status = "COMPLETED"
        task.completed = True
        session.current = None
        return "completed"

    app.commands.register_builtin("start", start)
    app.commands.register_builtin("done", done)
    app.commands.register_builtin("exit", lambda: EXIT_REPL)

    assert run_repl(app) == 0

    assert app.io.prompts == [
        "> ",
        "[doing: Anki] > ",
        "> ",
    ]
    output = "\n".join(str(item) for item in app.io.out)
    assert "Ready. The Assistant is waiting for a command." in output
    assert "Working: Anki." in output
    # Returning to command mode is announced after completion rather than hidden.
    assert output.count("Ready. The Assistant is waiting for a command.") == 2


def test_wait_state_presentation_failure_cannot_break_the_repl():
    class BrokenSession:
        def current_task(self):
            raise RuntimeError("temporary read failure")

    state = current_wait_state(SimpleNamespace(session=BrokenSession()))
    assert state == WaitState("command")
