"""Owner-aware registry for ReminderEngine extension rules.

The registry stores extension rule callables only. It does not evaluate Task/Event
facts and does not deliver notifications. ReminderEngine remains the pure decision
engine and ReminderService remains the delivery orchestrator.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...api.v1.errors import ValidationError


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


__all__ = ["ReminderRuleEntry", "ReminderRuleRegistry"]
