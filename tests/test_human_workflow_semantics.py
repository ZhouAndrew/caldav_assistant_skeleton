from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from caldav_assistant.api import Agenda, AgendaItem, Task
from caldav_assistant.internal.agenda.service import AgendaService
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


def test_next_agenda_item_is_human_readable_and_never_leaks_raw_icalendar():
    io = FakeIO()
    commands = CommandService(CommandRegistry())
    app = SimpleNamespace(
        io=io,
        ctx=SimpleNamespace(ui=FakeUI(io), commands=commands),
        commands=commands,
    )
    raw = "BEGIN:VCALENDAR\r\nBEGIN:VTODO\r\nUID:secret\r\nEND:VTODO\r\nEND:VCALENDAR"
    item = AgendaItem(
        value=Task(
            id="secret-uid",
            summary="Physics homework",
            due=datetime(2026, 8, 29, 17, 0),
            raw=raw,
        ),
        kind="task",
    )
    commands.register_builtin("next", lambda: item)

    assert run_one_shot(app, ["next"]) == 0

    output = "\n".join(str(value) for value in io.out)
    assert "Next" in output
    assert "Physics homework" in output
    assert "AgendaItem(" not in output
    assert "BEGIN:VCALENDAR" not in output
    assert "secret-uid" not in output


class FakeTasks:
    def list(self, **filters):
        return [Task(id="paused", summary="Paused"), Task(id="other", summary="Other")]


class FakeEvents:
    def list(self, **filters):
        return []


class CandidateEngine:
    def candidates(self, tasks, events):
        return Agenda([AgendaItem(value=task, kind="task") for task in tasks])


class NextSpy:
    def __init__(self):
        self.options = None

    def choose(self, agenda, **options):
        self.options = options
        return agenda.items[1]


def test_paused_work_is_excluded_from_default_next_decision_context():
    state = {
        "current_task_uid": None,
        "paused_task_uids": ["paused"],
    }
    next_engine = NextSpy()
    service = AgendaService(
        FakeTasks(),
        FakeEvents(),
        CandidateEngine(),
        next_engine,
        state,
    )

    result = service.next(kind="task")

    assert result.value.id == "other"
    assert next_engine.options["skipped_uids"] == ("paused",)
