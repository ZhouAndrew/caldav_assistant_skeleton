"""Read human work-session state from explicit Assistant-owned facts.

When a Work VEVENT collection is configured, open/closed Assistant work segments are
the cross-device source for current/paused state.  Without one, the lightweight
Activity Journal is a local fallback so Task lifecycle commands remain usable.

A plain CalDAV ``STATUS:IN-PROCESS`` is never treated as proof that the Assistant
paused a Task; external CalDAV clients may legitimately use that standard status.
"""
from __future__ import annotations

from typing import Any

from ...api.v1.errors import AmbiguousError


_CURRENT_ACTIONS = frozenset({"task_started", "task_resumed"})
_PAUSED_ACTION = "task_paused"
_TERMINAL_ACTIONS = frozenset({"task_completed", "task_deleted"})
_LIFECYCLE_ACTIONS = _CURRENT_ACTIONS | {_PAUSED_ACTION} | _TERMINAL_ACTIONS


class CalDAVSessionService:
    def __init__(self, worklog: Any, tasks: Any = None, activity: Any = None) -> None:
        self.worklog = worklog
        self.tasks = tasks
        self.activity = activity
        self.last_items: list[Any] = []
        self.current_selection: Any = None

    def bind_tasks(self, tasks: Any) -> None:
        self.tasks = tasks

    def _worklog_configured(self) -> bool:
        configured = getattr(self.worklog, "configured", None)
        if not callable(configured):
            return self.worklog is not None
        try:
            return bool(configured())
        except Exception:
            return False

    def _in_progress_tasks(self) -> list[Any]:
        if self.tasks is None:
            return []
        try:
            return list(self.tasks.list(status="IN-PROCESS") or ())
        except Exception:
            return []

    def _latest_activity_action(self, task: Any) -> str | None:
        if self.activity is None:
            return None
        reader = getattr(self.activity, "for_task", None)
        if not callable(reader):
            return None
        try:
            items = [
                item
                for item in (reader(task) or ())
                if getattr(item, "action", None) in _LIFECYCLE_ACTIONS
            ]
        except Exception:
            return None
        if not items:
            return None
        latest = max(items, key=lambda item: getattr(item, "timestamp", 0))
        return str(getattr(latest, "action", "") or "") or None

    def current_task_id(self) -> str | None:
        if self._worklog_configured():
            return self.worklog.current_task_id()

        current: list[str] = []
        for task in self._in_progress_tasks():
            task_id = str(getattr(task, "id", "") or "").strip()
            if not task_id or bool(getattr(task, "completed", False)):
                continue
            if self._latest_activity_action(task) in _CURRENT_ACTIONS:
                current.append(task_id)

        if len(current) > 1:
            raise AmbiguousError(
                "More than one Task is marked current by the Activity Journal; "
                "pause or complete the extra Task before continuing."
            )
        return current[0] if current else None

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
        current = self.current_task_id()
        paused: list[str] = []

        for task in self._in_progress_tasks():
            task_id = str(getattr(task, "id", "") or "").strip()
            if not task_id or task_id == current or bool(getattr(task, "completed", False)):
                continue

            if self._worklog_configured():
                try:
                    # Closed Assistant work segments prove this Task was actually
                    # worked on by this Assistant.  STATUS:IN-PROCESS alone does not.
                    if self.worklog.segments_for(task):
                        paused.append(task_id)
                except Exception:
                    continue
            elif self._latest_activity_action(task) == _PAUSED_ACTION:
                paused.append(task_id)

        return tuple(paused)

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

    # Production lifecycle persistence is performed by TaskService through either
    # WorkLogService or ActivityService.  These compatibility methods deliberately
    # keep no second mutable session store.
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
