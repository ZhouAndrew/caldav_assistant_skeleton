"""Scratch-like Easy Tools API.

MODULE CONTRACT
- Imports: public AssistantContext/models/errors + tiny internal context/command binding.
- Calls: public namespaces through the current ``AssistantContext`` only.
- Provides: short synchronous blocks for simple extensions and scripts.
- Must not: expose ctx, async/await, CalDAV XML, IPC, SQLite, or OS APIs.

Easy API is the primary extension surface.  It may resolve human-friendly references,
reuse PromptKit for ambiguity, and normalize human temporal text, but authoritative
Task/Event behavior remains in the same Core services used by CLI/background.

Important domain rule: Tasks are work that can be started/paused/resumed/completed.
Events are scheduled occurrences and deliberately have no completion lifecycle.
"""
from __future__ import annotations

from typing import Any, Iterable

from .api import AssistantContext, Event, Task
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
    return chooser(
        f"Choose {kind}: {query}",
        matches,
        item_label=_summary,
    )


def _resolve_task(task: Task | str) -> Task | None:
    """Resolve a Task object, id, or human title without ever accepting Event."""
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

    # Preserve v1 compatibility for callers that already pass a Task id.
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
    """Resolve an Event object, id, or human title without treating it as Task."""
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


def _parse_temporal_text(value: Any, *, bias: str = "future") -> Any:
    """Keep date-only text as ``date``; use datetime only when text contains time."""
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
    normalized = _normalize_temporal_fields(fields, ("start", "due"))
    return _ctx().tasks.create(summary, **normalized)


def edit_task(task: Task | str, **changes: Any):
    target = _resolve_task(task)
    if target is None:
        return None
    normalized = _normalize_temporal_fields(changes, ("start", "due"))
    return _ctx().tasks.update(target, **normalized)


def start(task: Task | str):
    target = _resolve_task(task)
    return None if target is None else _ctx().tasks.start(target)


def pause(task: Task | str):
    target = _resolve_task(task)
    return None if target is None else _ctx().tasks.pause(target)


def resume(task: Task | str):
    target = _resolve_task(task)
    return None if target is None else _ctx().tasks.resume(target)


def complete(task: Task | str):
    target = _resolve_task(task)
    return None if target is None else _ctx().tasks.complete(target)


def remove(task: Task | Event | str):
    """Remove a Task; an Event object is accepted for v1 convenience.

    Bare text remains Task-first for compatibility.  Use ``remove_event(text)`` when
    removing an Event by id/title so Task and Event namespaces stay unambiguous.
    """
    if isinstance(task, Event):
        return _ctx().events.delete(task)
    target = _resolve_task(task)
    return None if target is None else _ctx().tasks.delete(target)


def set_due(task: Task | str, due: Any):
    target = _resolve_task(task)
    if target is None:
        return None
    return _ctx().tasks.update(target, due=_parse_temporal_text(due, bias="future"))


# ---- Event action blocks ------------------------------------------------
def add_event(summary: str, **fields: Any):
    normalized = _normalize_temporal_fields(fields, ("start", "end"))
    return _ctx().events.create(summary, **normalized)


def edit_event(event: Event | str, **changes: Any):
    target = _resolve_event(event)
    if target is None:
        return None
    normalized = _normalize_temporal_fields(changes, ("start", "end"))
    return _ctx().events.update(target, **normalized)


def remove_event(event: Event | str):
    target = _resolve_event(event)
    return None if target is None else _ctx().events.delete(target)


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
