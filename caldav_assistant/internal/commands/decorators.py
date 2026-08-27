"""Decorator bridge from Easy/Extension code into the one CommandRegistry.

This module owns no command business logic.  It only supplies the registration
context required while an extension module is being imported.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterable, Iterator, Mapping

from ...api.v1.errors import ExtensionError
from .registry import CommandRegistry


_bound_registry: CommandRegistry | None = None
_active_registry: ContextVar[CommandRegistry | None] = ContextVar(
    "caldav_assistant_active_command_registry",
    default=None,
)
_active_source: ContextVar[str | None] = ContextVar(
    "caldav_assistant_active_command_source",
    default=None,
)


def bind_command_registry(registry: CommandRegistry) -> None:
    """Bind the process-local default registry used outside an import scope."""
    if not isinstance(registry, CommandRegistry):
        raise TypeError("registry must be a CommandRegistry")
    global _bound_registry
    _bound_registry = registry


@contextmanager
def command_registration_scope(
    registry: CommandRegistry,
    *,
    source: str,
) -> Iterator[None]:
    """Temporarily route ``@command`` registrations to one extension owner."""
    if not isinstance(registry, CommandRegistry):
        raise TypeError("registry must be a CommandRegistry")
    if not isinstance(source, str) or not source.strip():
        raise ExtensionError("Extension command source must not be empty")

    registry_token = _active_registry.set(registry)
    source_token = _active_source.set(source.strip())
    try:
        yield
    finally:
        _active_source.reset(source_token)
        _active_registry.reset(registry_token)


def _registration_target() -> tuple[CommandRegistry, str]:
    registry = _active_registry.get() or _bound_registry
    if registry is None:
        raise ExtensionError(
            "No CommandRegistry is bound; @command must run inside an Assistant "
            "application or ExtensionManager load scope"
        )
    return registry, (_active_source.get() or "extension")


def command(
    name: str,
    *,
    aliases: Iterable[str] | None = None,
    description: str = "",
    metadata: Mapping[str, Any] | None = None,
    override: bool = False,
    allow_protected_override: bool = False,
):
    """Register one command while preserving the frozen ``@command("name")`` API.

    Ordinary Easy extensions should leave the override flags at their safe defaults.
    Full-API code may opt in explicitly; protected core commands still require the
    registry's second explicit permission flag.
    """
    def decorate(handler):
        registry, source = _registration_target()
        registry.register(
            name,
            handler,
            source=source,
            aliases=aliases,
            description=description,
            metadata=metadata,
            override=override,
            allow_protected_override=allow_protected_override,
        )
        return handler

    return decorate


__all__ = [
    "bind_command_registry",
    "command_registration_scope",
    "command",
]
