"""Build human long-term logs from authoritative CalDAV Work VEVENTs."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from ...api import Event, Task
from .work_service import CalDAVWorkTaskService


class TaskCompletionLogService:
    """Queue one WordPress summary derived from CalDAV work intervals."""

    def __init__(self, worklog: Any, wordpress: Any) -> None:
        self.worklog = worklog
        self.wordpress = wordpress

    @staticmethod
    def _stamp(value: Any) -> str:
        if isinstance(value, datetime):
            return value.astimezone().isoformat(timespec="seconds")
        if value is None:
            return "—"
        return str(value)

    @staticmethod
    def _duration(seconds: float) -> str:
        seconds = max(0, int(seconds))
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours}h {minutes}m {secs}s"
        if minutes:
            return f"{minutes}m {secs}s"
        return f"{secs}s"

    @classmethod
    def render(cls, task: Task, segments: Iterable[Event]) -> str:
        items = sorted(
            [item for item in segments if isinstance(item, Event)],
            key=lambda item: item.start or datetime.min,
        )
        closed = [
            item
            for item in items
            if isinstance(item.start, datetime)
            and isinstance(item.end, datetime)
            and item.end >= item.start
        ]
        total_seconds = sum((item.end - item.start).total_seconds() for item in closed)

        lines = [
            f"Task completed: {task.summary}",
            "",
            "Plan",
            f"- Planned start: {cls._stamp(task.start)}",
            f"- Due: {cls._stamp(task.due)}",
            f"- Priority: {task.priority if task.priority is not None else '—'}",
            f"- Completed: {cls._stamp(task.completed_at)}",
            "",
            "Work history",
        ]

        if closed:
            for index, item in enumerate(closed):
                start_label = "Started work" if index == 0 else "Resumed work"
                end_label = "Completed/ended interval" if index == len(closed) - 1 else "Paused work"
                lines.append(f"- {cls._stamp(item.start)} — {start_label}")
                lines.append(f"- {cls._stamp(item.end)} — {end_label}")
        else:
            lines.append("- No completed CalDAV work interval was recorded.")

        lines.extend(["", "Work segments"])
        if closed:
            for item in closed:
                lines.append(
                    f"- {cls._stamp(item.start)} → {cls._stamp(item.end)} "
                    f"({cls._duration((item.end - item.start).total_seconds())})"
                )
            lines.append(f"- Total active time: {cls._duration(total_seconds)}")
        else:
            lines.append("- No complete work interval was recorded.")

        if task.description.strip():
            lines.extend(["", "Task notes", task.description.strip()])

        return "\n".join(lines).strip()

    def queue_for(self, task: Task) -> Any:
        segments = self.worklog.segments_for(task)
        text = self.render(task, segments)
        return self.wordpress.queue_log(
            text,
            title=f"Completed — {task.summary}",
        )


class CompletionLoggingTaskService(CalDAVWorkTaskService):
    """Production lifecycle + non-blocking WordPress completion summary.

    CalDAV VTODO/VEVENT writes happen first.  WordPress transport remains decoupled:
    only the durable Outbox is queued after authoritative completion.
    """

    def __init__(self, *args: Any, completion_log: TaskCompletionLogService, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.completion_log = completion_log

    def complete(self, task: Task | str):
        result = super().complete(task)
        try:
            self.completion_log.queue_for(result.affected)
        except Exception:
            # The Task and its Work VEVENTs are already authoritative CalDAV facts.
            # An auxiliary WordPress summary must never reverse completion.
            pass
        return result


__all__ = ["TaskCompletionLogService", "CompletionLoggingTaskService"]
