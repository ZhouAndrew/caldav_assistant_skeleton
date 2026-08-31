"""Task lifecycle semantics backed by CalDAV Work VEVENTs when available.

Production prefers authoritative CalDAV Work VEVENTs for cross-device work intervals,
but work-history storage is an optional enhancement rather than a prerequisite for
using Tasks.  When no work-log VEVENT collection is configured, lifecycle actions
fall back to the base TaskService and its Activity Journal records.
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

    def _worklog_configured(self) -> bool:
        if self.worklog is None:
            return False
        configured = getattr(self.worklog, "configured", None)
        if not callable(configured):
            return True
        try:
            return bool(configured())
        except Exception:
            return False

    def _session_current_id(self) -> str | None:
        # The Session service owns the user-facing current/paused interpretation.
        # With a configured work log it delegates to WorkLogService; without one it
        # derives state from explicit Activity Journal lifecycle records.
        if self.session is not None:
            return super()._session_current_id()
        if self._worklog_configured():
            return self.worklog.current_task_id()
        return None

    def _session_paused_ids(self) -> tuple[str, ...]:
        if self.session is not None:
            return super()._session_paused_ids()
        if not self._worklog_configured():
            return ()

        current = self.worklog.current_task_id()
        try:
            items = self.list(status="IN-PROCESS")
        except Exception:
            return ()

        paused: list[str] = []
        for task in items:
            task_id = str(getattr(task, "id", "") or "").strip()
            if not task_id or task_id == current or task.completed:
                continue
            try:
                # An IN-PROCESS VTODO is not enough to mean "paused by this
                # Assistant".  A prior Assistant work segment is the proof.
                if self.worklog.segments_for(task):
                    paused.append(task_id)
            except Exception:
                continue
        return tuple(paused)

    def start(self, task: Task | str) -> ActionResult:
        if not self._worklog_configured():
            return super().start(task)

        obj = self.get(task)
        self._require_id(obj)
        if obj.completed or obj.status in {"COMPLETED", "CANCELLED"}:
            raise ValidationError("A completed or cancelled Task cannot be started")

        # WorkLogService.start_segment performs the authoritative open-interval
        # check itself. The old code first asked Session for current_task_id and then
        # start_segment immediately repeated the same CalDAV Work read.
        segment = self.worklog.start_segment(obj)
        try:
            result = self._update(
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

        self._record(
            "task_started",
            result.affected,
            work_session_before="none",
            work_session_after="current",
            **self._plan_context(obj),
        )
        return result

    def pause(self, task: Task | str) -> ActionResult:
        if not self._worklog_configured():
            return super().pause(task)

        obj = self.get(task)
        self._require_id(obj)
        if obj.status != "IN-PROCESS":
            raise ValidationError("A planned Task is not running and cannot be paused")

        # close_segment validates that this exact Task owns the authoritative open
        # interval. Do not read current_task_id first and then read the same interval
        # again just to close it.
        self.worklog.close_segment(obj, required=True)
        self._record(
            "task_paused",
            obj,
            work_session_before="current",
            work_session_after="paused",
            **self._plan_context(obj),
        )
        return ActionResult(True, affected=obj, undo_available=False)

    def resume(self, task: Task | str) -> ActionResult:
        if not self._worklog_configured():
            return super().resume(task)

        obj = self.get(task)
        self._require_id(obj)
        if obj.completed or obj.status in {"COMPLETED", "CANCELLED"}:
            raise ValidationError("A completed or cancelled Task cannot be resumed")
        if obj.status != "IN-PROCESS":
            raise ValidationError("Only an in-progress Task can be resumed")

        # A closed prior segment is the proof that this Assistant previously paused
        # the Task. The old _session_paused_ids path listed every IN-PROCESS Task and
        # then re-scanned Work history once per Task before start_segment scanned the
        # open intervals yet again.
        if not self.worklog.segments_for(obj):
            raise ValidationError("Only a Task you previously paused can be resumed")

        self.worklog.start_segment(obj)
        self._record(
            "task_resumed",
            obj,
            work_session_before="paused",
            work_session_after="current",
            **self._plan_context(obj),
        )
        return ActionResult(True, affected=obj, undo_available=False)

    def complete(self, task: Task | str) -> ActionResult:
        if not self._worklog_configured():
            return super().complete(task)

        obj = self.get(task)
        task_id = self._require_id(obj)
        current_id = self.worklog.current_task_id()
        if current_id == task_id:
            work_session_before = "current"
        else:
            # Only this Task's history is relevant. Avoid constructing the global
            # paused set, which previously listed all IN-PROCESS Tasks and scanned
            # Work history separately for every candidate.
            try:
                work_session_before = "paused" if self.worklog.segments_for(obj) else "none"
            except Exception:
                work_session_before = "none"

        closed = None
        completed_at = self.worklog.now()
        if current_id == task_id:
            closed = self.worklog.close_segment(obj, required=True)
            # Use the same authoritative clock instant for VTODO completion as the
            # closed interval when possible.
            if getattr(closed, "end", None) is not None:
                completed_at = closed.end

        try:
            result = self._update(
                obj,
                {
                    "status": "COMPLETED",
                    "completed": True,
                    "completed_at": completed_at,
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

        self._record(
            "task_completed",
            result.affected,
            work_session_before=work_session_before,
            work_session_after="none",
            **self._plan_context(obj),
        )
        return result


__all__ = ["CalDAVWorkTaskService"]