"""Read human work-session state from explicit Assistant-owned facts.

When a Work VEVENT collection is configured, open/closed Assistant work segments are
the cross-device source for current/paused state.  Without one, the lightweight
Activity Journal is a local fallback so Task lifecycle commands remain usable.

A plain CalDAV ``STATUS:IN-PROCESS`` is never treated as proof that the Assistant
paused a Task; external CalDAV clients may legitimately use that standard status.
"""
from __future__ import annotations

from typing import Any, Iterable

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
        # Activity repositories return journal rows in chronological insertion order.
        # Windows clocks can legitimately give start/pause (or resume/complete) the
        # exact same timestamp.  Timestamp-only max() then kept the first row and
        # made a just-paused Task still look current.  Preserve chronological ordering
        # while using the later journal row as the deterministic tie-breaker.
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

    def startup_snapshot(self, tasks: Iterable[Any]) -> dict[str, Any]:
        """Resolve current/paused state from an already-read Task set.

        Startup used to ask ``current_task_id()``, ``paused_task_ids()`` and then
        ``tasks.get()`` independently.  With a CalDAV Work collection that caused
        repeated full Work VEVENT scans plus another Task traversal.  This internal
        composition reads the Work facts once and reuses the Tasks already fetched
        for Agenda.  No state is cached or promoted to a second source of truth.
        """
        task_values = list(tasks or ())
        in_progress = [task for task in task_values if self._is_in_progress(task)]

        if self._worklog_configured():
            reader = getattr(self.worklog, "_all_work_events", None)
            if not callable(reader):
                current_id = self.current_task_id()
                paused_ids = self.paused_task_ids()
            else:
                work_events = list(reader() or ())
                is_open = getattr(self.worklog, "_is_open", None)
                task_id_from_event = getattr(self.worklog, "_task_id_from_event", None)
                if not callable(is_open) or not callable(task_id_from_event):
                    current_id = self.current_task_id()
                    paused_ids = self.paused_task_ids()
                else:
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
        else:
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
            paused_ids = tuple(paused)

        return {
            "current_task_id": current_id,
            "current_task": self._task_by_id(task_values, current_id),
            "paused_task_ids": tuple(dict.fromkeys(paused_ids)),
        }

    def current_task_id(self) -> str | None:
        if self._worklog_configured():
            return self.worklog.current_task_id()

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
        current = self.current_task_id()
        paused: list[str] = []
        seen: set[str] = set()

        for task in self._in_progress_tasks():
            task_id = str(getattr(task, "id", "") or "").strip()
            if (
                not task_id
                or task_id in seen
                or task_id == current
                or bool(getattr(task, "completed", False))
            ):
                continue
            seen.add(task_id)

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
