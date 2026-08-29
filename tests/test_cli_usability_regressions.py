from __future__ import annotations

from types import SimpleNamespace

import pytest

from caldav_assistant.api import Agenda, AgendaItem, Task
from caldav_assistant.api.v1.errors import ValidationError
from caldav_assistant.internal.cli.app import run_repl
from caldav_assistant.internal.commands import CommandRegistry, CommandService
from caldav_assistant.internal.prompts import Menu
from caldav_assistant.internal.worklog import WorkLogService


class NoCallAdapter:
    def list_events(self, **filters):
        raise AssertionError("unconfigured work-history reads must not touch CalDAV")


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
    def __init__(self, io):
        self.io = io

    def show(self, value):
        self.io.write(value)


def test_unconfigured_work_history_does_not_block_read_context():
    worklog = WorkLogService(NoCallAdapter(), lambda: None)

    assert worklog.current_task_id() is None
    assert worklog.open_events() == []

    with pytest.raises(ValidationError, match="Work history calendar is not configured"):
        worklog.start_segment(Task(id="t1", summary="Task"))


def test_menu_accepts_exact_human_label_without_requiring_number():
    io = FakeIO("CalDAV")
    menu = Menu(io)

    assert menu.choose("Settings", ["Language", "CalDAV", "WordPress"]) == "CalDAV"


def test_command_typed_at_agenda_pager_is_replayed_by_repl():
    io = FakeIO("today", "start 1", "exit")
    commands = CommandService(CommandRegistry())
    ctx = SimpleNamespace(ui=FakeUI(io), commands=commands)
    app = SimpleNamespace(io=io, ctx=ctx, commands=commands, extensions=None, runtime=None)

    agenda = Agenda(
        items=[
            AgendaItem(value=Task(id=str(index), summary=f"Task {index}"), kind="task")
            for index in range(1, 15)
        ]
    )
    seen = []
    commands.register_builtin("today", lambda: agenda)
    commands.register_builtin("start", lambda *parts: seen.append(parts) or "started")
    from caldav_assistant.internal.cli.actions import EXIT_REPL
    commands.register_builtin("exit", lambda: EXIT_REPL)

    assert run_repl(app) == 0
    assert seen == [("1",)]
    assert "started" in io.out
