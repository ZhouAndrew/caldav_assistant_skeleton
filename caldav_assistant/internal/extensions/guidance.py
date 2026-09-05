"""User-facing Easy API extension guidance and development scaffolding.

This module does not load extensions or execute commands. It creates a typed, runnable
Python source file inside the existing per-user extension directory and can prepare a
minimal, non-destructive VS Code workspace configuration. ExtensionManager remains
responsible for discovery/lifecycle/error isolation afterwards.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from ...api.v1.errors import ExtensionError, ValidationError

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_TEMPLATE_ALIASES = {
    "full": "full",
    "detailed": "full",
    "command": "command",
    "cmd": "command",
    "task": "task",
    "task-automation": "task",
    "reminder": "reminder",
    "remind": "reminder",
    "daily": "daily",
    "daily-workflow": "daily",
    "empty": "empty",
    "minimal": "empty",
}
SIMPLE_EXTENSION_TEMPLATES = ("command", "task", "reminder", "daily", "empty")


def normalize_extension_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("Extension name must not be empty")
    clean = value.strip()
    if not _NAME_PATTERN.fullmatch(clean):
        raise ValidationError(
            "Extension name may contain only letters, digits, dot, underscore, "
            "and hyphen, and must start with a letter or digit"
        )
    return clean


def normalize_extension_template(value: Any) -> str:
    if value is None:
        return "full"
    clean = str(value).strip().casefold().replace("_", "-")
    template = _TEMPLATE_ALIASES.get(clean)
    if template is None:
        choices = ", ".join(SIMPLE_EXTENSION_TEMPLATES)
        raise ValidationError(f"Unknown extension template {value!r}; choose: {choices}")
    return template


def _small_template(name: str, template: str) -> str:
    """Return one intentionally small, runnable Easy API starter."""
    if template == "command":
        return f'''"""Small command extension created by CalDAV Assistant."""
from caldav_assistant.easy import command, show


@command({name!r})
def run() -> None:
    show("Hello from {name}")
'''

    if template == "task":
        return f'''"""Small Task automation extension created by CalDAV Assistant."""
from caldav_assistant.easy import choose_task, command, start, show


@command({name!r})
def run() -> None:
    task = choose_task()
    if task is not None:
        show(start(task))
'''

    if template == "reminder":
        return f'''"""Small reminder extension created by CalDAV Assistant."""
from caldav_assistant.easy import ask_datetime, command, remind, show


@command({name!r})
def run() -> None:
    when = ask_datetime("When should I remind you?")
    if when is not None:
        show(remind("{name}", when))
'''

    if template == "daily":
        return f'''"""Small daily-workflow extension created by CalDAV Assistant."""
from caldav_assistant.easy import command, show, today


@command({name!r})
def run() -> None:
    show(today())
'''

    if template == "empty":
        return f'''"""Minimal Easy API extension created by CalDAV Assistant."""
from caldav_assistant.easy import command


@command({name!r})
def run() -> None:
    pass
'''

    raise ValidationError(f"Unsupported small extension template: {template}")


def easy_extension_template(name: str, template: str = "full") -> str:
    """Return a runnable extension based only on the frozen public Easy API.

    ``full`` preserves the long-standing teaching template. The other templates are
    deliberately small so a new user can create one useful feature without first
    deleting a page of examples.
    """
    clean = normalize_extension_name(name)
    kind = normalize_extension_template(template)
    if kind != "full":
        return _small_template(clean, kind)

    return f'''"""CalDAV Assistant Easy API extension: {clean}.

This is a working template, not a tiny placeholder. Keep the examples you need and
delete the rest.

Core model:
- Task = work that can be started, paused, resumed, and completed.
- Event = something scheduled to occur; Events do NOT have a completion lifecycle.
- CalDAV remains the Task/Event source of truth. Do not edit XML or SQLite directly.
- Prefer caldav_assistant.easy. Use api/api.v1 only when Easy API is insufficient.

Extension lifecycle:
  extension enable {clean}
  extension reload {clean}
  extension errors {clean}

Editor support:
  extension dev

The installed caldav-assistant package ships PEP 561 type information (py.typed plus
Easy API stubs), so VS Code/Pylance can autocomplete imports, show signatures, and catch
Task/Event type mistakes when the correct Python interpreter is selected.
"""
from __future__ import annotations

from caldav_assistant.api import Agenda
from caldav_assistant.easy import (
    ask_date,
    choose,
    choose_task,
    command,
    complete,
    confirm,
    overdue_tasks,
    set_due,
    show,
    start,
    today,
    today_events,
    today_tasks,
    write_log,
)


_MENU = (
    "Today's agenda",
    "Today's tasks",
    "Overdue tasks",
    "Today's events",
    "Start a task",
    "Complete a task",
    "Change a task due date",
    "Log a selected task",
)


def _selected_task():
    """Reusable PromptKit/Easy-API brick; None means the user cancelled."""
    return choose_task()


def _show_today() -> None:
    items: Agenda = today()
    show(items)


def _start_task() -> None:
    task = _selected_task()
    if task is not None:
        show(start(task))


def _complete_task() -> None:
    task = _selected_task()
    if task is not None and confirm(f"Complete {{task.summary}}?"):
        show(complete(task))


def _change_due() -> None:
    task = _selected_task()
    if task is None:
        return
    due = ask_date("New due date")
    if due is not None:
        show(set_due(task, due))


def _log_selected_task() -> None:
    task = _selected_task()
    if task is None:
        return
    if confirm(f"Write a long-term log entry for {{task.summary}}?", default=False):
        # WordPress/Outbox is a long-term record path; it does not decide Task state.
        show(write_log(f"Work note: {{task.summary}}"))


@command({clean!r})
def run() -> None:
    """Open a small Scratch-like menu assembled entirely from public Easy API bricks."""
    action = choose(_MENU, title="{clean}")
    if action is None:
        return

    if action == "Today's agenda":
        _show_today()
    elif action == "Today's tasks":
        show(today_tasks())
    elif action == "Overdue tasks":
        show(overdue_tasks())
    elif action == "Today's events":
        # Events are calendar occurrences. Do not call complete()/start() on an Event.
        show(today_events())
    elif action == "Start a task":
        _start_task()
    elif action == "Complete a task":
        _complete_task()
    elif action == "Change a task due date":
        _change_due()
    elif action == "Log a selected task":
        _log_selected_task()
'''


def create_easy_extension(manager: Any, name: str, template: str = "full"):
    """Create a disabled one-file Easy API extension in ``manager.root``.

    The file is deliberately not auto-enabled. New executable code must still pass
    through the existing explicit ``extension enable NAME`` lifecycle step. Any stale
    enablement value from a previously deleted extension with the same name is cleared
    before the new source becomes discoverable.
    """
    clean = normalize_extension_name(name)
    kind = normalize_extension_template(template)
    registry = getattr(getattr(manager, "commands", None), "registry", None)
    contains = getattr(registry, "contains", None)
    if callable(contains) and contains(clean):
        raise ExtensionError(
            f"Command {clean!r} already exists; choose a different extension name"
        )

    root = Path(manager.root)
    destination = root / f"{clean}.py"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ExtensionError(str(exc)) from exc

    if destination.exists():
        raise ExtensionError(
            f"Extension {clean!r} already exists at {destination}"
        )

    set_enabled = getattr(manager, "_set_enabled", None)
    if not callable(set_enabled):
        raise ExtensionError("Extension manager cannot persist disabled state")
    set_enabled(clean, False)

    try:
        destination.write_text(
            easy_extension_template(clean, kind),
            encoding="utf-8",
        )
    except OSError as exc:
        raise ExtensionError(str(exc)) from exc

    manager.discover()
    return manager.get(clean)


def ensure_vscode_workspace(manager: Any) -> tuple[Path, bool]:
    """Create recommended VS Code/Pylance settings without overwriting user config."""
    root = Path(manager.root)
    settings_path = root / ".vscode" / "settings.json"
    try:
        root.mkdir(parents=True, exist_ok=True)
        settings_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ExtensionError(str(exc)) from exc

    if settings_path.exists():
        return settings_path, False

    settings = {
        "python.analysis.typeCheckingMode": "basic",
        "python.analysis.autoImportCompletions": True,
    }
    try:
        settings_path.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise ExtensionError(str(exc)) from exc
    return settings_path, True


__all__ = [
    "SIMPLE_EXTENSION_TEMPLATES",
    "normalize_extension_name",
    "normalize_extension_template",
    "easy_extension_template",
    "create_easy_extension",
    "ensure_vscode_workspace",
]
