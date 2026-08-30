"""Built-in Task follow-up reminder policy.

This module is intentionally pure.  It reads public Task facts and the injected
clock, then returns platform-neutral NotificationRequests.  It does not persist
state, call CalDAV, or deliver notifications.

The policy fills the gap between a one-shot due reminder and an assistant that
keeps following an unfinished Task.  After a Task has been overdue for a short
grace period, it emits one catch-up slot plus the next scheduled slot.  Therefore
a machine that was asleep for hours does not replay an entire backlog of nags.
Completion/cancellation is still decided by the authoritative CalDAV Task state;
ReminderEngine stops calling rules for inactive Tasks.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ...api import Task
from .engine import NotificationRequest


@dataclass(frozen=True, slots=True)
class TaskFollowUpPolicy:
    """Generate bounded repeated follow-ups for overdue unfinished Tasks."""

    first_overdue_delay: timedelta = timedelta(minutes=20)
    repeat_interval: timedelta = timedelta(hours=1)

    def __post_init__(self) -> None:
        if self.first_overdue_delay.total_seconds() < 0:
            raise ValueError("first_overdue_delay must not be negative")
        if self.repeat_interval.total_seconds() <= 0:
            raise ValueError("repeat_interval must be positive")

    def evaluate(
        self,
        item: Any,
        now: datetime,
    ) -> list[NotificationRequest]:
        if not isinstance(item, Task):
            return []
        if not isinstance(item.due, datetime):
            # Preserve the frozen date-only contract.  A calendar date does not
            # secretly become midnight merely to make follow-up scheduling easy.
            return []
        if item.completed:
            return []

        status = str(item.status or "").upper()
        if status in {"COMPLETED", "CANCELLED"}:
            return []

        clock, due = self._comparable_pair(now, item.due)
        first = due + self.first_overdue_delay
        if clock < first:
            return []

        elapsed = clock - first
        slot_index = int(elapsed // self.repeat_interval)
        current = first + self.repeat_interval * slot_index
        following = current + self.repeat_interval

        return [
            self._request(item, status, due, current, slot_index),
            self._request(item, status, due, following, slot_index + 1),
        ]

    @staticmethod
    def _comparable_pair(
        now: datetime,
        due: datetime,
    ) -> tuple[datetime, datetime]:
        clock = (
            now
            if now.tzinfo is not None
            else now.replace(tzinfo=timezone.utc)
        )
        if due.tzinfo is None:
            due = due.replace(tzinfo=clock.tzinfo or timezone.utc)
        return clock, due

    def _request(
        self,
        task: Task,
        status: str,
        due: datetime,
        when: datetime,
        slot_index: int,
    ) -> NotificationRequest:
        summary = str(task.summary or "").strip() or "Task"
        token = str(task.id or "").strip() or summary
        overdue_for = when - due
        duration = self._duration_text(overdue_for)

        if status == "IN-PROCESS":
            title = f"Task still in progress: {summary}"
            body = (
                f"Overdue by {duration}. "
                "Finish it and mark it done when complete."
            )
        else:
            title = f"Task still unfinished: {summary}"
            body = (
                f"Overdue by {duration}. "
                "Start it now or reschedule the due time."
            )

        return NotificationRequest(
            key=(
                "task_follow_up:"
                f"{token}:{slot_index}:{when.isoformat()}"
            ),
            when=when,
            title=title,
            body=body,
            source="task_follow_up",
            object_id=str(task.id or "").strip() or None,
            metadata={
                "kind": "task",
                "reason": "task_follow_up",
                "stage": "overdue",
                "slot_index": slot_index,
                "due": due.isoformat(),
                "status": status,
            },
        )

    @staticmethod
    def _duration_text(value: timedelta) -> str:
        total_minutes = max(0, int(value.total_seconds() // 60))
        hours, minutes = divmod(total_minutes, 60)
        parts: list[str] = []
        if hours:
            parts.append(f"{hours} hour" + ("s" if hours != 1 else ""))
        if minutes or not parts:
            parts.append(
                f"{minutes} minute" + ("s" if minutes != 1 else "")
            )
        return " ".join(parts)


__all__ = ["TaskFollowUpPolicy"]
