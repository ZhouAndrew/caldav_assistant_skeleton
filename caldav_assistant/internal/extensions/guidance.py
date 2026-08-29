"""User-facing Easy API extension guidance and one-file scaffolding.

This module does not load extensions or execute commands.  It only creates a small
Python source file inside the existing per-user extension directory.  ExtensionManager
remains responsible for discovery/lifecycle/error isolation afterwards.
"""
from __future__ import annotations

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
    """Return the smallest useful one-file extension based on the frozen Easy API."""
    clean = normalize_extension_name(name)
    return f'''"""CalDAV Assistant Easy API extension: {clean}.

Task = work that can be started, paused, resumed, and completed.
Event = something scheduled to occur; Events do not have a completion lifecycle.
"""
from caldav_assistant.easy import command, show, today


@command({clean!r})
def run():
    show(today())
'''


def create_easy_extension(manager: Any, name: str):
    """Create a disabled one-file Easy API extension in ``manager.root``.

    The file is deliberately not auto-enabled.  New executable code must still pass
    through the existing explicit ``extension enable NAME`` lifecycle step.  Any stale
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

    # This is an internal package and deliberately reuses ExtensionManager's canonical
    # persistence brick rather than duplicating the extensions.enabled settings format.
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


__all__ = [
    "normalize_extension_name",
    "easy_extension_template",
    "create_easy_extension",
]
