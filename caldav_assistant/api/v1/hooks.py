"""Stable v1 hook decorator and synchronous Hook/Event API.

The Extension System keeps ownership-aware registration while an extension is
being imported. Outside that scope, the same public ``@on(...)`` decorator falls
back to the process EventBus. Advanced EventBus options (priority/once/bus) are
also supported without exposing internal registries.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from .errors import ExtensionError, ValidationError
from ...internal.hook_event import (
    EventBus,
    HookDispatchReport,
    HookEvent,
    HookFailure,
    HookHandle,
    emit,
    get_event_bus,
    off,
    on as _event_bus_on,
    unregister_owner,
)


_bound_registrar: Any = None
_active_registrar: ContextVar[Any] = ContextVar(
    "caldav_assistant_active_hook_registrar",
    default=None,
)
_active_owner: ContextVar[str | None] = ContextVar(
    "caldav_assistant_active_hook_owner",
    default=None,
)


def _bind_hook_registrar(registrar: Any) -> None:
    """Bind the Extension System registrar for the current process."""
    global _bound_registrar
    _bound_registrar = registrar


@contextmanager
def _hook_registration_scope(
    registrar: Any,
    *,
    owner: str,
) -> Iterator[None]:
    """Temporarily bind one extension owner while its module is imported."""
    if registrar is None:
        raise ExtensionError("Hook registrar is required")
    if not isinstance(owner, str) or not owner.strip():
        raise ExtensionError("Hook owner must not be empty")

    registrar_token = _active_registrar.set(registrar)
    owner_token = _active_owner.set(owner.strip())
    try:
        yield
    finally:
        _active_owner.reset(owner_token)
        _active_registrar.reset(registrar_token)


def _register_hook(registrar: Any, event: str, handler: Any, owner: str | None):
    register = getattr(registrar, "register", None)
    if callable(register):
        return register(event, handler, owner=owner)
    if callable(registrar):
        # Backward-compatible tiny registrar callback.
        return registrar(event, handler)
    raise ExtensionError("No usable hook registrar is bound")


def on(
    event: str,
    *,
    priority: int = 0,
    once: bool = False,
    owner: str | None = None,
    bus: EventBus | None = None,
):
    """Register a Full API hook without exposing internal hook registries.

    During ExtensionManager import, the frozen owner-aware Extension HookRegistry
    remains authoritative so disable/reload/unload can remove that extension's
    handlers. Otherwise registration uses the synchronous EventBus v1 API.
    """
    if not isinstance(event, str) or not event.strip():
        raise ValidationError("Hook event must not be empty")
    clean_event = event.strip()

    if bus is not None or priority != 0 or once or owner is not None:
        return _event_bus_on(
            clean_event,
            priority=priority,
            once=once,
            owner=owner,
            bus=bus,
        )

    def decorate(handler):
        if not callable(handler):
            raise ValidationError("Hook handler must be callable")

        registrar = _active_registrar.get() or _bound_registrar
        if registrar is not None:
            _register_hook(
                registrar,
                clean_event,
                handler,
                _active_owner.get(),
            )
            return handler

        # Full API code may also use hooks without an ExtensionManager scope.
        return _event_bus_on(clean_event)(handler)

    return decorate


__all__ = [
    "EventBus",
    "HookDispatchReport",
    "HookEvent",
    "HookFailure",
    "HookHandle",
    "emit",
    "get_event_bus",
    "off",
    "on",
    "unregister_owner",
]
