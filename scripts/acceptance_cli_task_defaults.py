#!/usr/bin/env python3
"""Human-path acceptance for the simplified CLI Task defaults.

This deliberately drives the normal command parser, PromptKit menus, CrudActions and
SettingsActions as a user would. CalDAV transport is replaced by a tiny in-memory
boundary so the acceptance is deterministic; production CalDAV integration is already
covered by the repository's separate real-server acceptance scripts.
"""
from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

from caldav_assistant.api import Task
from caldav_assistant.internal.cli.actions import EXIT_REPL
from caldav_assistant.internal.cli.app import run_repl
from caldav_assistant.internal.cli.crud import register_crud_cli_commands
from caldav_assistant.internal.cli.io import StdConsoleIO
from caldav_assistant.internal.commands import CommandRegistry, CommandService
from caldav_assistant.internal.prompts import Menu, PromptKit
from caldav_assistant.internal.settings.cli import register_settings_cli_command
from caldav_assistant.internal.settings.keys import (
    CALDAV_TASK_COLLECTION_URL,
    TASK_DEFAULT_VIEW,
)


class Tasks:
    def __init__(self):
        self.items = [
            Task(id="open", summary="Open task"),
            Task(id="done", summary="Done task", status="COMPLETED", completed=True),
        ]

    def list(self, **filters):
        items = list(self.items)
        if filters.pop("actionable", False):
            items = [
                item
                for item in items
                if not item.completed and item.status not in {"COMPLETED", "CANCELLED"}
            ]
        return items

    def create(self, summary, **fields):
        task = Task(id=f"t{len(self.items) + 1}", summary=str(summary), **fields)
        self.items.append(task)
        return f"created {task.summary}"


class Settings:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        if value is None:
            self.values.pop(key, None)
            return None
        self.values[key] = value
        return value

    def reset(self, key):
        self.values.pop(key, None)
        return None

    def list(self, category=None):
        return []

    def caldav_collections(self):
        return [
            {"name": "Tasks", "url": "https://dav.example/tasks/", "components": ["VTODO"]},
            {"name": "School", "url": "https://dav.example/school/", "components": ["VTODO", "VEVENT"]},
        ]


def scripted_input(values):
    iterator = iter(values)

    def read(prompt=""):
        try:
            value = next(iterator)
        except StopIteration as exc:
            raise EOFError from exc
        transcript.write(f"{prompt}{value}\n")
        return value

    return read


transcript = StringIO()
stderr = StringIO()
answers = [
    "tasks",
    "tasks completed",
    "add task New task",
    "1",  # first-use collection -> Tasks
    "1",  # saved default -> Continue
    "1",  # Task timing -> No date
    "4",  # Optional Task fields -> Create
    "settings tasks",
    "1",  # Default task view
    "5",  # all
    "1",  # saved default view -> Continue
    "0",  # leave Tasks settings
    "tasks",
    "exit",
]
io = StdConsoleIO(
    input_fn=scripted_input(answers),
    stdout=transcript,
    stderr=stderr,
)
tasks = Tasks()
settings = Settings()
session = SimpleNamespace(last_items=[], current_selection=None)
prompts = PromptKit(io, Menu(io), temporal=SimpleNamespace(), tasks=tasks)
commands = CommandService(CommandRegistry())
ctx = SimpleNamespace(
    ui=prompts,
    commands=commands,
    tasks=tasks,
    events=SimpleNamespace(list=lambda **_: []),
    session=session,
    settings=settings,
)
register_crud_cli_commands(commands, ctx)
register_settings_cli_command(commands, ctx)
commands.register_builtin("exit", lambda: EXIT_REPL)
app = SimpleNamespace(ctx=ctx, commands=commands, io=io, extensions=None)

code = run_repl(app)
visible = transcript.getvalue()
print(visible)

assert code == 0
assert stderr.getvalue() == ""
assert "Tasks · Incomplete · 1" in visible
assert "Tasks · Completed · 1" in visible
assert "Choose the default Task collection" in visible
assert "✓ Default task collection: Tasks" in visible
assert "Create Task → New task" in visible
assert "Default task view: incomplete" in visible
assert "✓ Default task view: all" in visible
assert "Tasks · All · 3" in visible
assert settings.get(CALDAV_TASK_COLLECTION_URL) == "https://dav.example/tasks/"
assert settings.get(TASK_DEFAULT_VIEW) == "all"
assert [task.summary for task in tasks.items] == ["Open task", "Done task", "New task"]

print("CLI TASK DEFAULTS HUMAN-PATH ACCEPTANCE: PASS")
