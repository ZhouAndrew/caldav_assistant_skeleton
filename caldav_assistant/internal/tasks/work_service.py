"""Task lifecycle semantics backed by CalDAV Work VEVENTs.

The base TaskService remains useful for pure unit/object API use.  Production uses
this subclass so start/pause/resume/complete work-session facts are stored only in
CalDAV, not in the local Activity Journal or assistant_state table.
"""
from __future__ import annotations

from typing import Any

from ...api import ActionResult, Task
from ...api.v1.errors import ValidationError
from .service import TaskService


class CalDAVWorkTaskService(TaskService):
    def __init__(self, *args: Any, worklog: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.worklog = worklog

    def _caldav_work_enabled(self) -> bool:
        return self.worklog is not None

    def _session_current_id(self) -> str | None:
        if self.worklog is not None:
            return self.worklog.current_task_id()
        return super()._session_current_id()

    def _session_paused_ids(self) -> tuple[str, ...]:
        if self.worklog is None:
            return super()._session_paused_ids()
        current = self.worklog.current_task_id()
        try:
            items = self.list(status="IN-PROCESS")
        except Exception:
            return ()
        return tuple(
            task.id
            for task in items
            if task.id
            and task.id != current
            and task.status == "IN-PROCESS"
            and not task.completed
        )

    def start(self, task: Task | str) -> ActionResult:
        if self.worklog is None:
            return super().start(task)

        obj = self.get(task)
        task_id = self._require_id(obj)
        if obj.completed or obj.status in {"COMPLETED", "CANCELLED"}:
            raise ValidationError("A completed or cancelled Task cannot be started")

        current_id = self.worklog.current_task_id()
        if current_id == task_id:
            raise ValidationError("This Task is already the current work")
        if current_id:
            raise ValidationError(
                "Another Task is currently being worked on; pause or complete it before starting a different Task"
            )

        segment = self.worklog.start_segment(obj)
        try:
            return self._update(
                obj,
                {
                    "status": "IN-PROCESS",
                    "completed": False,
                    "completed_at": None,
                },
                activity_action=None,
            )
        except Exception:
            try:
                self.worklog.discard_segment(segment)
            except Exception:
                pass
            raise

    def pause(self, task: Task | str) -> ActionResult:
        if self.worklog is None:
            return super().pause(task)

        obj = self.get(task)
        task_id = self._require_id(obj)
        if obj.status != "IN-PROCESS":
            raise ValidationError("A planned Task is not running and cannot be paused")
        if self.worklog.current_task_id() != task_id:
            raise ValidationError("Only the Task you are working on now can be paused")

        self.worklog.close_segment(obj, required=True)
        return ActionResult(True, affected=obj, undo_available=False)

    def resume(self, task: Task | str) -> ActionResult:
        if self.worklog is None:
            return super().resume(task)

        obj = self.get(task)
        task_id = self._require_id(obj)
        if obj.completed or obj.status in {"COMPLETED", "CANCELLED"}:
            raise ValidationError("A completed or cancelled Task cannot be resumed")
        if obj.status != "IN-PROCESS":
            raise ValidationError("Only an in-progress Task can be resumed")

        current_id = self.worklog.current_task_id()
        if current_id:
            if current_id == task_id:
                raise ValidationError("This Task is already the current work")
            raise ValidationError(
                "Another Task is currently being worked on; pause or complete it before resuming this Task"
            )
        if self.worklog.open_for(obj) is not None:
            raise ValidationError("This Task already has an open CalDAV work interval")

        self.worklog.start_segment(obj)
        return ActionResult(True, affected=obj, undo_available=False)

    def complete(self, task: Task | str) -> ActionResult:
        if self.worklog is None:
            return super().complete(task)

        obj = self.get(task)
        task_id = self._require_id(obj)
        closed = None
        if self.worklog.current_task_id() == task_id:
            closed = self.worklog.close_segment(obj, required=True)

        try:
            return self._update(
                obj,
                {
                    "status": "COMPLETED",
                    "completed": True,
                    "completed_at": self._normalize_changes({"status": "COMPLETED"})["completed_at"],
                },
                activity_action=None,
            )
        except Exception:
            if closed is not None:
                try:
                    self.worklog.reopen_segment(closed)
                except Exception:
                    pass
            raise


__all__ = ["CalDAVWorkTaskService"]
