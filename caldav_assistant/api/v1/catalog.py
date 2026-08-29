"""Self-describing catalog for the stable Public Python API v1.

The catalog is deliberately built from the actual public modules and Protocols so
documentation cannot silently claim that an interface exists when it is not exported.
It never scans ``caldav_assistant.internal`` and therefore preserves the frozen
Public/Internal compatibility boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
import importlib
import inspect
import re
from typing import Any, Iterable

from .errors import AmbiguousError, NotFoundError
from .protocols import (
    ActivityAPI,
    AgendaAPI,
    CommandsAPI,
    EventsAPI,
    NotificationsAPI,
    RemindersAPI,
    SessionAPI,
    SettingsAPI,
    TasksAPI,
    TemporalAPI,
    UIAPI,
    WordPressAPI,
)


@dataclass(frozen=True, slots=True)
class APIEntry:
    """One discoverable public interface."""

    path: str
    layer: str
    kind: str
    signature: str
    summary: str
    usage: str
    source: str


_NAMESPACE_PROTOCOLS: tuple[tuple[str, type[Any]], ...] = (
    ("ctx.tasks", TasksAPI),
    ("ctx.events", EventsAPI),
    ("ctx.agenda", AgendaAPI),
    ("ctx.reminders", RemindersAPI),
    ("ctx.notifications", NotificationsAPI),
    ("ctx.wordpress", WordPressAPI),
    ("ctx.ui", UIAPI),
    ("ctx.time", TemporalAPI),
    ("ctx.commands", CommandsAPI),
    ("ctx.activity", ActivityAPI),
    ("ctx.settings", SettingsAPI),
    ("ctx.session", SessionAPI),
)

_LAYER_ORDER = {"easy": 0, "object": 1, "full": 2}
_LAYER_ALIASES = {
    "easy": "easy",
    "tools": "easy",
    "object": "object",
    "ctx": "object",
    "context": "object",
    "full": "full",
    "v1": "full",
}

_EASY_SUMMARIES = {
    "show": "Display a value through the current Assistant UI.",
    "tasks": "List tasks using optional public Task filters.",
    "today_tasks": "List tasks relevant to today.",
    "overdue_tasks": "List overdue tasks.",
    "next_task": "Return the recommended next Task, if one exists.",
    "find_task": "Find one Task by id/title-like query.",
    "events": "List events using optional public Event filters.",
    "today_events": "List events relevant to today.",
    "next_event": "Return the recommended next Event, if one exists.",
    "find_event": "Find one Event by id/title-like query.",
    "today": "Return today's combined Agenda.",
    "agenda": "Return an Agenda for a day range and optional filters.",
    "next": "Return the recommended next agenda item.",
    "add_task": "Create a Task through the shared Task Core service.",
    "edit_task": "Update a Task through the shared Task Core service.",
    "start": "Begin working on a Task now.",
    "pause": "Pause work on a Task.",
    "resume": "Resume previously paused work on a Task.",
    "complete": "Mark a Task completed.",
    "remove": "Delete a Task, or an Event object passed explicitly.",
    "set_due": "Change a Task due value using the shared temporal parser.",
    "add_event": "Create an Event through the shared Event Core service.",
    "edit_event": "Update an Event through the shared Event Core service.",
    "remove_event": "Delete an Event.",
    "parse_date": "Parse human date text with the shared TemporalParser.",
    "parse_time": "Parse human time text with the shared TemporalParser.",
    "parse_datetime": "Parse human date/time text with the shared TemporalParser.",
    "ask_date": "Prompt for a date using the shared UI/PromptKit.",
    "ask_time": "Prompt for a time using the shared UI/PromptKit.",
    "ask_datetime": "Prompt for a date/time using the shared UI/PromptKit.",
    "choose": "Choose one item using the shared UI/PromptKit.",
    "choose_many": "Choose multiple items using the shared UI/PromptKit.",
    "confirm": "Ask a yes/no confirmation through the shared UI.",
    "choose_task": "Choose one Task through the shared UI.",
    "choose_event": "Choose one Event through the shared UI.",
    "remind": "Create a reminder through ReminderService.",
    "notify": "Send a notification through NotificationService.",
    "snooze": "Snooze an existing reminder.",
    "write_log": "Write or queue a long-term WordPress activity log.",
    "command": "Register an extension command in the shared Command Registry.",
}

_EASY_EXAMPLES = {
    "show": "show(today())",
    "tasks": "for task in tasks(category='school'):\n    show(task)",
    "today_tasks": "show(today_tasks())",
    "overdue_tasks": "show(overdue_tasks())",
    "next_task": "task = next_task()",
    "find_task": "task = find_task('report')",
    "events": "show(events())",
    "today_events": "show(today_events())",
    "next_event": "event = next_event()",
    "find_event": "event = find_event('English class')",
    "today": "show(today())",
    "agenda": "show(agenda(days=7, category='school'))",
    "next": "show(next())",
    "add_task": "add_task('Write report', due='tomorrow')",
    "edit_task": "edit_task(task, priority=1)",
    "start": "start(next_task())",
    "pause": "pause(task)",
    "resume": "resume(task)",
    "complete": "complete(task)",
    "remove": "remove(task)",
    "set_due": "set_due(task, 'next Friday')",
    "add_event": "add_event('English class', start='tomorrow 17:00')",
    "edit_event": "edit_event(event, location='Room 2')",
    "remove_event": "remove_event(event)",
    "parse_date": "due = parse_date('August5', bias='future')",
    "parse_time": "at = parse_time('17:30')",
    "parse_datetime": "when = parse_datetime('tomorrow 17:00', bias='future')",
    "ask_date": "due = ask_date('Due?')",
    "ask_time": "at = ask_time('Time?')",
    "ask_datetime": "when = ask_datetime('When?')",
    "choose": "item = choose(['A', 'B'], title='Choose')",
    "choose_many": "items = choose_many(['A', 'B'], title='Choose')",
    "confirm": "if confirm('Continue?'):\n    show('OK')",
    "choose_task": "task = choose_task()",
    "choose_event": "event = choose_event()",
    "remind": "remind('Submit report', 'tomorrow 17:00')",
    "notify": "notify('CalDAV Assistant', 'Done')",
    "snooze": "snooze(reminder, 'in 15 minutes')",
    "write_log": "write_log('Finished report')",
    "command": "@command('school')\ndef school():\n    show(agenda(days=7, category='school'))",
}


def _first_doc_line(obj: Any) -> str:
    text = inspect.getdoc(obj) or ""
    if not text:
        return ""
    paragraph = text.split("\n\n", 1)[0].strip()
    return " ".join(line.strip() for line in paragraph.splitlines() if line.strip())


def _signature(obj: Any, *, strip_bound: bool = False) -> str:
    try:
        value = inspect.signature(obj)
    except (TypeError, ValueError):
        return ""
    if strip_bound:
        params = list(value.parameters.values())
        if params and params[0].name in {"self", "cls"}:
            value = value.replace(parameters=params[1:])
    return str(value)


def _kind(obj: Any) -> str:
    if inspect.isclass(obj):
        return "class"
    if inspect.isfunction(obj) or inspect.ismethod(obj) or callable(obj):
        return "callable"
    return "value"


def _snake_case(name: str) -> str:
    first = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", first).lower()


def _normalize_layer(layer: str | None) -> str | None:
    if layer is None:
        return None
    clean = str(layer).strip().casefold()
    if not clean:
        return None
    normalized = _LAYER_ALIASES.get(clean)
    if normalized is None:
        raise ValueError("layer must be one of: easy, object, full")
    return normalized


def _collect_easy() -> list[APIEntry]:
    module = importlib.import_module("caldav_assistant.easy")
    entries: list[APIEntry] = []
    for name in getattr(module, "__all__", ()):
        if not isinstance(name, str) or name.startswith("_") or not hasattr(module, name):
            continue
        obj = getattr(module, name)
        summary = _EASY_SUMMARIES.get(name) or _first_doc_line(obj) or "Public Easy API callable."
        example = _EASY_EXAMPLES.get(name, f"{name}(...)")
        entries.append(
            APIEntry(
                path=f"easy.{name}",
                layer="easy",
                kind=_kind(obj),
                signature=_signature(obj),
                summary=summary,
                usage=f"from caldav_assistant.easy import {name}\n\n{example}",
                source="caldav_assistant.easy",
            )
        )
    return entries


def _protocol_members(prefix: str, protocol: type[Any]) -> list[APIEntry]:
    entries = [
        APIEntry(
            path=prefix,
            layer="object",
            kind="namespace",
            signature=protocol.__name__,
            summary=f"AssistantContext namespace implementing {protocol.__name__}.",
            usage=f"{prefix}",
            source=f"caldav_assistant.api.v1.{protocol.__name__}",
        )
    ]

    annotations = getattr(protocol, "__annotations__", {})
    for name, annotation in annotations.items():
        if name.startswith("_"):
            continue
        entries.append(
            APIEntry(
                path=f"{prefix}.{name}",
                layer="object",
                kind="attribute",
                signature=str(annotation),
                summary=f"Public {prefix} attribute.",
                usage=f"value = {prefix}.{name}",
                source=f"caldav_assistant.api.v1.{protocol.__name__}",
            )
        )

    for name, obj in vars(protocol).items():
        if name.startswith("_") or not callable(obj):
            continue
        summary = _first_doc_line(obj) or f"Public {prefix} method."
        entries.append(
            APIEntry(
                path=f"{prefix}.{name}",
                layer="object",
                kind="method",
                signature=_signature(obj, strip_bound=True),
                summary=summary,
                usage=f"{prefix}.{name}(...)",
                source=f"caldav_assistant.api.v1.{protocol.__name__}",
            )
        )
    return entries


def _collect_object() -> list[APIEntry]:
    entries: list[APIEntry] = []
    for prefix, protocol in _NAMESPACE_PROTOCOLS:
        entries.extend(_protocol_members(prefix, protocol))
    return entries


def _class_members(owner_name: str, obj: type[Any]) -> list[APIEntry]:
    entries: list[APIEntry] = []
    annotations = getattr(obj, "__annotations__", {})
    for name, annotation in annotations.items():
        if name.startswith("_"):
            continue
        entries.append(
            APIEntry(
                path=f"{owner_name}.{name}",
                layer="full",
                kind="attribute",
                signature=str(annotation),
                summary=f"Public {owner_name} attribute.",
                usage=f"{_snake_case(owner_name)}.{name}",
                source=f"caldav_assistant.api.v1.{owner_name}",
            )
        )

    for name, member in vars(obj).items():
        if name.startswith("_") or not callable(member):
            continue
        summary = _first_doc_line(member) or f"Public {owner_name} method."
        entries.append(
            APIEntry(
                path=f"{owner_name}.{name}",
                layer="full",
                kind="method",
                signature=_signature(member, strip_bound=True),
                summary=summary,
                usage=f"{_snake_case(owner_name)}.{name}(...)",
                source=f"caldav_assistant.api.v1.{owner_name}",
            )
        )
    return entries


def _collect_full() -> list[APIEntry]:
    module = importlib.import_module("caldav_assistant.api.v1")
    entries: list[APIEntry] = []
    for name in getattr(module, "__all__", ()):
        if not isinstance(name, str) or name.startswith("_") or not hasattr(module, name):
            continue
        obj = getattr(module, name)
        summary = _first_doc_line(obj) or f"Versioned v1 public {_kind(obj)}."
        if inspect.isclass(obj):
            usage = f"from caldav_assistant.api.v1 import {name}\n\n{name}{_signature(obj)}"
        elif callable(obj):
            usage = f"from caldav_assistant.api.v1 import {name}\n\n{name}(...)"
        else:
            usage = f"from caldav_assistant.api.v1 import {name}"
        entries.append(
            APIEntry(
                path=f"v1.{name}",
                layer="full",
                kind=_kind(obj),
                signature=_signature(obj),
                summary=summary,
                usage=usage,
                source="caldav_assistant.api.v1",
            )
        )
        if inspect.isclass(obj):
            entries.extend(_class_members(name, obj))
    return entries


def api_catalog(layer: str | None = None) -> tuple[APIEntry, ...]:
    """Return the actual discoverable Public API catalog.

    ``layer`` accepts ``easy``, ``object``/``ctx`` or ``full``/``v1``.
    """

    wanted = _normalize_layer(layer)
    entries = _collect_easy() + _collect_object() + _collect_full()
    unique = {(entry.layer, entry.path): entry for entry in entries}
    values = list(unique.values())
    if wanted is not None:
        values = [entry for entry in values if entry.layer == wanted]
    values.sort(key=lambda entry: (_LAYER_ORDER.get(entry.layer, 99), entry.path.casefold()))
    return tuple(values)


def _normalized_query(value: str) -> str:
    clean = str(value).strip()
    prefixes = (
        "caldav_assistant.easy.",
        "caldav_assistant.api.v1.",
        "caldav_assistant.api.",
        "AssistantContext.",
    )
    for prefix in prefixes:
        if clean.casefold().startswith(prefix.casefold()):
            clean = clean[len(prefix):]
            if prefix.casefold().startswith("caldav_assistant.easy"):
                clean = f"easy.{clean}"
            elif prefix.casefold().startswith("caldav_assistant.api"):
                clean = f"v1.{clean}"
            elif prefix == "AssistantContext.":
                clean = f"ctx.{clean}"
            break
    return clean.casefold()


def _exact_matches(query: str, entries: Iterable[APIEntry]) -> list[APIEntry]:
    normalized = _normalized_query(query)
    matches = [entry for entry in entries if entry.path.casefold() == normalized]
    if matches:
        return matches

    return [
        entry
        for entry in entries
        if entry.path.rsplit(".", 1)[-1].casefold() == normalized
    ]


def api_find(query: str, *, layer: str | None = None) -> tuple[APIEntry, ...]:
    """Search public interface paths and summaries."""

    text = str(query).strip().casefold()
    if not text:
        return api_catalog(layer)
    values = [
        entry
        for entry in api_catalog(layer)
        if text in entry.path.casefold() or text in entry.summary.casefold()
    ]
    return tuple(values)


def api_exists(name: str, *, layer: str | None = None) -> bool:
    """Return whether a matching public interface exists."""

    return bool(_exact_matches(name, api_catalog(layer)))


def api_describe(name: str, *, layer: str | None = None) -> APIEntry:
    """Return one public interface description or raise a stable v1 API error."""

    matches = _exact_matches(name, api_catalog(layer))
    if not matches:
        raise NotFoundError(f"Public API interface not found: {name}")
    if len(matches) > 1:
        choices = ", ".join(entry.path for entry in matches)
        raise AmbiguousError(f"Public API name is ambiguous: {name}. Matches: {choices}")
    return matches[0]


__all__ = [
    "APIEntry",
    "api_catalog",
    "api_find",
    "api_exists",
    "api_describe",
]
