from __future__ import annotations

from types import SimpleNamespace

import pytest

from caldav_assistant.api import Agenda, AgendaItem, Event, Task
from caldav_assistant.api.v1.errors import ValidationError
from caldav_assistant.internal.cli.actions import BuiltinActions
from caldav_assistant.internal.cli.app import run_repl
from caldav_assistant.internal.commands import CommandRegistry, CommandService
from caldav_assistant.internal.prompts import Menu
from caldav_assistant.internal.session import CalDAVSessionService
from caldav_assistant.internal.settings.keys import CALDAV_WORKLOG_COLLECTION_URL
from caldav_assistant.internal.tasks.work_service import CalDAVWorkTaskService
from caldav_assistant.internal.worklog import WorkLogService


class NoCallAdapter:
    def list_events(self, **filters):
        raise AssertionError("unconfigured work-history reads must not touch CalDAV")


class FakeIO:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.out = []
        self.err = []
        self.prompts = []

    def read(self, prompt=""):
        self.prompts.append(str(prompt))
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


class SetupSettings:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        return value

    def caldav_collections(self):
        return [
            {"name": "Tasks", "url": "https://dav.example/tasks/", "components": ["VTODO"]},
            {"name": "Personal", "url": "https://dav.example/personal/", "components": ["VEVENT"]},
        ]


class SetupUI:
    def __init__(self):
        self.messages = []
        self.choices = []

    def show(self, value):
        self.messages.append(str(value))

    def choose(self, title, items, **kwargs):
        labels = list(items)
        self.choices.append((title, labels))
        if title == "Work log collection":
            assert labels == ["Personal [VEVENT]"]
            return labels[0]
        raise AssertionError(f"unexpected menu: {title}")


class IntegrationAdapter:
    def __init__(self):
        self.task = Task(id="t1", summary="Anki")
        self.events = []

    def list_tasks(self, **filters):
        items = [self.task]
        status = filters.get("status")
        if status is not None:
            items = [item for item in items if item.status == status]
        return items

    def get_task(self, task_id):
        if task_id != self.task.id:
            raise KeyError(task_id)
        return self.task

    def update_task(self, task_id, changes):
        task = self.get_task(task_id)
        for key, value in changes.items():
            setattr(task, key, value)
        return task

    def list_events(self, **filters):
        category = filters.get("category")
        if category is None:
            return list(self.events)
        return [event for event in self.events if category in set(event.categories or ())]

    def create_event(self, event):
        event.id = f"work-{len(self.events) + 1}"
        self.events.append(event)
        return event

    def update_event(self, event_id, changes):
        event = next(item for item in self.events if item.id == event_id)
        for key, value in changes.items():
            setattr(event, key, value)
        return event

    def delete_event(self, event_id):
        self.events = [item for item in self.events if item.id != event_id]


def test_unconfigured_work_history_does_not_block_read_context():
    worklog = WorkLogService(NoCallAdapter(), lambda: None)

    assert worklog.current_task_id() is None
    assert worklog.open_events() == []

    with pytest.raises(ValidationError, match="Work log collection is not configured"):
        worklog.start_segment(Task(id="t1", summary="Task"))


def test_menu_accepts_exact_human_label_without_requiring_number():
    io = FakeIO("CalDAV")
    menu = Menu(io)

    assert menu.choose("Settings", ["Language", "CalDAV", "WordPress"]) == "CalDAV"


def test_command_typed_at_agenda_pager_is_replayed_by_repl_and_counts_items():
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
    assert any("-- 10/14 --" in prompt for prompt in io.prompts)
    assert not any("-- 10/16 --" in prompt for prompt in io.prompts)


def test_first_start_auto_configures_single_worklog_collection_then_creates_caldav_work_interval():
    adapter = IntegrationAdapter()
    settings = SetupSettings()
    ui = SetupUI()
    worklog = WorkLogService(
        adapter,
        lambda: settings.get(CALDAV_WORKLOG_COLLECTION_URL, None),
    )
    session = CalDAVSessionService(worklog)
    tasks = CalDAVWorkTaskService(adapter, session=session, worklog=worklog)
    session.bind_tasks(tasks)
    ctx = SimpleNamespace(tasks=tasks, session=session, settings=settings, ui=ui)

    result = BuiltinActions(ctx).start("Anki")

    assert result.success is True
    assert settings.get(CALDAV_WORKLOG_COLLECTION_URL) == "https://dav.example/personal/"
    assert adapter.task.status == "IN-PROCESS"
    assert worklog.current_task_id() == "t1"
    assert len(adapter.events) == 1
    assert adapter.events[0].summary == "Work — Anki"
    assert ui.choices == []
    assert any("Work history ready: Personal" in message for message in ui.messages)
    assert any("only compatible calendar was selected automatically" in message for message in ui.messages)
    assert any("Start working → Anki" in message for message in ui.messages)
