"""Assistant-oriented ReminderEngine composition.

The base ReminderEngine remains a reusable policy engine.  This composition adds
only the built-in Task follow-up policy while continuing to accept extension/user
rules through the frozen ``rules`` input.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from ...api import Event, Reminder, Task
from .engine import NotificationRequest, ReminderEngine as BaseReminderEngine
from .follow_up import TaskFollowUpPolicy


class AssistantReminderEngine(BaseReminderEngine):
    """Production ReminderEngine with the default assistant follow-up policy."""

    def __init__(
        self,
        follow_up_policy: TaskFollowUpPolicy | None = None,
    ) -> None:
        self.follow_up_policy = follow_up_policy or TaskFollowUpPolicy()

    def evaluate(
        self,
        tasks: Iterable[Task] = (),
        events: Iterable[Event] = (),
        reminders: Iterable[Reminder] = (),
        *,
        now: datetime | None = None,
        rules: Iterable[Any] = (),
    ) -> list[NotificationRequest]:
        combined_rules = (
            self.follow_up_policy,
            *tuple(rules),
        )
        return super().evaluate(
            tasks,
            events,
            reminders,
            now=now,
            rules=combined_rules,
        )


__all__ = ["AssistantReminderEngine"]
