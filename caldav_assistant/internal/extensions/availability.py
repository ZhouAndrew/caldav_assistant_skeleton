"""Presentation-only lookup for commands supplied by official extensions.

The command registry remains the source of truth for commands that are available now.
This helper answers the separate UX question: is an unresolved command known/supported
by a bundled extension but currently unavailable because that extension is disabled or
failed to load?
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...api.v1.errors import NotFoundError
from ...builtin_extensions._catalog import OFFICIAL_EXTENSION_CATALOG


@dataclass(frozen=True, slots=True)
class ExtensionCommandSupport:
    command: str
    extension: str
    enabled: bool
    status: str


def find_extension_command_support(manager: Any, name: str) -> ExtensionCommandSupport | None:
    """Return packaged support metadata for a command not found in the live registry."""
    if manager is None or not isinstance(name, str) or not name.strip():
        return None
    key = name.strip().casefold()

    for extension_name, metadata in OFFICIAL_EXTENSION_CATALOG.items():
        commands = metadata.get("commands", ()) if hasattr(metadata, "get") else ()
        for command_meta in commands:
            canonical = str(command_meta.get("name", "")).strip()
            aliases = tuple(str(item).strip() for item in command_meta.get("aliases", ()))
            names = (canonical, *aliases)
            if key not in {candidate.casefold() for candidate in names if candidate}:
                continue

            try:
                record = manager.get(extension_name)
            except (NotFoundError, AttributeError):
                return ExtensionCommandSupport(
                    command=canonical or name.strip(),
                    extension=extension_name,
                    enabled=False,
                    status="missing",
                )
            return ExtensionCommandSupport(
                command=canonical or name.strip(),
                extension=extension_name,
                enabled=bool(getattr(record, "enabled", False)),
                status=str(getattr(record, "status", "unknown")),
            )
    return None


__all__ = ["ExtensionCommandSupport", "find_extension_command_support"]
