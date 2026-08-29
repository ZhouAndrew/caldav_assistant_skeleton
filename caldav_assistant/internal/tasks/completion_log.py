"""Build durable long-term work logs for completed Tasks.

Activity Journal remains the fine-grained local event stream.  This module turns the
successful events for one Task into a human-readable completion summary and queues it
for WordPress without waiting for remote transport.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from ...api import Activity, Task
from .service import TaskService


_ACTION_LABELS = {
    "task_started": "Started work",
    "task_paused": "Paused work",
    "task_resumed": "Resumed work",
    "task_completed": "Completed task",
    "task_planned_start_changed": "Changed planned start",
    "task_due_changed": "Changed due",
    "task_priority_changed": "Changed priority",
}


class TaskCompletionLogService:
    """Queue one WordPress work log when a Task reaches completion."""

    def __init__(self, activity: Any, wordpress: Any) -> None:
        self.activity = activity
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
    def _work_segments(cls, activities: Iterable[Activity]) -> list[tuple[datetime, datetime]]:
        segments: list[tuple[datetime, datetime]] = []
        opened: datetime | None = None
        for item in sorted(activities, key=lambda value: value.timestamp):
            if item.action in {"task_started", "task_resumed"}:
                opened = item.timestamp
                continue
            if item.action in {"task_paused", "task_completed"} and opened is not None:
                if item.timestamp >= opened:
                    segments.append((opened, item.timestamp))
                opened = None
        return segments

    @classmethod
    def render(cls, task: Task, activities: Iterable[Activity]) -> str:
        items = sorted(list(activities), key=lambda value: value.timestamp)
        relevant = [item for item in items if item.action in _ACTION_LABELS]
        segments = cls._work_segments(relevant)
        total_seconds = sum((end - start).total_seconds() for start, end in segments)

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

        if relevant:
            for item in relevant:
                label = _ACTION_LABELS[item.action]
                lines.append(f"- {cls._stamp(item.timestamp)} — {label}")
        else:
            lines.append("- No Assistant work-session history was recorded.")

        lines.extend(["", "Work segments"])
        if segments:
            for start, end in segments:
                lines.append(
                    f"- {cls._stamp(start)} → {cls._stamp(end)} "
                    f"({cls._duration((end - start).total_seconds())})"
                )
            lines.append(f"- Total active time: {cls._duration(total_seconds)}")
        else:
            lines.append("- No complete start/pause/resume/end interval was recorded.")

        if task.description.strip():
            lines.extend(["", "Task notes", task.description.strip()])

        return "\n".join(lines).strip()

    def queue_for(self, task: Task) -> Any:
        activities = self.activity.for_task(task)
        text = self.render(task, activities)
        return self.wordpress.queue_log(
            text,
            title=f"Completed — {task.summary}",
        )


class CompletionLoggingTaskService(TaskService):
    """Production TaskService decorator that adds non-blocking long-term logs.

    CalDAV completion is authoritative and happens first.  WordPress transport is
    never attempted here: only a durable Outbox enqueue is requested.  If even that
    auxiliary enqueue fails, Task completion still succeeds and the failure is
    recorded in the local Activity Journal when possible.
    """

    def __init__(self, *args: Any, completion_log: TaskCompletionLogService, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.completion_log = completion_log

    def complete(self, task: Task | str):
        result = super().complete(task)
        try:
            self.completion_log.queue_for(result.affected)
        except Exception as exc:
            try:
                self._record(
                    "task_completion_log_queue_failed",
                    result.affected,
                    error=f"{type(exc).__name__}: {exc}",
                )
            except Exception:
                pass
        return result


__all__ = ["TaskCompletionLogService", "CompletionLoggingTaskService"]
