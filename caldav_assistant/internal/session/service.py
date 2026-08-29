"""Human work-session state for CalDAV Assistant.

A planned Task is not automatically something the user is working on. This
service keeps the tiny Assistant-owned state that answers the human questions
"what am I doing now?" and "what did I pause?". Task/Event facts remain in
CalDAV; only UIDs and work-session state live here.
"""
from __future__ import annotations

from typing import Any


class SessionService:
    CURRENT_TASK_KEY = "current_task_uid"
    PAUSED_TASKS_KEY = "paused_task_uids"

    def __init__(self, state: Any = None, tasks: Any = None) -> None:
        self.state = state
        self.tasks = tasks
        # Retained as lightweight UI/session scratch fields for compatibility.
        self.last_items: list[Any] = []
        self.current_selection: Any = None

    def bind_tasks(self, tasks: Any) -> None:
        self.tasks = tasks

    def _get(self, key: str, default: Any = None) -> Any:
        if self.state is None:
            return default
        getter = getattr(self.state, "get", None)
        if callable(getter):
            try:
                return getter(key, default)
            except TypeError:
                value = getter(key)
                return default if value is None else value
        if isinstance(self.state, dict):
            return self.state.get(key, default)
        return default

    def _set(self, key: str, value: Any) -> None:
        if self.state is None:
            return
        setter = getattr(self.state, "set", None)
        if callable(setter):
            setter(key, value)
            return
        if isinstance(self.state, dict):
            self.state[key] = value

    def _delete(self, key: str) -> None:
        if self.state is None:
            return
        deleter = getattr(self.state, "delete", None)
        if callable(deleter):
            deleter(key)
            return
        if isinstance(self.state, dict):
            self.state.pop(key, None)

    def _recover_legacy_current_task_id(self) -> str | None:
        """Recover pre-session IN-PROCESS state only when the answer is unique.

        Older builds could write ``STATUS:IN-PROCESS`` without persisting
        ``current_task_uid``. After upgrading, silently choosing among several such
        Tasks would be dangerous, so recovery occurs only when exactly one
        non-paused IN-PROCESS Task exists.
        """
        if self.tasks is None:
            return None
        try:
            candidates = list(self.tasks.list(status="IN-PROCESS"))
        except Exception:
            return None

        paused = set(self.paused_task_ids())
        eligible = [
            task
            for task in candidates
            if str(getattr(task, "id", "") or "").strip()
            and str(getattr(task, "id", "")) not in paused
            and not bool(getattr(task, "completed", False))
            and str(getattr(task, "status", "")) != "CANCELLED"
        ]
        if len(eligible) != 1:
            return None

        uid = str(getattr(eligible[0], "id", "") or "").strip()
        if not uid:
            return None
        self._set(self.CURRENT_TASK_KEY, uid)
        return uid

    def current_task_id(self) -> str | None:
        value = self._get(self.CURRENT_TASK_KEY, None)
        if value:
            return str(value)
        return self._recover_legacy_current_task_id()

    def current_task(self) -> Any:
        uid = self.current_task_id()
        if uid is None or self.tasks is None:
            return None
        try:
            task = self.tasks.get(uid)
        except Exception:
            self.clear_current()
            return None
        if getattr(task, "completed", False) or getattr(task, "status", "") == "CANCELLED":
            self.clear_current()
            return None
        return task

    def paused_task_ids(self) -> tuple[str, ...]:
        raw = self._get(self.PAUSED_TASKS_KEY, [])
        if not isinstance(raw, (list, tuple)):
            return ()
        result: list[str] = []
        for value in raw:
            text = str(value).strip()
            if text and text not in result:
                result.append(text)
        return tuple(result)

    def paused_tasks(self) -> list[Any]:
        if self.tasks is None:
            return []
        result: list[Any] = []
        valid_ids: list[str] = []
        for uid in self.paused_task_ids():
            try:
                task = self.tasks.get(uid)
            except Exception:
                continue
            if getattr(task, "completed", False) or getattr(task, "status", "") == "CANCELLED":
                continue
            result.append(task)
            valid_ids.append(uid)
        if tuple(valid_ids) != self.paused_task_ids():
            self._set(self.PAUSED_TASKS_KEY, valid_ids)
        return result

    def set_current(self, task: Any) -> None:
        uid = str(getattr(task, "id", task) or "").strip()
        if not uid:
            raise ValueError("current task must have an id")
        self._set(self.CURRENT_TASK_KEY, uid)
        paused = [item for item in self.paused_task_ids() if item != uid]
        self._set(self.PAUSED_TASKS_KEY, paused)

    def clear_current(self, task: Any = None) -> None:
        if task is not None:
            uid = str(getattr(task, "id", task) or "").strip()
            stored = self._get(self.CURRENT_TASK_KEY, None)
            if uid and stored and str(stored) != uid:
                return
        self._delete(self.CURRENT_TASK_KEY)

    def mark_paused(self, task: Any) -> None:
        uid = str(getattr(task, "id", task) or "").strip()
        if not uid:
            raise ValueError("paused task must have an id")
        self.clear_current(uid)
        paused = [item for item in self.paused_task_ids() if item != uid]
        paused.insert(0, uid)
        self._set(self.PAUSED_TASKS_KEY, paused)

    def unpause(self, task: Any) -> None:
        uid = str(getattr(task, "id", task) or "").strip()
        paused = [item for item in self.paused_task_ids() if item != uid]
        self._set(self.PAUSED_TASKS_KEY, paused)

    def forget(self, task: Any) -> None:
        uid = str(getattr(task, "id", task) or "").strip()
        self.clear_current(uid)
        self.unpause(uid)


__all__ = ["SessionService"]
