"""Production Task lifecycle with Assistant work-period cleanup.

The work-period timer is auxiliary Assistant state.  Successful pause/complete/delete
must remove any still-pending timer so a later notification cannot refer to work that
has already stopped.  Authoritative CalDAV mutations always happen first; cleanup
failure is recorded in Activity Journal and never rolls back a successful Task write.
"""
from __future__ import annotations

from typing import Any

from .completion_log import CompletionLoggingTaskService


class WorkPeriodAwareTaskService(CompletionLoggingTaskService):
    def __init__(self, *args: Any, work_periods: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.work_periods = work_periods

    def bind_work_periods(self, work_periods: Any) -> None:
        self.work_periods = work_periods

    def _cancel_work_period(self, task: Any, *, reason: str) -> None:
        service = self.work_periods
        cancel = getattr(service, "cancel_for", None)
        if not callable(cancel):
            return
        task_id = str(getattr(task, "id", task) or "").strip()
        try:
            cancel(task_id, reason=reason)
        except Exception as exc:
            # The Task transition is already authoritative.  Record the cleanup
            # defect instead of lying to callers that the Task action itself failed.
            try:
                self._record(
                    "work_period_cleanup_failed",
                    task,
                    reason=reason,
                    error=f"{type(exc).__name__}: {exc}",
                )
            except Exception:
                pass

    def pause(self, task: Any):
        result = super().pause(task)
        self._cancel_work_period(result.affected, reason="task_paused")
        return result

    def complete(self, task: Any):
        result = super().complete(task)
        self._cancel_work_period(result.affected, reason="task_completed")
        return result

    def delete(self, task: Any):
        # Capture the id before the authoritative object disappears.
        obj = self.get(task)
        result = super().delete(obj)
        self._cancel_work_period(obj, reason="task_deleted")
        return result


__all__ = ["WorkPeriodAwareTaskService"]
