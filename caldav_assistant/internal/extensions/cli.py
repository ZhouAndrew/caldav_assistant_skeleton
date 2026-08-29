"""CLI management bricks for the Extension System.

The top-level command registry still performs all resolution/execution.  The subcommand
verb table below is declarative dispatch local to one management command; it is not an
alternate application command router.

User-facing extension creation is intentionally centered on ``caldav_assistant.easy``.
ExtensionManager remains the lifecycle mechanism, not the programming model.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ...api.v1.errors import ValidationError
from ..commands.service import CommandService
from ..localization import LocaleService
from .guidance import create_easy_extension
from .manager import ExtensionManager, ExtensionRecord


_GUIDE_DEFAULT = """Extensions add features with the Python Easy API.

Start here:
  from caldav_assistant.easy import *

The important model:
  Task  = work you can start, pause, resume, and complete.
  Event = something scheduled to occur. An Event is not completed.

Small example:
  from caldav_assistant.easy import command, show, overdue_tasks

  @command(\"urgent\")
  def urgent():
      show(overdue_tasks())

Create a starter file:
  extension new NAME

Then edit the generated Python file and enable it:
  extension enable NAME

After editing an enabled extension:
  extension reload NAME

If an extension fails:
  extension errors
  extension errors NAME

Useful Easy API bricks:
  tasks(), today_tasks(), overdue_tasks(), next_task(), choose_task()
  start(task), pause(task), resume(task), complete(task), set_due(task, when)
  events(), today_events(), next_event(), choose_event()
  add_event(), edit_event(), remove_event()
  today(), agenda(), next(), remind(), notify(), write_log(), command()

Use Task lifecycle actions only with Tasks. Agenda/today/next may contain both Tasks
and Events. Advanced extensions can use caldav_assistant.api / api.v1, but ordinary
extensions should prefer Easy API."""


class ExtensionActions:
    def __init__(self, manager: ExtensionManager) -> None:
        self.manager = manager
        # Some contract tests and embedders intentionally provide only the lifecycle
        # surface. LocaleService accepts ``None`` and falls back to built-in English.
        self.locale = LocaleService(getattr(manager, "settings", None))
        self._verbs: dict[str, Callable[..., str]] = {
            "guide": self.guide,
            "new": self.new,
            "path": self.path,
            "add": self.add,
            "load": self.load,
            "enable": self.enable,
            "disable": self.disable,
            "reload": self.reload,
            "unload": self.unload,
            "errors": self.errors,
        }

    def _t(self, key: str, default: str, **values: Any) -> str:
        return self.locale.t(key, default=default, **values)

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
            return self._t(
                "extension.none",
                "No extensions found. Run 'extension guide' to learn or "
                "'extension new NAME' to create one.",
            )
        lines = [self._t("extension.list_title", "Extensions:")]
        lines.extend(f"  {self._record_line(record)}" for record in records)
        return "\n".join(lines)

    def extension(self, *parts: Any) -> str:
        if not parts:
            return self._t(
                "extension.usage",
                "Usage: extension "
                "{guide|new|path|add|load|enable|disable|reload|unload|errors} ...\n"
                "Run 'extension guide' to learn how to add a feature with Python Easy API.",
            )
        verb = str(parts[0]).strip().casefold()
        handler = self._verbs.get(verb)
        if handler is None:
            raise ValidationError(f"Unknown extension action: {parts[0]}")
        return handler(*parts[1:])

    def guide(self, *parts: Any) -> str:
        if parts:
            raise ValidationError("extension guide does not take arguments")
        return self._t("extension.guide", _GUIDE_DEFAULT)

    def new(self, *parts: Any) -> str:
        name = self._one_name(parts, "new")
        record = create_easy_extension(self.manager, name)
        return self._t(
            "extension.created",
            "Created Easy API extension {name} at {path} (disabled).\n"
            "Edit the file, then run: extension enable {name}",
            name=record.name,
            path=record.path,
        )

    def path(self, *parts: Any) -> str:
        if parts:
            raise ValidationError("extension path does not take arguments")
        return self._t(
            "extension.path",
            "Extension directory: {path}",
            path=self.manager.root,
        )

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

    def _hook_failure_lines(self, owner: str | None = None) -> list[str]:
        lines: list[str] = []
        for failure in self.manager.hook_failures():
            failure_owner = failure.owner or "unknown"
            if owner is not None and failure_owner != owner:
                continue
            lines.append(
                f"{failure_owner}: hook {failure.event}: "
                f"{failure.error_type}: {failure.message}"
            )
        return lines

    def errors(self, *parts: Any) -> str:
        if len(parts) > 1:
            raise ValidationError(
                "extension errors accepts zero arguments or one extension name"
            )

        if parts:
            name = self._one_name(parts, "errors")
            getter = getattr(self.manager, "get", None)
            if not callable(getter):
                raise ValidationError(
                    "Detailed extension diagnostics require ExtensionManager.get()"
                )
            record = getter(name)
            lines = [self._record_line(record)]
            path = getattr(record, "path", None)
            if path is not None:
                lines.append(f"Path: {path}")
            traceback = getattr(record, "traceback", None)
            if traceback:
                lines.append("Traceback:\n" + str(traceback).rstrip())
            hook_lines = self._hook_failure_lines(record.name)
            lines.extend(hook_lines)
            if not getattr(record, "error", None) and not traceback and not hook_lines:
                lines.append("No recorded extension errors.")
            return "\n".join(lines)

        lines: list[str] = []
        if self.manager.manager_error:
            lines.append(f"Manager: {self.manager.manager_error}")

        for record in self.manager.errors():
            lines.append(self._record_line(record))

        lines.extend(self._hook_failure_lines())
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
            description="Learn, create, debug, and manage Python Easy API extensions",
        )
    return actions


__all__ = ["ExtensionActions", "register_extension_cli_commands"]
