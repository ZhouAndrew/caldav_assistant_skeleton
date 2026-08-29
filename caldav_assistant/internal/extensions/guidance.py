"""User-facing Easy API extension guidance and development scaffolding.

This module does not load extensions or execute commands.  It creates a typed, runnable
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


def easy_extension_template(name: str) -> str:
    """Return a detailed, runnable one-file extension based only on frozen Easy API."""
    clean = normalize_extension_name(name)
    return f'''"""CalDAV Assistant Easy API extension: {clean}.

This file is intentionally a real working template rather than a tiny placeholder.
Delete the examples you do not need and keep the pieces that match your extension.

Core model:
- Task = work that can be started, paused, resumed, and completed.
- Event = something scheduled to occur; Events do NOT have a completion lifecycle.
- CalDAV remains the Task/Event source of truth. Do not edit XML or SQLite directly.
- Prefer caldav_assistant.easy. Use api/api.v1 only when Easy API is insufficient.

Useful lifecycle commands after editing this file:
  extension enable {clean}
  extension reload {clean}
  extension errors {clean}

VS Code/Pylance setup:
  extension dev

The package ships py.typed + Easy API stubs, so the normal Python interpreter where
caldav-assistant is installed can provide autocomplete and type checking.
"""
from __future__ import annotations

from caldav_assistant.easy import (
    ask_date,
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


USAGE = """{clean} commands:
  {clean}                 Show today's combined agenda
  {clean} tasks           Show today's Tasks only
  {clean} overdue         Show overdue Tasks
  {clean} events          Show today's Events only
  {clean} start           Choose a Task and start working on it
  {clean} complete        Choose a Task and mark it complete after confirmation
  {clean} due             Choose a Task and change its due date
  {clean} log TEXT...     Write long-term text through the WordPress/Outbox service
  {clean} help            Show this help
"""


def _choose_required_task():
    """Reusable prompt brick: return a chosen Task, or None if the user cancels."""
    return choose_task()


@command(
    {clean!r},
    description="Example Easy API extension with Task, Event, prompt, date, and log bricks.",
)
def run(*parts: str) -> None:
    """One command demonstrating safe composition of Easy API bricks.

    Extension commands receive CLI words as normal Python arguments.  This example uses
    a small local action table style without creating another application-wide command
    dispatcher.  Every data-changing operation still goes through the public Easy API.
    """
    action = parts[0].casefold() if parts else "today"

    if action == "today":
        show(today())
        return

    if action == "tasks":
        show(today_tasks())
        return

    if action == "overdue":
        show(overdue_tasks())
        return

    if action == "events":
        # Events are displayed/edited as calendar occurrences. Do not call complete().
        show(today_events())
        return

    if action == "start":
        task = _choose_required_task()
        if task is not None:
            show(start(task))
        return

    if action == "complete":
        task = _choose_required_task()
        if task is not None and confirm(f"Complete {{task.summary}}?"):
            show(complete(task))
        return

    if action == "due":
        task = _choose_required_task()
        if task is None:
            return
        due = ask_date("New due date")
        if due is not None:
            show(set_due(task, due))
        return

    if action == "log":
        text = " ".join(parts[1:]).strip()
        if not text:
            show("Usage: {clean} log TEXT...")
            return
        # write_log() uses the normal WordPress/Outbox path; it does not change Task state.
        show(write_log(text))
        return

    if action in {{"help", "?"}}:
        show(USAGE)
        return

    show(f"Unsupported extension action: {{parts[0]}}\n\n{{USAGE}}")
'''


def create_easy_extension(manager: Any, name: str):
    """Create a disabled one-file Easy API extension in ``manager.root``.

    The file is deliberately not auto-enabled. New executable code must still pass
    through the existing explicit ``extension enable NAME`` lifecycle step. Any stale
    enablement value from a previously deleted extension with the same name is cleared
    before the new source becomes discoverable.
    """
    clean = normalize_extension_name(name)
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
        destination.write_text(easy_extension_template(clean), encoding="utf-8")
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
    "normalize_extension_name",
    "easy_extension_template",
    "create_easy_extension",
    "ensure_vscode_workspace",
]
