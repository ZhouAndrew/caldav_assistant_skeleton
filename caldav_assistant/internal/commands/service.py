"""Canonical command execution service.

MODULE CONTRACT
- Imports/calls: CommandRegistry only.
- Provides: one registration/execution facade for CLI, extensions, user commands
  and future Intent/notification entry points.
- Must not: parse command lines, prompt users, swallow application exceptions,
  duplicate Task/Event business logic, or contain an if/elif dispatcher.

CommandService intentionally stays synchronous and thin.  The handler registered for
``done`` is the same action brick regardless of who invokes ``run('done', ...)``.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .registry import CommandEntry, CommandHandler, CommandRegistry


class CommandService:
    """Single application-level entry point for command registration/execution."""

    def __init__(self, registry: CommandRegistry) -> None:
        if not isinstance(registry, CommandRegistry):
            raise TypeError("registry must be a CommandRegistry")
        self.registry = registry

    # ------------------------------------------------------------------
    # Registration facade
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
        return self.registry.register(
            name,
            handler,
            source=source,
            protected=protected,
            aliases=aliases,
            description=description,
            metadata=metadata,
            override=override,
            allow_protected_override=allow_protected_override,
        )

    def register_builtin(
        self,
        name: str,
        handler: CommandHandler,
        **options: Any,
    ) -> CommandEntry:
        options.setdefault("source", "builtin")
        options.setdefault("protected", True)
        return self.register(name, handler, **options)

    def register_user(
        self,
        name: str,
        handler: CommandHandler,
        **options: Any,
    ) -> CommandEntry:
        options.setdefault("source", "user")
        return self.register(name, handler, **options)

    def register_extension(
        self,
        name: str,
        handler: CommandHandler,
        *,
        extension: str | None = None,
        **options: Any,
    ) -> CommandEntry:
        options.setdefault("source", f"extension:{extension}" if extension else "extension")
        return self.register(name, handler, **options)

    def unregister(self, name: str, *, allow_protected: bool = False) -> CommandEntry:
        return self.registry.unregister(name, allow_protected=allow_protected)

    # ------------------------------------------------------------------
    # Query facade
    # ------------------------------------------------------------------
    def get(self, name: str) -> CommandHandler:
        return self.registry.get(name)

    def resolve(self, name: str) -> CommandEntry:
        return self.registry.resolve(name)

    def list(self) -> tuple[CommandEntry, ...]:
        return self.registry.entries()

    def names(self, *, include_aliases: bool = False) -> tuple[str, ...]:
        return self.registry.names(include_aliases=include_aliases)

    # ------------------------------------------------------------------
    # Canonical execution entry point
    # ------------------------------------------------------------------
    def run(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """Resolve and invoke exactly one registered command.

        Domain/validation/extension exceptions deliberately propagate.  Presentation
        and bad-input recovery belong to CLI/Prompt/Extension boundaries, not here.
        """
        entry = self.registry.resolve(name)
        return entry.handler(*args, **kwargs)

    execute = run

    def __call__(self, name: str, *args: Any, **kwargs: Any) -> Any:
        return self.run(name, *args, **kwargs)
