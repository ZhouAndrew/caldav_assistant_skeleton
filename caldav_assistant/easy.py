"""Scratch-like public API for simple extensions and scripts.

Normal use should require only this module. Runtime, IPC, CalDAV, storage and platform
implementation details stay behind the current AssistantContext.
"""
from __future__ import annotations

from typing import Any, Iterable

from .api import AgendaItem, AssistantContext, Event, Task
from .api.v1.errors import AmbiguousError, NotFoundError, ValidationError
from .internal.commands.decorators import command
from .internal.runtime.current_context import get_current_context


def _ctx() -> AssistantContext:
    return get_current_context()


def _summary(value: Any) -> str:
    text = getattr(value, "summary", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    value_id = getattr(value, "id", None)
    return str(value_id) if value_id else str(value)


def _query_matches(items: Iterable[Any], query: str) -> list[Any]:
    needle = query.casefold()
    values = list(items)
    exact = [item for item in values if _summary(item).casefold() == needle]
    return exact or [item for item in values if needle in _summary(item).casefold()]


def _choose_ambiguous(kind: str, query: str, items: Iterable[Any]) -> Any:
    matches = _query_matches(items, query)
    if len(matches) < 2:
        raise AmbiguousError(query)
    chooser = getattr(_ctx().ui, "choose", None)
    if not callable(chooser):
        raise AmbiguousError(query)
    return chooser(f"Choose {kind}: {query}", matches, item_label=_summary)


def _resolve_task(task: Task | str) -> Task | None:
    """Resolve a Task object, id, or title; never accept an Event."""
    if isinstance(task, Event):
        raise ValidationError(
            "Event has no Task work lifecycle; this Easy API action requires a Task"
        )
    if isinstance(task, Task):
        return task
    if not isinstance(task, str) or not task.strip():
        raise ValidationError("Task reference must be a Task or non-empty text")

    query = task.strip()
    namespace = _ctx().tasks
    getter = getattr(namespace, "get", None)
    if callable(getter):
        try:
            return getter(query)
        except NotFoundError:
            pass
    try:
        return namespace.find(query)
    except AmbiguousError:
        return _choose_ambiguous("task", query, namespace.list())


def _resolve_event(event: Event | str) -> Event | None:
    """Resolve an Event object, id, or title; never treat it as a Task."""
    if isinstance(event, Task):
        raise ValidationError(
            "Task is not an Event; use the Task Easy API for work lifecycle actions"
        )
    if isinstance(event, Event):
        return event
    if not isinstance(event, str) or not event.strip():
        raise ValidationError("Event reference must be an Event or non-empty text")

    query = event.strip()
    namespace = _ctx().events
    getter = getattr(namespace, "get", None)
    if callable(getter):
        try:
            return getter(query)
        except NotFoundError:
            pass
    try:
        return namespace.find(query)
    except AmbiguousError:
        return _choose_ambiguous("event", query, namespace.list())


def _agenda_value(item: Any) -> Any:
    """Unwrap the public AgendaItem contract, retaining old tiny-test compatibility."""
    return item.value if isinstance(item, AgendaItem) else item


def _parse_temporal_text(value: Any, *, bias: str = "future") -> Any:
    if not isinstance(value, str):
        return value
    try:
        return _ctx().time.parse_date(value, bias=bias)
    except (ValidationError, ValueError):
        return _ctx().time.parse_datetime(value, bias=bias)


def _normalize_temporal_fields(
    fields: dict[str, Any],
    names: Iterable[str],
    *,
    bias: str = "future",
) -> dict[str, Any]:
    normalized = dict(fields)
    for name in names:
        if name in normalized:
            normalized[name] = _parse_temporal_text(normalized[name], bias=bias)
    return normalized


# Display
def show(value: Any) -> None:
    """Display a value through the current Assistant UI."""
    _ctx().ui.show(value)


# Tasks
def tasks(**filters: Any):
    """List Tasks using optional public filters."""
    return _ctx().tasks.list(**filters)


def today_tasks(**filters: Any):
    """List Tasks relevant to today."""
    return _ctx().tasks.list(today=True, **filters)


def overdue_tasks(**filters: Any):
    """List overdue Tasks."""
    return _ctx().tasks.list(overdue=True, **filters)


def next_task(**options: Any):
    """Return the recommended next Task, or None."""
    value = _agenda_value(_ctx().agenda.next(kind="task", **options))
    return value if isinstance(value, Task) else None


def find_task(query: str, **filters: Any):
    """Find one Task by id or human title query."""
    return _ctx().tasks.find(query, **filters)


# Events
def events(**filters: Any):
    """List Events using optional public filters."""
    return _ctx().events.list(**filters)


def today_events(**filters: Any):
    """List Events relevant to today."""
    return _ctx().events.list(today=True, **filters)


def next_event(**options: Any):
    """Return the recommended next Event, or None."""
    value = _agenda_value(_ctx().agenda.next(kind="event", **options))
    return value if isinstance(value, Event) else None


def find_event(query: str, **filters: Any):
    """Find one Event by id or human title query."""
    return _ctx().events.find(query, **filters)


# Agenda
def today():
    """Return today's combined Task/Event Agenda."""
    return _ctx().agenda.today()


def agenda(days: int = 1, **filters: Any):
    """Return a combined Agenda for a day range."""
    if days == 1 and not filters:
        return _ctx().agenda.today()
    return _ctx().agenda.range(days=days, **filters)


def next(**options: Any):
    """Return the recommended next AgendaItem, or None."""
    return _ctx().agenda.next(**options)


# Task actions
def add_task(summary: str, **fields: Any):
    """Create a Task; human date text is accepted for start/due."""
    normalized = _normalize_temporal_fields(fields, ("start", "due"))
    return _ctx().tasks.create(summary, **normalized)


def edit_task(task: Task | str, **changes: Any):
    """Update a Task selected by object, id, or title."""
    target = _resolve_task(task)
    if target is None:
        return None
    normalized = _normalize_temporal_fields(changes, ("start", "due"))
    return _ctx().tasks.update(target, **normalized)


def start(task: Task | str):
    """Start working on a Task now."""
    target = _resolve_task(task)
    return None if target is None else _ctx().tasks.start(target)


def pause(task: Task | str):
    """Pause the Task currently being worked on."""
    target = _resolve_task(task)
    return None if target is None else _ctx().tasks.pause(target)


def resume(task: Task | str):
    """Resume a previously paused Task."""
    target = _resolve_task(task)
    return None if target is None else _ctx().tasks.resume(target)


def complete(task: Task | str):
    """Mark a Task completed."""
    target = _resolve_task(task)
    return None if target is None else _ctx().tasks.complete(target)


def remove(task: Task | Event | str):
    """Delete a Task; an explicit Event object is also accepted."""
    if isinstance(task, Event):
        return _ctx().events.delete(task)
    target = _resolve_task(task)
    return None if target is None else _ctx().tasks.delete(target)


def set_due(task: Task | str, due: Any):
    """Change a Task due date/time; human date text is accepted."""
    target = _resolve_task(task)
    if target is None:
        return None
    return _ctx().tasks.update(target, due=_parse_temporal_text(due, bias="future"))


# Event actions
def add_event(summary: str, **fields: Any):
    """Create an Event; human date text is accepted for start/end."""
    normalized = _normalize_temporal_fields(fields, ("start", "end"))
    return _ctx().events.create(summary, **normalized)


def edit_event(event: Event | str, **changes: Any):
    """Update an Event selected by object, id, or title."""
    target = _resolve_event(event)
    if target is None:
        return None
    normalized = _normalize_temporal_fields(changes, ("start", "end"))
    return _ctx().events.update(target, **normalized)


def remove_event(event: Event | str):
    """Delete an Event selected by object, id, or title."""
    target = _resolve_event(event)
    return None if target is None else _ctx().events.delete(target)


# Time and prompts
def parse_date(text: str, *, bias: str = "any"):
    """Parse human date text with the shared TemporalParser."""
    return _ctx().time.parse_date(text, bias=bias)


def parse_datetime(text: str, *, bias: str = "any"):
    """Parse human date/time text with the shared TemporalParser."""
    return _ctx().time.parse_datetime(text, bias=bias)


def parse_time(text: str):
    """Parse human time text with the shared TemporalParser."""
    parser = getattr(_ctx().time, "parse_time", None)
    if callable(parser):
        return parser(text)
    return _ctx().time.parse_datetime(text).time()


def ask_date(prompt: str = "Date?"):
    """Ask the user for a date."""
    return _ctx().ui.ask_date(prompt)


def ask_time(prompt: str = "Time?"):
    """Ask the user for a time."""
    return _ctx().ui.ask_time(prompt)


def ask_datetime(prompt: str = "Date/time?"):
    """Ask the user for a date and time."""
    return _ctx().ui.ask_datetime(prompt)


# Menu blocks
def choose(items: Any, title: str = "Choose", **options: Any):
    """Ask the user to choose one item."""
    return _ctx().ui.choose(title, items, **options)


def choose_many(items: Any, title: str = "Choose", **options: Any):
    """Ask the user to choose multiple items."""
    chooser = getattr(_ctx().ui, "choose_many", None)
    if callable(chooser):
        return chooser(title, items, **options)
    return _ctx().ui.choose(title, items, multiple=True, **options)


def confirm(text: str, **options: Any):
    """Ask for yes/no confirmation."""
    return _ctx().ui.confirm(text, **options)


def choose_task(**filters: Any):
    """Ask the user to choose one Task."""
    return _ctx().ui.choose_task(**filters)


def choose_event(**filters: Any):
    """Ask the user to choose one Event."""
    return _ctx().ui.choose_event(**filters)


# Reminders and notifications
def remind(title: str, when: Any, **options: Any):
    """Create a reminder."""
    return _ctx().reminders.create(title, when, **options)


def notify(title: str, body: str = "", actions: Any = None):
    """Send a platform-independent notification."""
    return _ctx().notifications.send(title, body, actions)


def snooze(reminder: Any, until: Any):
    """Snooze an existing reminder."""
    return _ctx().reminders.snooze(reminder, until)


# Long-term log
def write_log(text: str, **metadata: Any):
    """Write or queue a long-term WordPress log."""
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
