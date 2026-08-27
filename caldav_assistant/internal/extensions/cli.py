"""CLI management bricks for the Extension System.

The top-level command registry still performs all resolution/execution.  The subcommand
verb table below is declarative dispatch local to one management command; it is not an
alternate application command router.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ...api.v1.errors import ValidationError
from ..commands.service import CommandService
from .manager import ExtensionManager, ExtensionRecord


class ExtensionActions:
    def __init__(self, manager: ExtensionManager) -> None:
        self.manager = manager
        self._verbs: dict[str, Callable[..., str]] = {
            "add": self.add,
            "load": self.load,
            "enable": self.enable,
            "disable": self.disable,
            "reload": self.reload,
            "unload": self.unload,
            "errors": self.errors,
        }

    @staticmethod
    def _record_line(record: ExtensionRecord) -> str:
        state = record.status
        if record.enabled and state == "disabled":
            state = "enabled"
        suffix = f" — {record.error}" if record.error else ""
        return f"{record.name}: {state}{suffix}"

    def extensions(self, *parts: Any) -> str:
        if parts:
            raise ValidationError("extensions does not take arguments")
        records = self.manager.list()
        if not records:
            return "No extensions found. Add one with: extension add FILE"
        lines = ["Extensions:"]
        lines.extend(f"  {self._record_line(record)}" for record in records)
        return "\n".join(lines)

    def extension(self, *parts: Any) -> str:
        if not parts:
            return (
                "Usage: extension "
                "{add|load|enable|disable|reload|unload|errors} ..."
            )
        verb = str(parts[0]).strip().casefold()
        handler = self._verbs.get(verb)
        if handler is None:
            raise ValidationError(f"Unknown extension action: {parts[0]}")
        return handler(*parts[1:])

    @staticmethod
    def _one_name(parts: tuple[Any, ...], action: str) -> str:
        if len(parts) != 1 or not isinstance(parts[0], str):
            raise ValidationError(f"extension {action} requires one extension name")
        return parts[0]

    def add(self, *parts: Any) -> str:
        if len(parts) != 1 or not isinstance(parts[0], str):
            raise ValidationError("extension add requires one file or directory path")
        record = self.manager.add(Path(parts[0]))
        return (
            f"Added {record.name} (disabled). "
            f"Enable with: extension enable {record.name}"
        )

    def load(self, *parts: Any) -> str:
        name = self._one_name(parts, "load")
        return self._record_line(self.manager.load(name))

    def enable(self, *parts: Any) -> str:
        name = self._one_name(parts, "enable")
        return self._record_line(self.manager.enable(name))

    def disable(self, *parts: Any) -> str:
        name = self._one_name(parts, "disable")
        return self._record_line(self.manager.disable(name))

    def reload(self, *parts: Any) -> str:
        name = self._one_name(parts, "reload")
        return self._record_line(self.manager.reload(name))

    def unload(self, *parts: Any) -> str:
        name = self._one_name(parts, "unload")
        return self._record_line(self.manager.unload(name))

    def errors(self, *parts: Any) -> str:
        if parts:
            raise ValidationError("extension errors does not take arguments")

        lines: list[str] = []
        if self.manager.manager_error:
            lines.append(f"Manager: {self.manager.manager_error}")

        for record in self.manager.errors():
            lines.append(self._record_line(record))

        for failure in self.manager.hook_failures():
            owner = failure.owner or "unknown"
            lines.append(
                f"{owner}: hook {failure.event}: "
                f"{failure.error_type}: {failure.message}"
            )

        return "\n".join(lines) if lines else "No extension errors."


def register_extension_cli_commands(
    commands: CommandService,
    manager: ExtensionManager,
) -> ExtensionActions:
    actions = ExtensionActions(manager)

    registry = commands.registry
    if not registry.contains("extensions"):
        commands.register_builtin(
            "extensions",
            actions.extensions,
            description="List discovered extensions",
        )
    if not registry.contains("extension"):
        commands.register_builtin(
            "extension",
            actions.extension,
            description="Manage extensions",
        )
    return actions


__all__ = ["ExtensionActions", "register_extension_cli_commands"]
