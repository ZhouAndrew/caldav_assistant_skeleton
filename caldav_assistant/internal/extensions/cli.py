"""CLI management bricks for the Extension System.

The top-level command registry still performs all resolution/execution.  The subcommand
verb table below is declarative dispatch local to one management command; it is not an
alternate application command router.

User-facing extension creation is intentionally centered on ``caldav_assistant.easy``.
Official bundled extensions use the exact same ExtensionManager lifecycle; this module
only makes their origin, defaults, and read-only source ownership explicit to humans.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ...api.v1.errors import ValidationError
from ...builtin_extensions._catalog import OFFICIAL_EXTENSION_CATALOG
from ..commands.service import CommandService
from ..localization import LocaleService
from .guidance import create_easy_extension, ensure_vscode_workspace
from .manager import ExtensionManager, ExtensionRecord


_GUIDE_DEFAULT = """Extensions add features with the Python Easy API.

Start here:
  from caldav_assistant.easy import command, show, overdue_tasks

The important model:
  Task  = work you can start, pause, resume, and complete.
  Event = something scheduled to occur. An Event is not completed.

Small example:
  @command(\"urgent\")
  def urgent() -> None:
      show(overdue_tasks())

Create a starter file:
  extension new NAME

Prepare the extension directory for VS Code/Pylance:
  extension dev

The installed package includes PEP 561 typing, an Easy API stub, and typed Object API
Protocols. Select the Python interpreter where caldav-assistant is installed and VS
Code can autocomplete imports, show signatures, and type-check Task/Event usage.

Official bundled extensions:
  extension official
  extension info NAME
  extension enable|disable NAME
  extension reset NAME

After editing an enabled user extension:
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
        self.locale = LocaleService(getattr(manager, "settings", None))
        self._verbs: dict[str, Callable[..., str]] = {
            "guide": self.guide,
            "new": self.new,
            "dev": self.dev,
            "path": self.path,
            "official": self.official,
            "user": self.user,
            "info": self.info,
            "reset": self.reset,
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

    def _is_official(self, record: ExtensionRecord) -> bool:
        if record.name in OFFICIAL_EXTENSION_CATALOG:
            return True
        root = getattr(self.manager, "bundled_root", None)
        if root is None:
            return False
        try:
            return record.path.resolve().is_relative_to(Path(root).resolve())
        except (OSError, RuntimeError, ValueError):
            return False

    def _origin(self, record: ExtensionRecord) -> str:
        return "official" if self._is_official(record) else "user"

    def _record_line(self, record: ExtensionRecord) -> str:
        state = record.status
        if record.enabled and state == "disabled":
            state = "enabled"
        suffix = f" — {record.error}" if record.error else ""
        origin = self._t(
            "extension.origin.official" if self._is_official(record) else "extension.origin.user",
            "official" if self._is_official(record) else "user",
        )
        # Preserve the long-standing `name: state` prefix used by scripts/tests;
        # source information is additive metadata rather than a breaking prefix.
        return f"{record.name}: {state} [{origin}]{suffix}"

    def _group(self, title: str, records: list[ExtensionRecord], empty: str) -> list[str]:
        lines = [title]
        if not records:
            lines.append(f"  {empty}")
        else:
            lines.extend(f"  {self._record_line(record)}" for record in records)
        return lines

    def extensions(self, *parts: Any) -> str:
        if parts:
            raise ValidationError("extensions does not take arguments")
        records = list(self.manager.list())
        if not records:
            return self._t(
                "extension.none",
                "No extensions found. Run 'extension guide' to learn or "
                "'extension new NAME' to create one.",
            )
        official = [record for record in records if self._is_official(record)]
        user = [record for record in records if not self._is_official(record)]
        lines = [self._t("extension.list_title", "Extensions:")]
        lines.extend(
            self._group(
                self._t("extension.official_title", "Official bundled extensions:"),
                official,
                self._t("extension.none_official", "none"),
            )
        )
        lines.extend(
            self._group(
                self._t("extension.user_title", "User extensions:"),
                user,
                self._t("extension.none_user", "none"),
            )
        )
        lines.append(
            self._t(
                "extension.list_hint",
                "Manage with: extension info NAME | enable/disable/reload NAME",
            )
        )
        return "\n".join(lines)

    def extension(self, *parts: Any) -> str:
        if not parts:
            return self._t(
                "extension.usage",
                "Usage: extension "
                "{guide|new|dev|path|official|user|info|reset|add|load|enable|disable|reload|unload|errors} ...\n"
                "Run 'extension guide' for Easy API and VS Code development help.",
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
            "Created typed Easy API extension {name} at {path} (disabled).\n"
            "For VS Code support run: extension dev\n"
            "Then enable it with: extension enable {name}",
            name=record.name,
            path=record.path,
        )

    def dev(self, *parts: Any) -> str:
        if parts:
            raise ValidationError("extension dev does not take arguments")
        settings_path, created = ensure_vscode_workspace(self.manager)
        state = self._t(
            "extension.dev_created" if created else "extension.dev_existing",
            "created" if created else "already existed; left unchanged",
        )
        return self._t(
            "extension.dev",
            "VS Code extension workspace: {root}\n"
            "Pylance settings: {settings} ({state})\n"
            "Open that directory in VS Code, then select the Python interpreter where "
            "caldav-assistant is installed. The package ships py.typed + Easy API stubs "
            "for autocomplete and type checking.",
            root=self.manager.root,
            settings=settings_path,
            state=state,
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

    def official(self, *parts: Any) -> str:
        if parts:
            raise ValidationError("extension official does not take arguments")
        records = [record for record in self.manager.list() if self._is_official(record)]
        lines = self._group(
            self._t("extension.official_title", "Official bundled extensions:"),
            records,
            self._t("extension.none_official", "none"),
        )
        lines.append(
            self._t(
                "extension.official_hint",
                "Official source code is shipped with the app. You can enable, disable, "
                "reload, inspect errors, or reset an official extension to its default state.",
            )
        )
        return "\n".join(lines)

    def user(self, *parts: Any) -> str:
        if parts:
            raise ValidationError("extension user does not take arguments")
        records = [record for record in self.manager.list() if not self._is_official(record)]
        return "\n".join(
            self._group(
                self._t("extension.user_title", "User extensions:"),
                records,
                self._t("extension.none_user", "none"),
            )
        )

    def info(self, *parts: Any) -> str:
        name = self._one_name(parts, "info")
        record = self.manager.get(name)
        official = self._is_official(record)
        metadata = OFFICIAL_EXTENSION_CATALOG.get(record.name, {}) if official else {}
        origin = self._t(
            "extension.origin.official_long" if official else "extension.origin.user_long",
            "Official (bundled with CalDAV Assistant)" if official else "User extension",
        )
        lines = [
            f"Name: {record.name}",
            f"Origin: {origin}",
            f"Status: {record.status}",
            f"Enabled: {'yes' if record.enabled else 'no'}",
            f"Path: {record.path}",
        ]
        title = metadata.get("title") if hasattr(metadata, "get") else None
        description = metadata.get("description") if hasattr(metadata, "get") else None
        if title:
            lines.insert(1, f"Title: {title}")
        if description:
            lines.append(f"Description: {description}")
        if official:
            default = bool(metadata.get("default_enabled", record.name in self.manager.default_enabled))
            lines.append(f"Default: {'enabled' if default else 'disabled'}")
            lines.append(
                self._t(
                    "extension.official_source_note",
                    "Official source is managed by application updates; manage its lifecycle "
                    "with enable/disable/reload/reset instead of editing the bundled file.",
                )
            )
        else:
            lines.append(
                self._t(
                    "extension.user_source_note",
                    "User source is yours to edit. Run `extension dev` for VS Code/Pylance setup.",
                )
            )
        return "\n".join(lines)

    def reset(self, *parts: Any) -> str:
        name = self._one_name(parts, "reset")
        record = self.manager.get(name)
        if not self._is_official(record):
            raise ValidationError("extension reset is only for official bundled extensions")
        metadata = OFFICIAL_EXTENSION_CATALOG.get(record.name, {})
        default_enabled = bool(
            metadata.get("default_enabled", record.name in self.manager.default_enabled)
            if hasattr(metadata, "get")
            else record.name in self.manager.default_enabled
        )
        updated = self.manager.enable(record.name) if default_enabled else self.manager.disable(record.name)
        return self._t(
            "extension.reset_done",
            "Reset official extension to packaged default → {record}",
            record=self._record_line(updated),
        )

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
            description="List official bundled and user extensions",
        )
    if not registry.contains("extension"):
        commands.register_builtin(
            "extension",
            actions.extension,
            description=(
                "Manage official/user extensions and prepare typed Easy API development"
            ),
        )
    return actions


__all__ = ["ExtensionActions", "register_extension_cli_commands"]
