from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from caldav_assistant.api import ActionResult, Task
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

    def show(self, value):
        self.shown.append(value)

    def choose_task(self, **filters):
        return self.task

    def choose(self, title, items, **options):
        return self.field

    def ask_date(self, prompt):
        return self.due

    def ask_text(self, prompt):
        return self.text


class FakeTasks:
    def __init__(self, task):
        self.task = task
        self.calls = []

    def list(self, **filters):
        return [self.task]

    def find(self, query, **filters):
        self.calls.append(("find", query))
        return self.task

    def complete(self, task):
        self.calls.append(("complete", task))
        return ActionResult(True, affected=task)

    def start(self, task):
        self.calls.append(("start", task))
        return ActionResult(True, affected=task)

    def pause(self, task):
        self.calls.append(("pause", task))
        return ActionResult(True, affected=task)

    def resume(self, task):
        self.calls.append(("resume", task))
        return ActionResult(True, affected=task)

    def update(self, task, **changes):
        self.calls.append(("update", task, changes))
        return ActionResult(True, affected=task)


class FakeAgenda:
    def today(self):
        return "TODAY"

    def next(self):
        return "NEXT"


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
    ctx = SimpleNamespace(
        tasks=FakeTasks(task),
        agenda=FakeAgenda(),
        wordpress=FakeWordPress(),
        time=FakeTime(),
        ui=FakeUI(task),
        commands=commands,
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


def test_done_without_target_uses_promptkit_selection():
    ctx = make_ctx()
    action = BuiltinActions(ctx)

    action.done()

    assert ("complete", ctx.ui.task) in ctx.tasks.calls


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


def test_lifecycle_and_log_commands_only_call_public_namespaces():
    ctx = make_ctx()
    action = BuiltinActions(ctx)

    action.start("Report")
    action.pause("Report")
    action.resume("Report")
    ctx.ui.text = "Finished report"
    result = action.log()

    assert result.success is True
    assert ctx.wordpress.calls == ["Finished report"]
    assert ("start", ctx.ui.task) in ctx.tasks.calls
    assert ("pause", ctx.ui.task) in ctx.tasks.calls
    assert ("resume", ctx.ui.task) in ctx.tasks.calls


def test_registration_adds_frozen_cli_commands_without_overwriting_existing_core():
    ctx = make_ctx()
    original_today = lambda: "original"
    ctx.commands.register_builtin("today", original_today)

    register_cli_builtin_commands(ctx.commands, ctx)

    names = set(ctx.commands.names())
    assert {
        "today", "next", "edit", "done", "start", "pause", "resume",
        "log", "help", "exit", "edit-due",
    } <= names
    assert ctx.commands.get("today") is original_today
    assert all(ctx.commands.resolve(name).protected for name in names)
