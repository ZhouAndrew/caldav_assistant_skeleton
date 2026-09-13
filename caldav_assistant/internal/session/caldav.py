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
        _, latest = max(
            enumerate(items),
            key=lambda pair: (getattr(pair[1], "timestamp", 0), pair[0]),
        )
        return str(getattr(latest, "action", "") or "") or None

    def _activity_work_facts(self, tasks: Iterable[Any]) -> dict[str, Any]:
        """Return last locally observed work state without network access."""
        current: list[str] = []
        worked: list[str] = []
        for task in tasks:
            if not self._is_in_progress(task):
                continue
            task_id = str(getattr(task, "id", "") or "").strip()
            if not task_id:
                continue
            action = self._latest_activity_action(task)
            if action in _CURRENT_ACTIONS:
                current.append(task_id)
                worked.append(task_id)
            elif action == _PAUSED_ACTION:
                worked.append(task_id)
        if len(current) > 1:
            raise AmbiguousError(
                "More than one Task is marked current by the Activity Journal; "
                "pause or complete the extra Task before continuing."
            )
        return {
            "current_task_id": current[0] if current else None,
            "worked_task_ids": tuple(dict.fromkeys(worked)),
        }

    def cached_startup_snapshot(self, tasks: Iterable[Any]) -> dict[str, Any]:
        """Return cache-only work facts for the bounded startup fallback."""
        return self._activity_work_facts(tasks)

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

    def _fallback_paused_ids(
        self,
        tasks: Iterable[Any],
        *,
        current_id: str | None,
    ) -> tuple[str, ...]:
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

    def startup_work_facts(
        self,
        *,
        include_history: bool = False,
    ) -> dict[str, Any] | None:
        """Read only open Work VEVENT facts during interactive startup.

        Loading every closed interval made startup grow with Work history.  Current
        work needs only the open marker.  Other IN-PROCESS Tasks are conservatively
        excluded from the startup recommendation without claiming their exact paused
        history was read.
        """
        if not self._worklog_configured():
            return None
        reader = (
            getattr(self.worklog, "_all_work_events", None)
            if include_history
            else getattr(self.worklog, "open_snapshot", None)
        )
        full_history = include_history
        if not callable(reader):
            # Replacement WorkLog implementations retain their historical single
            # snapshot behavior.  Production exposes open_snapshot and stays
            # bounded independently of closed-history size.
            reader = getattr(self.worklog, "_all_work_events", None)
            full_history = True
        is_open = getattr(self.worklog, "_is_open", None)
        task_id_from_event = getattr(self.worklog, "_task_id_from_event", None)
        if not callable(reader) or not callable(is_open) or not callable(task_id_from_event):
            return None

        work_events = list(reader() or ())
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
        worked_ids = (
            tuple(
                str(task_id_from_event(item))
                for item in work_events
                if task_id_from_event(item) is not None
            )
            if full_history
            else None
        )
        return {
            "current_task_id": next(iter(current_ids)) if current_ids else None,
            "worked_task_ids": worked_ids,
        }

    def startup_snapshot(
        self,
        tasks: Iterable[Any],
        *,
        work_facts: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Resolve current/paused state from an already-read Task set.

        ``work_facts`` lets the caller overlap the Work VEVENT read with the Task and
        Event reads.  If it is absent, the historical compatible path is retained.
        """
        task_values = list(tasks or ())
        in_progress = [task for task in task_values if self._is_in_progress(task)]

        if self._worklog_configured():
            if isinstance(work_facts, dict):
                current_id = work_facts.get("current_task_id")
                worked_values = work_facts.get("worked_task_ids")
                if worked_values is None:
                    paused_ids = tuple(
                        task_id
                        for task in in_progress
                        for task_id in [str(getattr(task, "id", "") or "").strip()]
                        if task_id and task_id != current_id
                    )
                else:
                    worked_ids = {str(value) for value in worked_values}
                    paused_ids = tuple(
                        task_id
                        for task in in_progress
                        for task_id in [str(getattr(task, "id", "") or "").strip()]
                        if task_id and task_id != current_id and task_id in worked_ids
                    )
            else:
                reader = getattr(self.worklog, "_all_work_events", None)
                if not callable(reader):
                    current_id = self.current_task_id()
                    paused_ids = self._fallback_paused_ids(
                        in_progress,
                        current_id=current_id,
                    )
                else:
                    # Exact paused-state commands deliberately read closed Work
                    # history.  Only interactive startup uses the bounded OPEN
                    # query supplied through ``work_facts``.
                    facts = self.startup_work_facts(include_history=True)
                    if facts is None:
                        current_id = self.current_task_id()
                        paused_ids = self._fallback_paused_ids(
                            in_progress,
                            current_id=current_id,
                        )
                    else:
                        current_id = facts.get("current_task_id")
                        worked_ids = {str(value) for value in facts.get("worked_task_ids", ())}
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
