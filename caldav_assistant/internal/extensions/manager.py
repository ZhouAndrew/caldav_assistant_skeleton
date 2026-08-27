"""Extension discovery and lifecycle manager.

Frozen responsibilities implemented here:
discover -> load -> enable/disable -> reload -> unload -> error isolation.

The manager imports extension Python modules but does not duplicate command execution,
Task/Event business logic, IPC, CalDAV, or UI behavior.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
from pathlib import Path
import re
import shutil
import sys
import traceback as traceback_module
from types import ModuleType
from typing import Any, Iterable

from ...api.v1.errors import ExtensionError, NotFoundError, ValidationError
from ...api.v1.hooks import _hook_registration_scope
from ..commands.decorators import command_registration_scope
from ..commands.registry import CommandEntry
from ..commands.service import CommandService
from .hooks import HookFailure, HookRegistry


_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_ENABLED_KEY = "extensions.enabled"


@dataclass(slots=True)
class ExtensionRecord:
    name: str
    path: Path
    enabled: bool = False
    status: str = "disabled"
    error: str | None = None
    traceback: str | None = None
    module_name: str | None = None
    _command_names: tuple[str, ...] = field(default=(), repr=False)
    _replaced_commands: tuple[CommandEntry, ...] = field(default=(), repr=False)


class ExtensionManager:
    """Manage user extensions from a per-user directory."""

    def __init__(
        self,
        commands: CommandService,
        hooks: HookRegistry,
        settings: Any,
        *,
        root: str | Path | None = None,
    ) -> None:
        if not isinstance(commands, CommandService):
            raise TypeError("commands must be CommandService")
        if not isinstance(hooks, HookRegistry):
            raise TypeError("hooks must be HookRegistry")

        self.commands = commands
        self.hooks = hooks
        self.settings = settings
        self.root = Path(root) if root is not None else (
            Path.home() / ".caldav-assistant" / "extensions"
        )
        self._records: dict[str, ExtensionRecord] = {}
        self._modules: dict[str, ModuleType] = {}
        self._generation = 0
        self._manager_error: str | None = None

    # ------------------------------------------------------------------
    # Small persistence / validation bricks
    # ------------------------------------------------------------------
    @staticmethod
    def _name(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("Extension name must not be empty")
        clean = value.strip()
        if not _NAME_PATTERN.fullmatch(clean):
            raise ValidationError(
                "Extension name may contain only letters, digits, dot, underscore, "
                "and hyphen, and must start with a letter or digit"
            )
        return clean

    def _enabled_map(self) -> dict[str, bool]:
        try:
            value = self.settings.get(_ENABLED_KEY, {})
        except Exception:
            return {}
        if not isinstance(value, dict):
            return {}
        return {
            str(name): bool(enabled)
            for name, enabled in value.items()
            if isinstance(name, str)
        }

    def _set_enabled(self, name: str, enabled: bool) -> None:
        state = self._enabled_map()
        state[name] = bool(enabled)
        self.settings.set(_ENABLED_KEY, state)

    @staticmethod
    def _source_for(name: str) -> str:
        return f"extension:{name}"

    @staticmethod
    def _entry_same(left: CommandEntry, right: CommandEntry) -> bool:
        return (
            left.name.casefold() == right.name.casefold()
            and left.handler is right.handler
            and left.source == right.source
            and left.protected == right.protected
            and left.aliases == right.aliases
            and left.description == right.description
            and dict(left.metadata) == dict(right.metadata)
        )

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def _sources(self) -> dict[str, list[Path]]:
        sources: dict[str, list[Path]] = {}
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            children = sorted(self.root.iterdir(), key=lambda item: item.name.casefold())
        except OSError as exc:
            self._manager_error = f"{type(exc).__name__}: {exc}"
            return {}

        self._manager_error = None
        for child in children:
            if child.name.startswith("_") or child.name.startswith("."):
                continue

            candidate: Path | None = None
            name: str | None = None

            if child.is_file() and child.suffix == ".py":
                name = child.stem
                candidate = child
            elif child.is_dir() and (child / "__init__.py").is_file():
                name = child.name
                candidate = child

            if candidate is None or name is None:
                continue
            if not _NAME_PATTERN.fullmatch(name):
                continue

            sources.setdefault(name, []).append(candidate)

        return sources

    def discover(self) -> tuple[ExtensionRecord, ...]:
        enabled = self._enabled_map()
        sources = self._sources()
        seen: set[str] = set()

        for name, paths in sources.items():
            seen.add(name)
            previous = self._records.get(name)
            is_enabled = bool(enabled.get(name, False))

            if len(paths) > 1:
                record = previous or ExtensionRecord(name=name, path=paths[0])
                record.path = paths[0]
                record.enabled = is_enabled
                if record.status != "loaded":
                    record.status = "error"
                    record.error = "Duplicate extension sources with the same name"
                    record.traceback = None
                self._records[name] = record
                continue

            path = paths[0]
            if previous is not None and previous.path == path:
                previous.enabled = is_enabled
                if previous.status not in {"loaded", "error"}:
                    previous.status = "enabled" if is_enabled else "disabled"
                continue

            self._records[name] = ExtensionRecord(
                name=name,
                path=path,
                enabled=is_enabled,
                status="enabled" if is_enabled else "disabled",
            )

        # A loaded module remains manageable until explicitly unloaded even if its
        # file was removed.  Non-loaded vanished records can disappear from discovery.
        for name in list(self._records):
            if name in seen:
                continue
            record = self._records[name]
            if record.status != "loaded":
                del self._records[name]

        return self.list(discover=False)

    def list(self, *, discover: bool = True) -> tuple[ExtensionRecord, ...]:
        if discover:
            self.discover()
        return tuple(
            self._records[name]
            for name in sorted(self._records, key=str.casefold)
        )

    def get(self, name: str) -> ExtensionRecord:
        clean = self._name(name)
        self.discover()
        try:
            return self._records[clean]
        except KeyError as exc:
            raise NotFoundError(clean) from exc

    # ------------------------------------------------------------------
    # Transactional command ownership
    # ------------------------------------------------------------------
    def _capture_command_delta(
        self,
        before: tuple[CommandEntry, ...],
        record: ExtensionRecord,
    ) -> None:
        before_by_key = {entry.name.casefold(): entry for entry in before}
        after = self.commands.list()
        after_by_key = {entry.name.casefold(): entry for entry in after}

        changed_names: list[str] = []
        replaced: list[CommandEntry] = []

        for key, current in after_by_key.items():
            original = before_by_key.get(key)
            if original is None or not self._entry_same(current, original):
                changed_names.append(current.name)
                if original is not None:
                    replaced.append(original)

        # A plugin can explicitly replace a command under an alias in a way that
        # changes the canonical key.  Preserve any pre-load entry that vanished.
        for key, original in before_by_key.items():
            if key not in after_by_key:
                if all(
                    old.name.casefold() != original.name.casefold()
                    for old in replaced
                ):
                    replaced.append(original)

        record._command_names = tuple(changed_names)
        record._replaced_commands = tuple(replaced)

    def _remove_owned_commands(self, record: ExtensionRecord) -> None:
        owned_source = self._source_for(record.name)
        names = {name.casefold() for name in record._command_names}

        # Include source-based ownership so commands registered later by the extension
        # through ctx.commands.register_extension(...) are also removed.
        candidates = [
            entry
            for entry in self.commands.list()
            if entry.source == owned_source or entry.name.casefold() in names
        ]

        for entry in reversed(candidates):
            try:
                self.commands.unregister(
                    entry.name,
                    allow_protected=entry.protected,
                )
            except Exception:
                # Teardown must be best-effort and must not take down the Assistant.
                continue

        # Restore commands that an explicitly overriding Full API extension replaced.
        for old in record._replaced_commands:
            try:
                self.commands.register(
                    old.name,
                    old.handler,
                    source=old.source,
                    protected=old.protected,
                    aliases=old.aliases,
                    description=old.description,
                    metadata=dict(old.metadata),
                )
            except Exception:
                # Never override a newer legitimate registration during teardown.
                continue

        record._command_names = ()
        record._replaced_commands = ()

    def _teardown(self, record: ExtensionRecord) -> None:
        self._remove_owned_commands(record)
        self.hooks.unregister_owner(record.name)

        module = self._modules.pop(record.name, None)
        module_name = record.module_name
        if module_name:
            sys.modules.pop(module_name, None)
        if module is not None:
            sys.modules.pop(module.__name__, None)
        record.module_name = None

    # ------------------------------------------------------------------
    # Import / lifecycle
    # ------------------------------------------------------------------
    def _module_spec(self, record: ExtensionRecord, module_name: str):
        if record.path.is_dir():
            origin = record.path / "__init__.py"
            return importlib.util.spec_from_file_location(
                module_name,
                origin,
                submodule_search_locations=[str(record.path)],
            )
        return importlib.util.spec_from_file_location(module_name, record.path)

    def load(self, name: str) -> ExtensionRecord:
        record = self.get(name)
        if record.status == "loaded":
            return record

        if not record.path.exists():
            record.status = "error"
            record.error = "Extension source no longer exists"
            record.traceback = None
            return record

        # Clear residue from an earlier failed attempt.
        self._teardown(record)
        before = self.commands.list()
        self._generation += 1
        safe_name = re.sub(r"[^A-Za-z0-9_]", "_", record.name)
        module_name = (
            f"_caldav_assistant_extension_{safe_name}_{self._generation}"
        )

        try:
            spec = self._module_spec(record, module_name)
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot create module spec for {record.path}")

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            record.module_name = module_name

            with command_registration_scope(
                self.commands.registry,
                source=self._source_for(record.name),
            ), _hook_registration_scope(
                self.hooks,
                owner=record.name,
            ):
                spec.loader.exec_module(module)

            self._capture_command_delta(before, record)
            self._modules[record.name] = module
            record.status = "loaded"
            record.error = None
            record.traceback = None
            return record

        except Exception as exc:
            # Capture registrations made before the import failed, then roll them back.
            self._capture_command_delta(before, record)
            self._teardown(record)
            record.status = "error"
            record.error = f"{type(exc).__name__}: {exc}"
            record.traceback = traceback_module.format_exc()
            return record

    def load_enabled(self) -> tuple[ExtensionRecord, ...]:
        records = self.discover()
        loaded: list[ExtensionRecord] = []
        for record in records:
            if not record.enabled:
                continue
            # load() isolates ordinary extension exceptions and returns an error record.
            loaded.append(self.load(record.name))
        return tuple(loaded)

    def unload(self, name: str) -> ExtensionRecord:
        record = self.get(name)
        self._teardown(record)
        record.status = "enabled" if record.enabled else "disabled"
        record.error = None
        record.traceback = None
        return record

    def enable(self, name: str) -> ExtensionRecord:
        record = self.get(name)
        self._set_enabled(record.name, True)
        record.enabled = True
        if record.status != "loaded":
            record.status = "enabled"
        return self.load(record.name)

    def disable(self, name: str) -> ExtensionRecord:
        record = self.get(name)
        self._set_enabled(record.name, False)
        record.enabled = False
        self._teardown(record)
        record.status = "disabled"
        record.error = None
        record.traceback = None
        return record

    def reload(self, name: str) -> ExtensionRecord:
        record = self.get(name)
        was_enabled = record.enabled
        self._teardown(record)
        record.status = "enabled" if was_enabled else "disabled"
        return self.load(record.name)

    # ------------------------------------------------------------------
    # Installation and diagnostics
    # ------------------------------------------------------------------
    def add(self, source: str | Path) -> ExtensionRecord:
        path = Path(source).expanduser()
        if not path.exists():
            raise NotFoundError(str(path))

        if path.is_file():
            if path.suffix != ".py":
                raise ValidationError("A one-file extension must be a .py file")
            name = self._name(path.stem)
            destination = self.root / path.name
        elif path.is_dir():
            if not (path / "__init__.py").is_file():
                raise ValidationError(
                    "An extension directory must contain __init__.py"
                )
            name = self._name(path.name)
            destination = self.root / path.name
        else:
            raise ValidationError("Extension source must be a file or directory")

        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ExtensionError(str(exc)) from exc

        if destination.exists():
            raise ExtensionError(
                f"Extension {name!r} already exists at {destination}"
            )

        try:
            if path.is_dir():
                shutil.copytree(path, destination)
            else:
                shutil.copy2(path, destination)
        except OSError as exc:
            raise ExtensionError(str(exc)) from exc

        # New code is deliberately disabled until the user explicitly enables it.
        self._set_enabled(name, False)
        self.discover()
        return self.get(name)

    def errors(self) -> tuple[ExtensionRecord, ...]:
        self.discover()
        return tuple(
            record
            for record in self.list(discover=False)
            if record.status == "error" or record.error
        )

    def hook_failures(self) -> tuple[HookFailure, ...]:
        return self.hooks.failures()

    @property
    def manager_error(self) -> str | None:
        return self._manager_error


__all__ = ["ExtensionRecord", "ExtensionManager"]
