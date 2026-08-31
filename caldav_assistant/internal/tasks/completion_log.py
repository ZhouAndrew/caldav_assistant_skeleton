"""Queue the final human work interval when a Task is completed.

Detailed machine history lives in CalDAV Work VEVENTs and Activity Journal.  The
WordPress daily log receives only the interval that completion just closed; earlier
paused intervals were already logged by the bundled work-session extension.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from ...api import Event, Task
from ..wordpress.worklog import WorkLogFormatter
from .work_service import CalDAVWorkTaskService


class TaskCompletionLogService:
    """Queue the final closed work segment using the user's WordPress log style."""

    def __init__(self, worklog: Any, wordpress: Any, settings: Any = None) -> None:
        self.worklog = worklog
        self.wordpress = wordpress
        self.formatter = WorkLogFormatter(settings)

    @staticmethod
    def _closed(segments: Iterable[Event]) -> list[Event]:
        values = [
            item
            for item in segments
            if isinstance(item, Event)
            and isinstance(item.start, datetime)
            and isinstance(item.end, datetime)
            and item.end >= item.start
        ]
        return sorted(values, key=lambda item: item.start)

    def render(self, task: Task, segments: Iterable[Event]) -> str | None:
        """Render only the interval closed by this completion operation.

        Completing an already-paused Task must not duplicate an interval that was
        written when it was paused.  CalDAVWorkTaskService intentionally gives a
        running Task's final Work VEVENT and VTODO the same end/completion instant,
        which makes this match deterministic.
        """
        completed_at = getattr(task, "completed_at", None)
        if not isinstance(completed_at, datetime):
            return None
        matches = [item for item in self._closed(segments) if item.end == completed_at]
        if not matches:
            return None
        item = matches[-1]
        return self.formatter.render_segment(
            task,
            item.start,
            item.end,
            status="completed",
        )

    def queue_for(self, task: Task) -> Any:
        text = self.render(task, self.worklog.segments_for(task))
        if not text:
            return None
        return self.wordpress.queue_log(text, _show_clock=False)


class CompletionLoggingTaskService(CalDAVWorkTaskService):
    """Production lifecycle + non-blocking WordPress final-segment queueing.

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
            # An auxiliary WordPress log must never reverse completion.
            pass
        return result


__all__ = ["TaskCompletionLogService", "CompletionLoggingTaskService"]
