"""Shortcut-style categorized command help for the CLI.

The normal command registry remains the source of truth.  This module only projects
registered commands into a small human-facing Action Library, similar to the way
Shortcuts shows action families before individual actions.

Design rules:
- bare ``help`` shows categories, never the whole registry;
- ``help <category>`` shows only that category;
- ``help <command>`` remains the detailed command help path;
- ``help all`` is the explicit escape hatch for a complete grouped catalog;
- extension/user commands remain discoverable without flooding the root view;
- command metadata can opt into ``help_category`` or ``help_hidden`` without
  changing CommandRegistry or the frozen Public Python API.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class HelpCategory:
    key: str
    title: str
    purpose: str
    commands: tuple[str, ...] = ()


_CORE_CATEGORIES: tuple[HelpCategory, ...] = (
    HelpCategory(
        "agenda",
        "Agenda",
        "See what matters now or next.",
        ("today", "next", "current"),
    ),
    HelpCategory(
        "work",
        "Work",
        "Start, pause, resume, or complete actual work.",
        ("start", "pause", "resume", "done"),
    ),
    HelpCategory(
        "manage",
        "Tasks & Events",
        "Create, inspect, edit, remove, or undo planned items.",
        ("add", "tasks", "events", "edit", "edit-event", "remove", "undo"),
    ),
    HelpCategory(
        "records",
        "Logs & History",
        "Write long-term notes or inspect what really happened.",
        ("log", "history"),
    ),
    HelpCategory(
        "system",
        "Settings & System",
        "Configure CalDAV Assistant, background service, and extensions.",
        ("settings", "background", "extensions", "extension"),
    ),
    HelpCategory(
        "learn",
        "Learn & Navigate",
        "Use guided navigation, detailed help, or browse the Public Python API.",
        ("menu", "help", "api", "exit"),
    ),
)

_DYNAMIC_CATEGORIES: tuple[HelpCategory, ...] = (
    HelpCategory(
        "added",
        "Added Actions",
        "Commands supplied by extensions or user automations.",
    ),
    HelpCategory(
        "other",
        "Other Actions",
        "Registered commands that do not yet belong to a standard category.",
    ),
)

_HIDDEN_COMMANDS = frozenset({"edit-due"})
_CATEGORY_BY_COMMAND = {
    command.casefold(): category.key
    for category in _CORE_CATEGORIES
    for command in category.commands
}
_CATEGORY_BY_KEY = {
    category.key: category
    for category in (*_CORE_CATEGORIES, *_DYNAMIC_CATEGORIES)
}


def _metadata(entry: Any) -> dict[str, Any]:
    value = getattr(entry, "metadata", None)
    try:
        return dict(value or {})
    except Exception:
        return {}


def _name(entry: Any) -> str:
    return str(getattr(entry, "name", "") or "").strip()


def _is_hidden(entry: Any) -> bool:
    name = _name(entry).casefold()
    if name in _HIDDEN_COMMANDS:
        return True
    return bool(_metadata(entry).get("help_hidden", False))


def category_key_for(entry: Any) -> str:
    """Return one stable help category for a registered command entry."""
    metadata = _metadata(entry)
    requested = str(metadata.get("help_category", "") or "").strip().casefold()
    if requested in _CATEGORY_BY_KEY:
        return requested

    name = _name(entry).casefold()
    known = _CATEGORY_BY_COMMAND.get(name)
    if known is not None:
        return known

    source = str(getattr(entry, "source", "") or "").strip().casefold()
    if source == "user" or source == "extension" or source.startswith("extension:"):
        return "added"
    return "other"


def visible_entries(entries: Iterable[Any]) -> tuple[Any, ...]:
    return tuple(entry for entry in entries if _name(entry) and not _is_hidden(entry))


def entries_by_category(entries: Iterable[Any]) -> dict[str, tuple[Any, ...]]:
    grouped: dict[str, list[Any]] = {key: [] for key in _CATEGORY_BY_KEY}
    for entry in visible_entries(entries):
        grouped.setdefault(category_key_for(entry), []).append(entry)
    return {key: tuple(values) for key, values in grouped.items()}


def category_keys() -> tuple[str, ...]:
    return tuple(category.key for category in (*_CORE_CATEGORIES, *_DYNAMIC_CATEGORIES))


def is_category(value: str) -> bool:
    return value.strip().casefold() in _CATEGORY_BY_KEY


def _entry_line(entry: Any) -> str:
    name = _name(entry)
    description = str(getattr(entry, "description", "") or "").strip()
    return f"  {name}" + (f" — {description}" if description else "")


def _available_categories(grouped: dict[str, tuple[Any, ...]]) -> tuple[HelpCategory, ...]:
    ordered = (*_CORE_CATEGORIES, *_DYNAMIC_CATEGORIES)
    return tuple(category for category in ordered if grouped.get(category.key))


def render_help_root(entries: Iterable[Any]) -> str:
    """Render the compact first-level Action Library, not a command dump."""
    grouped = entries_by_category(entries)
    categories = _available_categories(grouped)
    lines = [
        "Help · Action Library",
        "",
        "What do you want to do?",
    ]
    for category in categories:
        lines.append(f"  {category.key:<8} {category.title} — {category.purpose}")

    lines.extend(
        [
            "",
            "Open a category:  help work",
            "Explain an action: help pause",
            "Show all actions:  help all",
            "Number-based guide: menu",
        ]
    )
    return "\n".join(lines)


def render_help_category(entries: Iterable[Any], key: str) -> str:
    clean = key.strip().casefold()
    category = _CATEGORY_BY_KEY[clean]
    grouped = entries_by_category(entries)
    values = grouped.get(clean, ())
    lines = [
        f"Help · {category.title}",
        category.purpose,
        "",
    ]
    if values:
        lines.extend(_entry_line(entry) for entry in values)
    else:
        lines.append("  (No actions are currently available in this category.)")
    lines.extend(
        [
            "",
            "Use 'help <command>' for meaning, data writes, side effects, and verification.",
            "Back to categories: help",
        ]
    )
    return "\n".join(lines)


def render_help_all(entries: Iterable[Any]) -> str:
    """Render the complete catalog only when the user explicitly asks for it."""
    grouped = entries_by_category(entries)
    categories = _available_categories(grouped)
    lines = ["Help · All Actions (grouped)"]
    for category in categories:
        lines.extend(["", f"{category.title} [{category.key}]"])
        lines.extend(_entry_line(entry) for entry in grouped[category.key])
    lines.extend(
        [
            "",
            "Use 'help <category>' to narrow the list.",
            "Use 'help <command>' for detailed semantics and data effects.",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "HelpCategory",
    "category_key_for",
    "category_keys",
    "entries_by_category",
    "is_category",
    "render_help_all",
    "render_help_category",
    "render_help_root",
    "visible_entries",
]
