"""Assistant-owned work-period deadlines for the current Task.

A work period is an operational promise such as "work on this Task for 30 minutes".
It is deliberately NOT the Task's CalDAV DUE/DTSTART and it never completes or pauses
the Task automatically.  Persistence reuses ReminderService explicit reminders, so a
restart does not lose the deadline and no second Task/Event database is introduced.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any, Callable

from ..api.v1.errors import ValidationError


_DURATION_RE = re.compile(
    r"^(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours)$",
    re.IGNORECASE,
)


def parse_work_duration(value: Any) -> int:
    """Parse a positive human duration and return whole seconds."""
    if isinstance(value, bool):
        raise ValidationError("Work period must be a duration such as 30m or 1h")
    if isinstance(value, (int, float)):
        seconds = int(value)
    elif isinstance(value, str):
        match = _DURATION_RE.fullmatch(value.strip())
        if match is None:
            raise ValidationError("Work period must look like 30m, 90min, 1h, or 45s")
        amount = float(match.group("value"))
        unit = match.group("unit").casefold()
        multiplier = 1 if unit.startswith("s") else 60 if unit.startswith("m") else 3600
        seconds = int(amount * multiplier)
    else:
        raise ValidationError("Work period must be a duration such as 30m or 1h")
    if seconds <= 0:
        raise ValidationError("Work period must be greater than zero")
    return seconds


def maybe_work_duration(value: Any) -> int | None:
    """Return seconds only when *value* clearly looks like a duration token."""
    if not isinstance(value, str) or _DURATION_RE.fullmatch(value.strip()) is None:
        return None
    return parse_work_duration(value)


def format_work_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


class WorkPeriodService:
    """Manage one Assistant work-period reminder for the current Task."""

    KIND = "work_period"
    SOURCE = "work_period_end"

    def __init__(
        self,
        reminders: Any,
        *,
        activity: Any = None,
        session: Any = None,
        tasks: Any = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.reminders = reminders
        self.activity = activity
        self.session = session
        self.tasks = tasks
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise TypeError("WorkPeriodService clock must return datetime")
        if value.tzinfo is None:
            value = value.astimezone()
        return value.astimezone(timezone.utc)

    @staticmethod
    def _task_id(task: Any) -> str:
        value = str(getattr(task, "id", task) or "").strip()
        if not value:
            raise ValidationError("Task id must not be empty")
        return value

    def _task(self, task: Any) -> Any:
        if not isinstance(task, str):
            return task
        getter = getattr(self.tasks, "get", None)
        if callable(getter):
            return getter(task)
        return task

    def _current_task_id(self) -> str | None:
        getter = getattr(self.session, "current_task_id", None)
        if callable(getter):
            value = getter()
            return str(value).strip() if value else None
        return None

    def _items_for(self, task: Any) -> list[Any]:
        task_id = self._task_id(task)
        try:
            return list(self.reminders.list(kind=self.KIND, task_id=task_id) or ())
        except TypeError:
            return [
                item
                for item in (self.reminders.list() or ())
                if getattr(item, "metadata", {}).get("kind") == self.KIND
                and getattr(item, "metadata", {}).get("task_id") == task_id
            ]

    def cancel_for(self, task: Any, *, reason: str = "cancelled", record: bool = True) -> list[Any]:
        task_id = self._task_id(task)
        cancelled: list[Any] = []
        for reminder in self._items_for(task_id):
            try:
                cancelled.append(self.reminders.cancel(reminder))
            except Exception:
                raise
        if cancelled and record and self.activity is not None:
            self.activity.record(
                "work_period_cancelled",
                task_id,
                reason=reason,
                reminder_ids=[str(getattr(item, "id", "") or "") for item in cancelled],
                storage="assistant_state/reminders.items.v1",
            )
        return cancelled

    def allocate(self, task_id: str | None = None, seconds: Any = None) -> dict[str, Any]:
        seconds_value = parse_work_duration(seconds)
        current_id = self._current_task_id()
        if task_id is None:
            task_id = current_id
        task_id = self._task_id(task_id)
        if current_id is not None and current_id != task_id:
            raise ValidationError(
                "A work period can only be assigned to the Task you are working on now"
            )

        task = self._task(task_id)
        summary = str(getattr(task, "summary", "") or task_id).strip() or task_id
        self.cancel_for(task_id, reason="replaced", record=False)

        started_at = self._now()
        deadline = started_at + timedelta(seconds=seconds_value)
        reminder = self.reminders.create(
            f"Work period finished — {summary}",
            deadline,
            kind=self.KIND,
            source=self.SOURCE,
            task_id=task_id,
            duration_seconds=seconds_value,
            started_at=started_at.isoformat(),
            deadline=deadline.isoformat(),
            body=(
                f"The allocated {format_work_duration(seconds_value)} work period has ended. "
                "The Task is still in progress; press Ctrl-C in the monitor to complete or pause it."
            ),
        )
        if self.activity is not None:
            self.activity.record(
                "work_period_allocated",
                task_id,
                duration_seconds=seconds_value,
                started_at=started_at.isoformat(),
                deadline=deadline.isoformat(),
                reminder_id=str(getattr(reminder, "id", "") or ""),
                storage="assistant_state/reminders.items.v1",
                task_due_changed=False,
            )
        return self.status(task_id)

    def cancel(self, task_id: str | None = None, reason: str = "user") -> dict[str, Any]:
        if task_id is None:
            task_id = self._current_task_id()
        task_id = self._task_id(task_id)
        cancelled = self.cancel_for(task_id, reason=reason)
        return {
            "state": "cancelled" if cancelled else "none",
            "task_id": task_id,
            "cancelled": len(cancelled),
            "storage": "assistant_state/reminders.items.v1",
            "task_due_changed": False,
        }

    def status(self, task_id: str | None = None) -> dict[str, Any]:
        if task_id is None:
            task_id = self._current_task_id()
        if not task_id:
            return {
                "state": "none",
                "task_id": None,
                "storage": "assistant_state/reminders.items.v1",
                "task_due_changed": False,
            }
        task_id = self._task_id(task_id)
        items = self._items_for(task_id)
        if not items:
            return {
                "state": "none",
                "task_id": task_id,
                "storage": "assistant_state/reminders.items.v1",
                "task_due_changed": False,
            }

        item = max(items, key=lambda value: getattr(value, "when", datetime.min.replace(tzinfo=timezone.utc)))
        when = getattr(item, "when", None)
        now = self._now()
        if isinstance(when, datetime):
            comparable = when
            if comparable.tzinfo is None:
                comparable = comparable.astimezone()
            comparable = comparable.astimezone(timezone.utc)
            remaining = int((comparable - now).total_seconds())
            deadline = comparable.isoformat()
            state = "scheduled" if remaining > 0 else "expired"
        else:
            remaining = None
            deadline = str(when) if when is not None else None
            state = "unknown"
        metadata = dict(getattr(item, "metadata", {}) or {})
        return {
            "state": state,
            "task_id": task_id,
            "reminder_id": str(getattr(item, "id", "") or ""),
            "deadline": deadline,
            "remaining_seconds": remaining,
            "duration_seconds": int(metadata.get("duration_seconds", 0) or 0),
            "source": self.SOURCE,
            "storage": "assistant_state/reminders.items.v1",
            "task_due_changed": False,
        }


__all__ = [
    "WorkPeriodService",
    "parse_work_duration",
    "maybe_work_duration",
    "format_work_duration",
]
