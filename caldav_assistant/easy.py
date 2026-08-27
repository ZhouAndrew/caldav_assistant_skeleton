"""Scratch-like Easy Tools API.

MODULE CONTRACT
- Imports: public AssistantContext/models + tiny internal context/command binding.
- Calls: public namespaces through the current ``AssistantContext`` only.
- Provides: short synchronous blocks for simple extensions and scripts.
- Must not: expose ctx, async/await, CalDAV XML, IPC, SQLite, or OS APIs.

This module deliberately contains delegation only.  Task/Event/Agenda/Reminder/
WordPress behavior remains in the same Core services used by CLI/background.
"""
from __future__ import annotations

from typing import Any

from .api import AssistantContext, Event, Task
from .internal.commands.decorators import command
from .internal.runtime.current_context import get_current_context


def _ctx() -> AssistantContext:
    return get_current_context()


# ---- Display ------------------------------------------------------------
def show(value: Any) -> None:
    _ctx().ui.show(value)


# ---- Task query blocks --------------------------------------------------
def tasks(**filters: Any):
    return _ctx().tasks.list(**filters)


def today_tasks(**filters: Any):
    return _ctx().tasks.list(today=True, **filters)


def overdue_tasks(**filters: Any):
    return _ctx().tasks.list(overdue=True, **filters)


def next_task(**options: Any):
    value = _ctx().agenda.next(kind="task", **options)
    return value if isinstance(value, Task) else None


def find_task(query: str, **filters: Any):
    return _ctx().tasks.find(query, **filters)


# ---- Event query blocks -------------------------------------------------
def events(**filters: Any):
    return _ctx().events.list(**filters)


def today_events(**filters: Any):
    return _ctx().events.list(today=True, **filters)


def next_event(**options: Any):
    value = _ctx().agenda.next(kind="event", **options)
    return value if isinstance(value, Event) else None


def find_event(query: str, **filters: Any):
    return _ctx().events.find(query, **filters)


# ---- Agenda blocks ------------------------------------------------------
def today():
    return _ctx().agenda.today()


def agenda(days: int = 1, **filters: Any):
    if days == 1 and not filters:
        return _ctx().agenda.today()
    return _ctx().agenda.range(days=days, **filters)


def next(**options: Any):
    return _ctx().agenda.next(**options)


# ---- Task action blocks -------------------------------------------------
def add_task(summary: str, **fields: Any):
    return _ctx().tasks.create(summary, **fields)


def edit_task(task: Task | str, **changes: Any):
    return _ctx().tasks.update(task, **changes)


def start(task: Task | str):
    return _ctx().tasks.start(task)


def pause(task: Task | str):
    return _ctx().tasks.pause(task)


def resume(task: Task | str):
    return _ctx().tasks.resume(task)


def complete(task: Task | str):
    return _ctx().tasks.complete(task)


def remove(task: Task | Event | str):
    # A bare string follows the Task path.  Event callers have remove_event().
    if isinstance(task, Event):
        return _ctx().events.delete(task)
    return _ctx().tasks.delete(task)


def set_due(task: Task | str, due: Any):
    return _ctx().tasks.update(task, due=due)


# ---- Event action blocks ------------------------------------------------
def add_event(summary: str, **fields: Any):
    return _ctx().events.create(summary, **fields)


def edit_event(event: Event | str, **changes: Any):
    return _ctx().events.update(event, **changes)


def remove_event(event: Event | str):
    return _ctx().events.delete(event)


# ---- Time / prompt blocks -----------------------------------------------
def parse_date(text: str, *, bias: str = "any"):
    return _ctx().time.parse_date(text, bias=bias)


def parse_datetime(text: str, *, bias: str = "any"):
    return _ctx().time.parse_datetime(text, bias=bias)


def parse_time(text: str):
    # Prefer a native public TemporalService brick when available while retaining
    # compatibility with the existing parse_datetime-based implementation.
    parser = getattr(_ctx().time, "parse_time", None)
    if callable(parser):
        return parser(text)
    return _ctx().time.parse_datetime(text).time()


def ask_date(prompt: str = "Date?"):
    return _ctx().ui.ask_date(prompt)


def ask_time(prompt: str = "Time?"):
    return _ctx().ui.ask_time(prompt)


def ask_datetime(prompt: str = "Date/time?"):
    return _ctx().ui.ask_datetime(prompt)


# ---- Menu blocks --------------------------------------------------------
def choose(items: Any, title: str = "Choose", **options: Any):
    return _ctx().ui.choose(title, items, **options)


def choose_many(items: Any, title: str = "Choose", **options: Any):
    chooser = getattr(_ctx().ui, "choose_many", None)
    if callable(chooser):
        return chooser(title, items, **options)
    return _ctx().ui.choose(title, items, multiple=True, **options)


def confirm(text: str, **options: Any):
    return _ctx().ui.confirm(text, **options)


def choose_task(**filters: Any):
    return _ctx().ui.choose_task(**filters)


def choose_event(**filters: Any):
    return _ctx().ui.choose_event(**filters)


# ---- Reminder / notification blocks ------------------------------------
def remind(title: str, when: Any, **options: Any):
    return _ctx().reminders.create(title, when, **options)


def notify(title: str, body: str = "", actions: Any = None):
    return _ctx().notifications.send(title, body, actions)


def snooze(reminder: Any, until: Any):
    return _ctx().reminders.snooze(reminder, until)


# ---- WordPress block ----------------------------------------------------
def write_log(text: str, **metadata: Any):
    return _ctx().wordpress.log(text, **metadata)


__all__ = [
    "show",
    "tasks",
    "today_tasks",
    "overdue_tasks",
    "next_task",
    "find_task",
    "events",
    "today_events",
    "next_event",
    "find_event",
    "today",
    "agenda",
    "next",
    "add_task",
    "edit_task",
    "start",
    "pause",
    "resume",
    "complete",
    "remove",
    "set_due",
    "add_event",
    "edit_event",
    "remove_event",
    "parse_date",
    "parse_time",
    "parse_datetime",
    "ask_date",
    "ask_time",
    "ask_datetime",
    "choose",
    "choose_many",
    "confirm",
    "choose_task",
    "choose_event",
    "remind",
    "notify",
    "snooze",
    "write_log",
    "command",
]
