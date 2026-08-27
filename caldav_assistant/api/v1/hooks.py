"""Stable v1 hook decorator plus internal registrar binding.

Public extension authors use only::

    from caldav_assistant.api.v1 import on

    @on("task.completed")
    def ...

The underscore-prefixed binding/scope helpers are internal composition plumbing.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from .errors import ExtensionError, ValidationError


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
    global _bound_registrar
    _bound_registrar = registrar


@contextmanager
def _hook_registration_scope(
    registrar: Any,
    *,
    owner: str,
) -> Iterator[None]:
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


def on(event: str):
    """Register a Full API hook without exposing HookRegistry internals."""
    if not isinstance(event, str) or not event.strip():
        raise ValidationError("Hook event must not be empty")
    clean_event = event.strip()

    def decorate(handler):
        if not callable(handler):
            raise ValidationError("Hook handler must be callable")
        registrar = _active_registrar.get() or _bound_registrar
        if registrar is None:
            raise ExtensionError(
                "No hook registrar is bound; @on must run inside an Assistant "
                "application or ExtensionManager load scope"
            )
        _register_hook(
            registrar,
            clean_event,
            handler,
            _active_owner.get(),
        )
        return handler

    return decorate


__all__ = ["on"]
