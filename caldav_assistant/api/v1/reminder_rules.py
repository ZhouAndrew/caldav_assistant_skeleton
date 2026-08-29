"""Stable v1 reminder-rule extension surface.

Reminder rules are advisory bricks: they inspect public Task/Event objects and
return platform-neutral NotificationRequest values. Delivery and Task mutation
remain owned by Core services.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Iterator

from .errors import ExtensionError
from .models import NotificationRequest


Registrar = Callable[[Any, str | None], Any]
_bound_registrar: Registrar | None = None
_active_registrar: ContextVar[Registrar | None] = ContextVar(
    "caldav_assistant_active_reminder_rule_registrar", default=None
)
_active_owner: ContextVar[str | None] = ContextVar(
    "caldav_assistant_active_reminder_rule_owner", default=None
)


def _bind_reminder_rule_registrar(registrar: Registrar) -> None:
    """Internal composition hook; not part of the public compatibility promise."""
    if not callable(registrar):
        raise TypeError("registrar must be callable")
    global _bound_registrar
    _bound_registrar = registrar


@contextmanager
def _reminder_rule_registration_scope(
    registrar: Registrar,
    *,
    owner: str,
) -> Iterator[None]:
    """Internal extension-loader scope used to attach ownership."""
    if not callable(registrar):
        raise TypeError("registrar must be callable")
    if not isinstance(owner, str) or not owner.strip():
        raise ExtensionError("Reminder rule owner must not be empty")
    registrar_token = _active_registrar.set(registrar)
    owner_token = _active_owner.set(owner.strip())
    try:
        yield
    finally:
        _active_owner.reset(owner_token)
        _active_registrar.reset(registrar_token)


def reminder_rule(rule: Any = None):
    """Register one classic-AI reminder rule from extension code.

    A rule receives ``(Task|Event, now)`` and returns NotificationRequest(s) or
    ``None``. Registration itself grants no permission to mutate Task/Event facts.
    """
    def decorate(target: Any):
        registrar = _active_registrar.get() or _bound_registrar
        if registrar is None:
            raise ExtensionError(
                "No reminder-rule registrar is bound; reminder_rule must run inside "
                "an Assistant application or extension load scope"
            )
        registrar(target, _active_owner.get())
        return target

    return decorate(rule) if rule is not None else decorate


__all__ = ["NotificationRequest", "reminder_rule"]
