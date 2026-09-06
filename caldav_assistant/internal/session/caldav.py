"""Read human work-session state from explicit Assistant-owned facts.

When a Work VEVENT collection is configured, open/closed Assistant work segments are
the cross-device source for current/paused state. Without one, or while that CalDAV
collection is temporarily unavailable, the lightweight Activity Journal is the local
read fallback so the Assistant can still explain the last known work context.

A plain CalDAV ``STATUS:IN-PROCESS`` is never treated as proof that the Assistant
paused a Task; external CalDAV clients may legitimately use that standard status.
"""
from __future__ import annotations

from typing import Any, Iterable

from ...api.v1.errors import AmbiguousError, UnavailableError


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

    @staticmethod
    def _is_in_progress(task: Any) -> bool:
        return (
            str(getattr(task, "status", "") or "") == "IN-PROCESS"
            and not bool(getattr(task, "completed", False))
        )

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
        # Equal timestamps occur on coarse Windows clocks. Journal insertion order
        # provides the deterministic tie-breaker for start->pause/complete pairs.
        _, latest = max(
            enumerate(items),
            key=lambda pair: (getattr(pair[1], "timestamp", 0), pair[0]),
        )
        return str(getattr(latest, "action", "") or "") or None

    @staticmethod
    def _task_by_id(tasks: Iterable[Any], task_id: str | None) -> Any:
        if not task_id:
            return None
        wanted = str(task_id)
        for task in tasks:
            if str(getattr(task, "id", "") or "") == wanted:
                if bool(getattr(task, "completed", False)):
                    return None
                if str(getattr(task, "status", "") or "") == "CANCELLED":
                    return None
                return task
        return None

    def _activity_snapshot(
        self,
        task_values: list[Any],
        in_progress: list[Any],
    ) -> dict[str, Any]:
        """Resolve last locally observed current/paused state from Activity Journal."""
        current: list[str] = []
        paused: list[str] = []
        for task in in_progress:
            task_id = str(getattr(task, "id", "") or "").strip()
            if not task_id:
                continue
            action = self._latest_activity_action(task)
            if action in _CURRENT_ACTIONS:
                current.append(task_id)
            elif action == _PAUSED_ACTION:
                paused.append(task_id)

        if len(current) > 1:
            raise AmbiguousError(
                "More than one Task is marked current by the Activity Journal; "
                "pause or complete the extra Task before continuing."
            )
        current_id = current[0] if current else None
        return {
            "current_task_id": current_id,
            "current_task": self._task_by_id(task_values, current_id),
            "paused_task_ids": tuple(dict.fromkeys(paused)),
        }

    def _fallback_paused_ids(
        self,
        tasks: Iterable[Any],
        *,
        current_id: str | None,
    ) -> tuple[str, ...]:
        """Compatibility path for WorkLog replacements without snapshot bricks."""
        paused: list[str] = []
        seen: set[str] = set()
        configured = self._worklog_configured()

        for task in tasks:
            task_id = str(getattr(task, "id", "") or "").strip()
            if (
                not task_id
                or task_id in seen
                or task_id == current_id
                or bool(getattr(task, "completed", False))
            ):
                continue
            seen.add(task_id)

            if configured:
                try:
                    if self.worklog.segments_for(task):
                        paused.append(task_id)
                except Exception:
                    continue
            elif self._latest_activity_action(task) == _PAUSED_ACTION:
                paused.append(task_id)

        return tuple(paused)

    def startup_snapshot(self, tasks: Iterable[Any]) -> dict[str, Any]:
        """Resolve current/paused state from an already-read Task set."""
        task_values = list(tasks or ())
        in_progress = [task for task in task_values if self._is_in_progress(task)]

        if not self._worklog_configured():
            return self._activity_snapshot(task_values, in_progress)

        reader = getattr(self.worklog, "_all_work_events", None)
        if not callable(reader):
            try:
                current_id = self.current_task_id()
                paused_ids = self._fallback_paused_ids(
                    in_progress,
                    current_id=current_id,
                )
            except UnavailableError:
                return self._activity_snapshot(task_values, in_progress)
            return {
                "current_task_id": current_id,
                "current_task": self._task_by_id(task_values, current_id),
                "paused_task_ids": tuple(dict.fromkeys(paused_ids)),
            }

        try:
            work_events = list(reader() or ())
        except UnavailableError:
            # Work VEVENTs remain authoritative; this is only a read fallback while
            # that collection cannot be reached. Activity is never written back over
            # CalDAV and therefore cannot become a competing source of truth.
            return self._activity_snapshot(task_values, in_progress)

        is_open = getattr(self.worklog, "_is_open", None)
        task_id_from_event = getattr(self.worklog, "_task_id_from_event", None)
        if not callable(is_open) or not callable(task_id_from_event):
            try:
                current_id = self.current_task_id()
                paused_ids = self._fallback_paused_ids(
                    in_progress,
                    current_id=current_id,
                )
            except UnavailableError:
                return self._activity_snapshot(task_values, in_progress)
            return {
                "current_task_id": current_id,
                "current_task": self._task_by_id(task_values, current_id),
                "paused_task_ids": tuple(dict.fromkeys(paused_ids)),
            }

        open_items = [event for event in work_events if is_open(event)]
        current_ids = {
            task_id_from_event(item)
            for item in open_items
            if task_id_from_event(item) is not None
        }
        if len(open_items) > 1 or len(current_ids) > 1:
            raise AmbiguousError(
                "More than one open CalDAV work interval exists; "
                "close the extra interval before starting another Task."
            )
        current_id = next(iter(current_ids)) if current_ids else None
        worked_ids = {
            task_id_from_event(item)
            for item in work_events
            if task_id_from_event(item) is not None
        }
        paused_ids = tuple(
            task_id
            for task in in_progress
            for task_id in [str(getattr(task, "id", "") or "").strip()]
            if task_id and task_id != current_id and task_id in worked_ids
        )
        return {
            "current_task_id": current_id,
            "current_task": self._task_by_id(task_values, current_id),
            "paused_task_ids": tuple(dict.fromkeys(paused_ids)),
        }

    def current_task_id(self) -> str | None:
        if self._worklog_configured():
            try:
                return self.worklog.current_task_id()
            except UnavailableError:
                snapshot = self._activity_snapshot(
                    self._in_progress_tasks(),
                    self._in_progress_tasks(),
                )
                return snapshot["current_task_id"]

        current: list[str] = []
        seen: set[str] = set()
        for task in self._in_progress_tasks():
            task_id = str(getattr(task, "id", "") or "").strip()
            if (
                not task_id
                or task_id in seen
                or bool(getattr(task, "completed", False))
            ):
                continue
            seen.add(task_id)
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
        tasks = self._in_progress_tasks()
        return tuple(self.startup_snapshot(tasks)["paused_task_ids"])

    def paused_tasks(self) -> list[Any]:
        if self.tasks is None:
            return []
        tasks = self._in_progress_tasks()
        snapshot = self.startup_snapshot(tasks)
        paused = set(snapshot["paused_task_ids"])
        result: list[Any] = []
        seen: set[str] = set()
        for task in tasks:
            task_id = str(getattr(task, "id", "") or "").strip()
            if not task_id or task_id in seen or task_id not in paused:
                continue
            seen.add(task_id)
            result.append(task)
        return result

    # Production lifecycle persistence is performed by TaskService through either
    # WorkLogService or ActivityService. These compatibility methods deliberately
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
