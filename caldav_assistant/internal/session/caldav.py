"""Read human work-session state from CalDAV facts.

There is deliberately no persistent local state here.  The current Task is the
Task referenced by the single open Work VEVENT; paused Tasks are IN-PROCESS VTODOs
without that open interval.
"""
from __future__ import annotations

from typing import Any


class CalDAVSessionService:
    def __init__(self, worklog: Any, tasks: Any = None) -> None:
        self.worklog = worklog
        self.tasks = tasks
        self.last_items: list[Any] = []
        self.current_selection: Any = None

    def bind_tasks(self, tasks: Any) -> None:
        self.tasks = tasks

    def current_task_id(self) -> str | None:
        return self.worklog.current_task_id()

    def current_task(self) -> Any:
        uid = self.current_task_id()
        if uid is None or self.tasks is None:
            return None
        try:
            task = self.tasks.get(uid)
        except Exception:
            return None
        if getattr(task, "completed", False) or getattr(task, "status", "") == "CANCELLED":
            return None
        return task

    def paused_task_ids(self) -> tuple[str, ...]:
        if self.tasks is None:
            return ()
        current = self.current_task_id()
        try:
            items = self.tasks.list(status="IN-PROCESS")
        except Exception:
            return ()
        return tuple(
            str(task.id)
            for task in items
            if getattr(task, "id", None)
            and str(task.id) != current
            and getattr(task, "status", "") == "IN-PROCESS"
            and not bool(getattr(task, "completed", False))
        )

    def paused_tasks(self) -> list[Any]:
        if self.tasks is None:
            return []
        result = []
        for uid in self.paused_task_ids():
            try:
                result.append(self.tasks.get(uid))
            except Exception:
                continue
        return result

    # Production Task lifecycle writes through WorkLogService directly.  These
    # compatibility methods intentionally persist nothing locally.
    def set_current(self, task: Any) -> None:
        return None

    def clear_current(self, task: Any = None) -> None:
        return None

    def mark_paused(self, task: Any) -> None:
        return None

    def unpause(self, task: Any) -> None:
        return None

    def forget(self, task: Any) -> None:
        return None


__all__ = ["CalDAVSessionService"]
