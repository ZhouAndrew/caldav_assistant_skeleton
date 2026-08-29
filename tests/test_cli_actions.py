from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from caldav_assistant.api import ActionResult, AgendaItem, Task
from caldav_assistant.api.v1.errors import ValidationError
from caldav_assistant.internal.cli.actions import (
    BuiltinActions,
    register_cli_builtin_commands,
)
from caldav_assistant.internal.commands import CommandRegistry, CommandService


class FakeUI:
    def __init__(self, task):
        self.task = task
        self.shown = []
        self.field = "Due date"
        self.due = date(2026, 8, 30)
        self.text = "value"
        self.choose_task_calls = 0
        self.confirm_calls = []

    def show(self, value):
        self.shown.append(value)

    def choose_task(self, **filters):
        self.choose_task_calls += 1
        return self.task

    def choose(self, title, items, **options):
        if title.startswith("Resume"):
            return list(items)[0]
        return self.field

    def ask_date(self, prompt):
        return self.due

    def ask_text(self, prompt):
        return self.text

    def confirm(self, text, **options):
        self.confirm_calls.append((text, options))
        return True


class FakeSession:
    def __init__(self):
        self.current = None
        self.paused = []

    def current_task(self):
        return self.current

    def paused_tasks(self):
        return list(self.paused)


class FakeTasks:
    def __init__(self, task, session):
        self.task = task
        self.calls = []
        self.session = session

    def list(self, **filters):
        return [self.task]

    def find(self, query, **filters):
        self.calls.append(("find", query))
        return self.task

    def complete(self, task):
        self.calls.append(("complete", task))
        if self.session.current is task:
            self.session.current = None
        self.session.paused = [item for item in self.session.paused if item is not task]
        return ActionResult(True, affected=task)

    def start(self, task):
        self.calls.append(("start", task))
        self.session.current = task
        self.session.paused = [item for item in self.session.paused if item is not task]
        return ActionResult(True, affected=task)

    def pause(self, task):
        self.calls.append(("pause", task))
        self.session.current = None
        if task not in self.session.paused:
            self.session.paused.insert(0, task)
        return ActionResult(True, affected=task)

    def resume(self, task):
        self.calls.append(("resume", task))
        self.session.current = task
        self.session.paused = [item for item in self.session.paused if item is not task]
        return ActionResult(True, affected=task)

    def update(self, task, **changes):
        self.calls.append(("update", task, changes))
        return ActionResult(True, affected=task)


class FakeAgenda:
    def __init__(self, task):
        self.task = task
        self.calls = []

    def today(self):
        return "TODAY"

    def next(self, kind=None):
        self.calls.append(("next", kind))
        return AgendaItem(value=self.task, kind="task")


class FakeWordPress:
    def __init__(self):
        self.calls = []

    def log(self, text):
        self.calls.append(text)
        return ActionResult(True, message="queued")


class FakeTime:
    def parse_date(self, text, *, bias="any"):
        return date(2026, 8, 30)


def make_ctx():
    task = Task(id="t1", summary="Report")
    commands = CommandService(CommandRegistry())
    session = FakeSession()
    tasks = FakeTasks(task, session)
    ctx = SimpleNamespace(
        tasks=tasks,
        agenda=FakeAgenda(task),
        wordpress=FakeWordPress(),
        time=FakeTime(),
        ui=FakeUI(task),
        commands=commands,
        session=session,
    )
    return ctx


def test_done_resolves_explicit_target_then_calls_canonical_task_api():
    ctx = make_ctx()
    action = BuiltinActions(ctx)

    result = action.done("Report")

    assert result.success is True
    assert ctx.tasks.calls == [
        ("find", "Report"),
        ("complete", ctx.ui.task),
    ]
    assert ctx.ui.shown[-1] == "Complete → Report"


def test_done_without_target_prefers_current_work_before_full_task_chooser():
    ctx = make_ctx()
    ctx.session.current = ctx.ui.task
    action = BuiltinActions(ctx)

    action.done()

    assert ("complete", ctx.ui.task) in ctx.tasks.calls
    assert ctx.ui.choose_task_calls == 0


def test_edit_is_composed_from_choose_task_choose_field_and_ask_date():
    ctx = make_ctx()
    action = BuiltinActions(ctx)

    result = action.edit()

    assert result.success is True
    assert ctx.tasks.calls[-1] == (
        "update",
        ctx.ui.task,
        {"due": date(2026, 8, 30)},
    )
    assert ctx.ui.shown[-1] == "Edit → Report; due: 2026-08-30"


def test_start_without_target_uses_recommended_task_not_all_tasks_menu():
    ctx = make_ctx()
    action = BuiltinActions(ctx)

    result = action.start()

    assert result.success is True
    assert ctx.agenda.calls == [("next", "task")]
    assert ctx.ui.choose_task_calls == 0
    assert ctx.ui.confirm_calls
    assert ctx.session.current is ctx.ui.task
    assert ctx.tasks.calls[-1] == ("start", ctx.ui.task)
    assert ctx.ui.shown[-1] == "Start working → Report"


def test_pause_has_no_arbitrary_target_and_only_pauses_current_work():
    ctx = make_ctx()
    action = BuiltinActions(ctx)

    with pytest.raises(ValidationError, match="nothing to pause"):
        action.pause()

    with pytest.raises(ValidationError, match="does not take a task name"):
        action.pause("Report")

    ctx.session.current = ctx.ui.task
    result = action.pause()

    assert result.success is True
    assert ctx.tasks.calls[-1] == ("pause", ctx.ui.task)
    assert ctx.session.current is None
    assert ctx.session.paused == [ctx.ui.task]
    assert ctx.ui.shown[-1] == "Pause current work → Report"


def test_resume_only_continues_previously_paused_work():
    ctx = make_ctx()
    action = BuiltinActions(ctx)

    with pytest.raises(ValidationError, match="no paused work"):
        action.resume()

    with pytest.raises(ValidationError, match="does not take an arbitrary task name"):
        action.resume("Report")

    ctx.session.paused = [ctx.ui.task]
    result = action.resume()

    assert result.success is True
    assert ctx.tasks.calls[-1] == ("resume", ctx.ui.task)
    assert ctx.session.current is ctx.ui.task
    assert ctx.session.paused == []
    assert ctx.ui.shown[-1] == "Resume work → Report"


def test_current_explains_active_and_inactive_states():
    ctx = make_ctx()
    action = BuiltinActions(ctx)

    assert "No task is active" in action.current()

    ctx.session.current = ctx.ui.task
    # Object identity is not part of the CLI/Object API contract: production
    # current() crosses Local IPC and therefore returns a detached Task value.
    assert action.current() == ctx.ui.task


def test_log_still_calls_public_wordpress_namespace():
    ctx = make_ctx()
    action = BuiltinActions(ctx)
    ctx.ui.text = "Finished report"

    result = action.log()

    assert result.success is True
    assert ctx.wordpress.calls == ["Finished report"]


def test_registration_uses_clear_human_lifecycle_commands_and_hides_legacy_edit_due_from_help():
    ctx = make_ctx()
    original_today = lambda: "original"
    ctx.commands.register_builtin("today", original_today)

    register_cli_builtin_commands(ctx.commands, ctx)

    names = set(ctx.commands.names())
    assert {
        "today", "next", "current", "edit", "done", "start", "pause", "resume",
        "log", "help", "exit", "edit-due",
    } <= names
    assert ctx.commands.get("today") is original_today
    assert all(ctx.commands.resolve(name).protected for name in names)

    help_text = ctx.commands.run("help")
    assert "start — Begin working on a task now." in help_text
    assert "pause — Pause the task you are working on now." in help_text
    assert "resume — Continue a task you previously paused." in help_text
    assert "current — Show the task you are working on now." in help_text
    assert "edit-due" not in help_text
