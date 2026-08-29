"""Owner-aware registration bridge for ReminderEngine extension rules."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator

from ...api.v1.errors import ExtensionError, ValidationError


@dataclass(frozen=True, slots=True)
class ReminderRuleEntry:
    rule: Any
    owner: str | None = None


class ReminderRuleRegistry:
    """Small process-local registry with extension ownership for clean unload."""

    def __init__(self) -> None:
        self._entries: list[ReminderRuleEntry] = []

    def register(self, rule: Any, *, owner: str | None = None) -> Any:
        function = rule if callable(rule) else getattr(rule, "evaluate", None)
        if not callable(function):
            raise ValidationError(
                "Reminder rule must be callable or provide evaluate(item, now)"
            )
        clean_owner = None
        if owner is not None:
            if not isinstance(owner, str) or not owner.strip():
                raise ValidationError("Reminder rule owner must not be empty")
            clean_owner = owner.strip()
        if not any(entry.rule is rule for entry in self._entries):
            self._entries.append(ReminderRuleEntry(rule=rule, owner=clean_owner))
        return rule

    def rules(self) -> tuple[Any, ...]:
        return tuple(entry.rule for entry in self._entries)

    def unregister_owner(self, owner: str) -> int:
        if not isinstance(owner, str) or not owner.strip():
            return 0
        clean = owner.strip()
        before = len(self._entries)
        self._entries = [entry for entry in self._entries if entry.owner != clean]
        return before - len(self._entries)

    def clear(self) -> None:
        self._entries.clear()


_bound_registry: ReminderRuleRegistry | None = None
_active_registry: ContextVar[ReminderRuleRegistry | None] = ContextVar(
    "caldav_assistant_active_reminder_rule_registry", default=None
)
_active_owner: ContextVar[str | None] = ContextVar(
    "caldav_assistant_active_reminder_rule_owner", default=None
)


def bind_reminder_rule_registry(registry: ReminderRuleRegistry) -> None:
    if not isinstance(registry, ReminderRuleRegistry):
        raise TypeError("registry must be ReminderRuleRegistry")
    global _bound_registry
    _bound_registry = registry


@contextmanager
def reminder_rule_registration_scope(
    registry: ReminderRuleRegistry,
    *,
    owner: str,
) -> Iterator[None]:
    if not isinstance(registry, ReminderRuleRegistry):
        raise TypeError("registry must be ReminderRuleRegistry")
    if not isinstance(owner, str) or not owner.strip():
        raise ExtensionError("Reminder rule owner must not be empty")
    registry_token = _active_registry.set(registry)
    owner_token = _active_owner.set(owner.strip())
    try:
        yield
    finally:
        _active_owner.reset(owner_token)
        _active_registry.reset(registry_token)


def reminder_rule(rule: Any = None):
    """Register a classic-AI reminder rule from extension code.

    A rule receives ``(Task|Event, now)`` and returns NotificationRequest(s) or None.
    It never gets permission to mutate the item merely by being a rule.
    """
    def decorate(target: Any):
        registry = _active_registry.get() or _bound_registry
        if registry is None:
            raise ExtensionError(
                "No ReminderRuleRegistry is bound; reminder_rule must run inside "
                "an Assistant application or extension load scope"
            )
        registry.register(target, owner=_active_owner.get())
        return target

    return decorate(rule) if rule is not None else decorate


__all__ = [
    "ReminderRuleEntry",
    "ReminderRuleRegistry",
    "bind_reminder_rule_registry",
    "reminder_rule_registration_scope",
    "reminder_rule",
]
