"""Canonical command registry for built-in, user and extension commands.

MODULE CONTRACT
- Imports/calls: stdlib + stable public v1 errors only.
- Provides: CommandEntry and CommandRegistry.
- Must not: parse CLI text, prompt the user, call Task/Event services, load plugins,
  or contain a command dispatcher made of if/elif branches.

All command producers share this one registry.  Name conflicts are explicit; a
registration never silently replaces an existing command or alias.  Protected
canonical commands require a second explicit opt-in before replacement/removal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping
import unicodedata

from ...api.v1.errors import ConflictError, NotFoundError, ValidationError


CommandHandler = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class CommandEntry:
    """Immutable description of one canonical registered command."""

    name: str
    handler: CommandHandler = field(repr=False, compare=False)
    source: str = "unknown"
    protected: bool = False
    aliases: tuple[str, ...] = ()
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Prevent callers from mutating registry-owned metadata through an entry.
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class CommandRegistry:
    """Thread-safe registry shared by built-ins, user commands and extensions."""

    def __init__(self) -> None:
        self._entries: dict[str, CommandEntry] = {}
        self._aliases: dict[str, str] = {}
        self._lock = RLock()

    # ------------------------------------------------------------------
    # Normalization / validation bricks
    # ------------------------------------------------------------------
    @staticmethod
    def _name(value: Any, *, label: str = "Command name") -> tuple[str, str]:
        if not isinstance(value, str):
            raise ValidationError(f"{label} must be text")

        display = unicodedata.normalize("NFKC", value).strip()
        if not display:
            raise ValidationError(f"{label} must not be empty")
        if any(char.isspace() for char in display):
            raise ValidationError(f"{label} must be a single token")
        if any(unicodedata.category(char).startswith("C") for char in display):
            raise ValidationError(f"{label} contains control characters")

        return display, display.casefold()

    @classmethod
    def _aliases_value(cls, aliases: Iterable[str] | None, canonical_key: str) -> tuple[tuple[str, str], ...]:
        if aliases is None:
            return ()
        if isinstance(aliases, str):
            raise ValidationError("aliases must be an iterable of command names")

        result: list[tuple[str, str]] = []
        seen: set[str] = set()
        for raw in aliases:
            display, key = cls._name(raw, label="Command alias")
            if key == canonical_key:
                raise ValidationError("Command alias duplicates the canonical name")
            if key in seen:
                raise ValidationError(f"Duplicate command alias: {display}")
            seen.add(key)
            result.append((display, key))
        return tuple(result)

    @staticmethod
    def _source(value: Any) -> str:
        if value is None:
            return "unknown"
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("Command source must be non-empty text")
        return value.strip()

    def _canonical_key_for_locked(self, key: str) -> str | None:
        if key in self._entries:
            return key
        return self._aliases.get(key)

    def _entry_for_key_locked(self, key: str) -> CommandEntry | None:
        canonical = self._canonical_key_for_locked(key)
        return None if canonical is None else self._entries[canonical]

    @staticmethod
    def _conflict_message(name: str, existing: CommandEntry) -> str:
        return f"Command {name!r} already exists (canonical: {existing.name!r})"

    # ------------------------------------------------------------------
    # Registry operations
    # ------------------------------------------------------------------
    def register(
        self,
        name: str,
        handler: CommandHandler,
        *,
        source: str = "unknown",
        protected: bool = False,
        aliases: Iterable[str] | None = None,
        description: str = "",
        metadata: Mapping[str, Any] | None = None,
        override: bool = False,
        allow_protected_override: bool = False,
    ) -> CommandEntry:
        """Register one canonical command atomically.

        ``override=True`` is the explicit Full-API escape hatch for replacing an
        ordinary command.  A protected command requires both ``override=True`` and
        ``allow_protected_override=True`` so core canonical names cannot be replaced
        accidentally by a plugin or user command.
        """
        display_name, key = self._name(name)
        if not callable(handler):
            raise ValidationError("Command handler must be callable")

        normalized_aliases = self._aliases_value(aliases, key)
        normalized_source = self._source(source)
        if not isinstance(description, str):
            raise ValidationError("Command description must be text")
        if metadata is not None and not isinstance(metadata, Mapping):
            raise ValidationError("Command metadata must be a mapping")

        with self._lock:
            existing = self._entry_for_key_locked(key)
            if existing is not None:
                if not override:
                    raise ConflictError(self._conflict_message(display_name, existing))
                if existing.protected and not allow_protected_override:
                    raise ConflictError(
                        f"Protected command {existing.name!r} cannot be overridden without explicit permission"
                    )

            # Every alias participates in the same namespace as canonical names.
            # Validate the entire registration before mutating anything.
            replacement_key = None
            if existing is not None:
                replacement_key = self._canonical_key_for_locked(key)

            for alias_display, alias_key in normalized_aliases:
                alias_existing = self._entry_for_key_locked(alias_key)
                if alias_existing is None:
                    continue
                alias_existing_key = self._canonical_key_for_locked(alias_key)
                if replacement_key is not None and alias_existing_key == replacement_key:
                    # Re-registering the same command with a new alias set is fine.
                    continue
                raise ConflictError(self._conflict_message(alias_display, alias_existing))

            if replacement_key is not None:
                old = self._entries.pop(replacement_key)
                for old_alias in old.aliases:
                    _, old_alias_key = self._name(old_alias, label="Command alias")
                    self._aliases.pop(old_alias_key, None)

            entry = CommandEntry(
                name=display_name,
                handler=handler,
                source=normalized_source,
                protected=bool(protected),
                aliases=tuple(display for display, _ in normalized_aliases),
                description=description.strip(),
                metadata=dict(metadata or {}),
            )
            self._entries[key] = entry
            for _, alias_key in normalized_aliases:
                self._aliases[alias_key] = key
            return entry

    def unregister(
        self,
        name: str,
        *,
        allow_protected: bool = False,
    ) -> CommandEntry:
        display, key = self._name(name)
        with self._lock:
            canonical = self._canonical_key_for_locked(key)
            if canonical is None:
                raise NotFoundError(display)
            entry = self._entries[canonical]
            if entry.protected and not allow_protected:
                raise ConflictError(f"Protected command {entry.name!r} cannot be removed")

            del self._entries[canonical]
            for alias in entry.aliases:
                _, alias_key = self._name(alias, label="Command alias")
                self._aliases.pop(alias_key, None)
            return entry

    def get_entry(self, name: str) -> CommandEntry:
        display, key = self._name(name)
        with self._lock:
            entry = self._entry_for_key_locked(key)
            if entry is None:
                raise NotFoundError(display)
            return entry

    def get(self, name: str) -> CommandHandler:
        """Backward-compatible handler lookup used by the original scaffold."""
        return self.get_entry(name).handler

    resolve = get_entry

    def contains(self, name: str) -> bool:
        try:
            _, key = self._name(name)
        except ValidationError:
            return False
        with self._lock:
            return self._canonical_key_for_locked(key) is not None

    def entries(self) -> tuple[CommandEntry, ...]:
        """Return a stable registration-order snapshot of canonical commands."""
        with self._lock:
            return tuple(self._entries.values())

    def names(self, *, include_aliases: bool = False) -> tuple[str, ...]:
        with self._lock:
            names = [entry.name for entry in self._entries.values()]
            if include_aliases:
                for entry in self._entries.values():
                    names.extend(entry.aliases)
            return tuple(names)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and self.contains(name)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
