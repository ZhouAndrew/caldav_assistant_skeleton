"""Discover the real public Python API without duplicating its documentation.

The catalog inspects only exported Easy/Object/Full API surfaces. Public signatures
and docstrings are the source of truth; internal implementation modules are ignored.
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


def _first_doc_line(obj: Any) -> str:
    text = inspect.getdoc(obj) or ""
    if not text:
        return ""
    paragraph = text.split("\n\n", 1)[0].strip()
    return " ".join(line.strip() for line in paragraph.splitlines() if line.strip())


def _fallback_summary(name: str, *, prefix: str = "") -> str:
    words = name.replace("_", " ").strip()
    return f"{prefix}{words}." if words else f"{prefix}public interface."


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
    if callable(obj):
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
        signature = _signature(obj)
        entries.append(
            APIEntry(
                path=f"easy.{name}",
                layer="easy",
                kind=_kind(obj),
                signature=signature,
                summary=_first_doc_line(obj)
                or _fallback_summary(name, prefix="Easy API: "),
                usage=f"from caldav_assistant.easy import {name}\n\n{name}(...)",
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
            summary=_first_doc_line(protocol)
            or f"AssistantContext namespace implementing {protocol.__name__}.",
            usage=prefix,
            source=f"caldav_assistant.api.v1.{protocol.__name__}",
        )
    ]

    for name, annotation in getattr(protocol, "__annotations__", {}).items():
        if name.startswith("_"):
            continue
        entries.append(
            APIEntry(
                path=f"{prefix}.{name}",
                layer="object",
                kind="attribute",
                signature=str(annotation),
                summary=_fallback_summary(name, prefix=f"{prefix}: "),
                usage=f"value = {prefix}.{name}",
                source=f"caldav_assistant.api.v1.{protocol.__name__}",
            )
        )

    for name, obj in vars(protocol).items():
        if name.startswith("_") or not callable(obj):
            continue
        entries.append(
            APIEntry(
                path=f"{prefix}.{name}",
                layer="object",
                kind="method",
                signature=_signature(obj, strip_bound=True),
                summary=_first_doc_line(obj)
                or _fallback_summary(name, prefix=f"{prefix}: "),
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
    for name, annotation in getattr(obj, "__annotations__", {}).items():
        if name.startswith("_"):
            continue
        entries.append(
            APIEntry(
                path=f"{owner_name}.{name}",
                layer="full",
                kind="attribute",
                signature=str(annotation),
                summary=_fallback_summary(name, prefix=f"{owner_name}: "),
                usage=f"{_snake_case(owner_name)}.{name}",
                source=f"caldav_assistant.api.v1.{owner_name}",
            )
        )

    for name, member in vars(obj).items():
        if name.startswith("_") or not callable(member):
            continue
        entries.append(
            APIEntry(
                path=f"{owner_name}.{name}",
                layer="full",
                kind="method",
                signature=_signature(member, strip_bound=True),
                summary=_first_doc_line(member)
                or _fallback_summary(name, prefix=f"{owner_name}: "),
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
        signature = _signature(obj)
        if inspect.isclass(obj):
            usage = f"from caldav_assistant.api.v1 import {name}\n\n{name}{signature}"
        elif callable(obj):
            usage = f"from caldav_assistant.api.v1 import {name}\n\n{name}(...)"
        else:
            usage = f"from caldav_assistant.api.v1 import {name}"
        entries.append(
            APIEntry(
                path=f"v1.{name}",
                layer="full",
                kind=_kind(obj),
                signature=signature,
                summary=_first_doc_line(obj)
                or _fallback_summary(name, prefix="Public v1: "),
                usage=usage,
                source="caldav_assistant.api.v1",
            )
        )
        if inspect.isclass(obj):
            entries.extend(_class_members(name, obj))
    return entries


def api_catalog(layer: str | None = None) -> tuple[APIEntry, ...]:
    """Return the discoverable Public API catalog."""
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
    return tuple(
        entry
        for entry in api_catalog(layer)
        if text in entry.path.casefold() or text in entry.summary.casefold()
    )


def api_exists(name: str, *, layer: str | None = None) -> bool:
    """Return whether a matching public interface exists."""
    return bool(_exact_matches(name, api_catalog(layer)))


def api_describe(name: str, *, layer: str | None = None) -> APIEntry:
    """Return one public interface description."""
    matches = _exact_matches(name, api_catalog(layer))
    if not matches:
        raise NotFoundError(f"Public API interface not found: {name}")
    if len(matches) > 1:
        choices = ", ".join(entry.path for entry in matches)
        raise AmbiguousError(f"Public API name is ambiguous: {name}. Matches: {choices}")
    return matches[0]


__all__ = ["APIEntry", "api_catalog", "api_find", "api_exists", "api_describe"]
