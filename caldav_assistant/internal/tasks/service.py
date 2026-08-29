"""Canonical Task business service.

MODULE CONTRACT
- Imports/calls: public Task/ActionResult/errors + CalDAVAdapter + injected
  ActivityService/UndoManager/SessionService collaborators.
- Provides: TaskService query and mutation actions.
- Must not: access CalDAV XML/HTTP directly, read/write SQLite directly, print CLI
  output, or contain Event/Agenda/Reminder/WordPress logic.

CalDAV remains the Task source of truth.  The Assistant-owned work-session stores
only which task the human is actively working on or has temporarily paused.
Activity Journal entries describe successful planning changes and human work-session
transitions; they never replace authoritative Task state.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Any

from ...api import ActionResult, Task
from ...api.v1.errors import AmbiguousError, NotFoundError, ValidationError
from ..caldav.adapter import CalDAVAdapter


class TaskService:
    """Canonical Task business layer above :class:`CalDAVAdapter`.

    ``start`` means begin working on a Task *now*.  It is deliberately unrelated
    to the Task's planned ``DTSTART`` value.  ``pause`` and ``resume`` operate on
    Assistant work-session state; a merely planned Task cannot be paused.
    """

    _MUTABLE_FIELDS = frozenset(
        {
            "summary",
            "description",
            "start",
            "due",
            "status",
            "completed",
            "completed_at",
            "priority",
            "categories",
        }
    )
    _STATUSES = frozenset(
        {"NEEDS-ACTION", "IN-PROCESS", "COMPLETED", "CANCELLED"}
    )

    def __init__(
        self,
        adapter: CalDAVAdapter,
        activity: Any = None,
        undo: Any = None,
        session: Any = None,
    ) -> None:
        self.adapter = adapter
        self.activity = activity
        self.undo = undo
        self.session = session

    def _bind(self, task: Task) -> Task:
        if not isinstance(task, Task):
            raise TypeError("CalDAVAdapter must return Task objects")
        task._service = self
        return task

    @staticmethod
    def _require_id(task: Task) -> str:
        task_id = str(task.id or "").strip()
        if not task_id:
            raise ValidationError("Task has no id")
        return task_id

    @staticmethod
    def _validate_summary(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("Task summary must not be empty")
        return value.strip()

    @classmethod
    def _normalize_changes(cls, changes: dict[str, Any]) -> dict[str, Any]:
        if not changes:
            raise ValidationError("No task changes supplied")

        unknown = set(changes) - cls._MUTABLE_FIELDS
        if unknown:
            raise ValidationError(
                f"Unsupported Task fields: {', '.join(sorted(unknown))}"
            )

        normalized = dict(changes)

        if "summary" in normalized:
            normalized["summary"] = cls._validate_summary(normalized["summary"])

        for key in ("start", "due"):
            if key in normalized:
                value = normalized[key]
                if value is not None and not isinstance(value, date):
                    raise ValidationError(f"{key} must be date, datetime, or None")

        if "completed_at" in normalized:
            value = normalized["completed_at"]
            if value is not None and not isinstance(value, datetime):
                raise ValidationError("completed_at must be datetime or None")

        if "completed" in normalized and not isinstance(normalized["completed"], bool):
            raise ValidationError("completed must be bool")

        if "priority" in normalized:
            value = normalized["priority"]
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value <= 9
            ):
                raise ValidationError("priority must be an integer from 0 to 9 or None")

        if "categories" in normalized:
            value = normalized["categories"]
            if not isinstance(value, (list, tuple)) or not all(
                isinstance(item, str) for item in value
            ):
                raise ValidationError("categories must contain strings")
            normalized["categories"] = list(value)

        status_present = "status" in normalized
        completed_present = "completed" in normalized
        status = normalized.get("status")
        completed = normalized.get("completed")

        if status_present and status not in cls._STATUSES:
            raise ValidationError(f"Unsupported Task status: {status}")

        if status_present and completed_present:
            if status == "COMPLETED" and completed is False:
                raise ValidationError(
                    "STATUS:COMPLETED cannot be combined with completed=False"
                )
            if status != "COMPLETED" and completed is True:
                raise ValidationError("completed=True requires STATUS:COMPLETED")

        if status_present:
            if status == "COMPLETED":
                normalized.setdefault("completed", True)
                normalized.setdefault("completed_at", datetime.now(timezone.utc))
            else:
                normalized.setdefault("completed", False)
                normalized.setdefault("completed_at", None)
        elif completed is True:
            normalized["status"] = "COMPLETED"
            normalized.setdefault("completed_at", datetime.now(timezone.utc))

        return normalized

    @classmethod
    def _copy_for_create(cls, value: Task) -> Task:
        task = replace(value, categories=list(value.categories), _service=None)
        task.summary = cls._validate_summary(task.summary)
        if task.status == "COMPLETED" and not task.completed:
            task.completed = True
        elif task.completed and task.status != "COMPLETED":
            task.status = "COMPLETED"

        validated = cls._normalize_changes(
            {name: getattr(task, name) for name in cls._MUTABLE_FIELDS}
        )
        for name, item in validated.items():
            setattr(task, name, item)
        return task

    @classmethod
    def _snapshot(cls, task: Task) -> dict[str, Any]:
        return {
            "id": task.id,
            **{
                name: deepcopy(getattr(task, name))
                for name in cls._MUTABLE_FIELDS
            },
        }

    @staticmethod
    def _plan_context(task: Task) -> dict[str, Any]:
        """Small planning snapshot attached to human work-session events."""
        return {
            "planned_start": deepcopy(task.start),
            "due": deepcopy(task.due),
            "priority": deepcopy(task.priority),
        }

    def _record(self, action: str, task: Task, **metadata: Any) -> None:
        if self.activity is not None:
            self.activity.record(action, task.id, **metadata)

    def _remember(self, payload: dict[str, Any]) -> bool:
        if self.undo is None:
            return False
        self.undo.remember(payload)
        return True

    def _session_current_id(self) -> str | None:
        if self.session is None:
            return None
        getter = getattr(self.session, "current_task_id", None)
        return getter() if callable(getter) else None

    def _session_paused_ids(self) -> tuple[str, ...]:
        if self.session is None:
            return ()
        getter = getattr(self.session, "paused_task_ids", None)
        return tuple(getter()) if callable(getter) else ()

    def list(self, **filters: Any) -> list[Task]:
        return [self._bind(task) for task in self.adapter.list_tasks(**filters)]

    def find(self, query: str, **filters: Any) -> Task:
        if not isinstance(query, str) or not query.strip():
            raise ValidationError("Task query must not be empty")

        needle = query.strip().casefold()
        items = self.list(**filters)
        exact = [task for task in items if task.summary.casefold() == needle]
        matches = exact or [task for task in items if needle in task.summary.casefold()]

        if not matches:
            raise NotFoundError(query)
        if len(matches) > 1:
            raise AmbiguousError(query)
        return matches[0]

    def get(self, task: Task | str) -> Task:
        if isinstance(task, Task):
            return self._bind(task)
        if not isinstance(task, str) or not task.strip():
            raise ValidationError("Task id must not be empty")

        try:
            return self._bind(self.adapter.get_task(task.strip()))
        except KeyError as exc:
            raise NotFoundError(task) from exc

    def create(self, summary: Task | str, **fields: Any) -> ActionResult:
        if isinstance(summary, Task):
            if fields:
                raise ValidationError("Do not pass fields when creating from a Task object")
            candidate = self._copy_for_create(summary)
        else:
            if not isinstance(summary, str):
                raise ValidationError("Task summary must be text")
            unknown = set(fields) - self._MUTABLE_FIELDS
            if unknown:
                raise ValidationError(
                    f"Unsupported Task fields: {', '.join(sorted(unknown))}"
                )
            candidate = Task(summary=self._validate_summary(summary), **fields)
            candidate = self._copy_for_create(candidate)

        created = self._bind(self.adapter.create_task(candidate))
        self._require_id(created)
        undo_available = self._remember({"action": "task.create", "task_id": created.id})
        self._record("task_created", created, after=self._snapshot(created))
        return ActionResult(True, affected=created, undo_available=undo_available)

    def _update(
        self,
        task: Task | str,
        changes: dict[str, Any],
        *,
        activity_action: str | None = "task_updated",
        activity_metadata: dict[str, Any] | None = None,
        validate: bool = True,
        undo: bool = True,
    ) -> ActionResult:
        obj = self.get(task)
        task_id = self._require_id(obj)
        normalized = self._normalize_changes(changes) if validate else dict(changes)

        before = {
            key: deepcopy(getattr(obj, key))
            for key in normalized
            if key in self._MUTABLE_FIELDS
        }
        updated = self._bind(self.adapter.update_task(task_id, normalized))

        undo_available = False
        if undo:
            undo_available = self._remember(
                {
                    "action": "task.update",
                    "task_id": task_id,
                    "before": before,
                    "after": deepcopy(normalized),
                }
            )

        if activity_action is not None:
            metadata = dict(activity_metadata or {})
            metadata.update(
                {
                    "before": deepcopy(before),
                    "after": deepcopy(normalized),
                    "changes": deepcopy(normalized),
                }
            )
            self._record(activity_action, updated, **metadata)
        return ActionResult(True, affected=updated, undo_available=undo_available)

    def update(self, task: Task | str, **changes: Any) -> ActionResult:
        keys = set(changes)
        if keys == {"start"}:
            action = "task_planned_start_changed"
        elif keys == {"due"}:
            action = "task_due_changed"
        elif keys == {"priority"}:
            action = "task_priority_changed"
        else:
            action = "task_updated"
        return self._update(task, changes, activity_action=action)

    def complete(self, task: Task | str) -> ActionResult:
        obj = self.get(task)
        task_id = self._require_id(obj)
        work_session_before = (
            "current"
            if self._session_current_id() == task_id
            else "paused"
            if task_id in self._session_paused_ids()
            else "none"
        )
        result = self._update(
            obj,
            {
                "status": "COMPLETED",
                "completed": True,
                "completed_at": datetime.now(timezone.utc),
            },
            activity_action=None,
        )
        if self.session is not None:
            forget = getattr(self.session, "forget", None)
            if callable(forget):
                forget(result.affected)
        self._record(
            "task_completed",
            result.affected,
            work_session_before=work_session_before,
            work_session_after="none",
            **self._plan_context(obj),
        )
        return result

    def start(self, task: Task | str) -> ActionResult:
        obj = self.get(task)
        task_id = self._require_id(obj)
        if obj.completed or obj.status in {"COMPLETED", "CANCELLED"}:
            raise ValidationError("A completed or cancelled Task cannot be started")

        current_id = self._session_current_id()
        if current_id == task_id:
            raise ValidationError("This Task is already the current work")
        if current_id and current_id != task_id:
            raise ValidationError(
                "Another Task is currently being worked on; pause or complete it before starting a different Task"
            )

        result = self._update(
            obj,
            {
                "status": "IN-PROCESS",
                "completed": False,
                "completed_at": None,
            },
            activity_action=None,
        )
        if self.session is not None:
            setter = getattr(self.session, "set_current", None)
            if callable(setter):
                setter(result.affected)
        self._record(
            "task_started",
            result.affected,
            work_session_before="none",
            work_session_after="current",
            **self._plan_context(obj),
        )
        return result

    def pause(self, task: Task | str) -> ActionResult:
        obj = self.get(task)
        task_id = self._require_id(obj)
        if obj.status != "IN-PROCESS":
            raise ValidationError("A planned Task is not running and cannot be paused")

        if self.session is not None and self._session_current_id() != task_id:
            raise ValidationError("Only the Task you are working on now can be paused")

        if self.session is not None:
            marker = getattr(self.session, "mark_paused", None)
            if callable(marker):
                marker(obj)
        self._record(
            "task_paused",
            obj,
            work_session_before="current",
            work_session_after="paused",
            **self._plan_context(obj),
        )
        return ActionResult(True, affected=obj, undo_available=False)

    def resume(self, task: Task | str) -> ActionResult:
        obj = self.get(task)
        task_id = self._require_id(obj)
        if obj.completed or obj.status in {"COMPLETED", "CANCELLED"}:
            raise ValidationError("A completed or cancelled Task cannot be resumed")

        current_id = self._session_current_id()
        if current_id and current_id != task_id:
            raise ValidationError(
                "Another Task is currently being worked on; pause or complete it before resuming this Task"
            )
        if self.session is not None and task_id not in self._session_paused_ids():
            raise ValidationError("Only a Task you previously paused can be resumed")

        # STATUS may already be IN-PROCESS; writing the standard fields again makes
        # recovery deterministic if another CalDAV client altered the task meanwhile.
        result = self._update(
            obj,
            {
                "status": "IN-PROCESS",
                "completed": False,
                "completed_at": None,
            },
            activity_action=None,
            undo=False,
        )
        if self.session is not None:
            setter = getattr(self.session, "set_current", None)
            if callable(setter):
                setter(result.affected)
        self._record(
            "task_resumed",
            result.affected,
            work_session_before="paused",
            work_session_after="current",
            **self._plan_context(obj),
        )
        return result

    def delete(self, task: Task | str) -> ActionResult:
        obj = self.get(task)
        task_id = self._require_id(obj)
        snapshot = self._snapshot(obj)
        work_session_before = (
            "current"
            if self._session_current_id() == task_id
            else "paused"
            if task_id in self._session_paused_ids()
            else "none"
        )

        self.adapter.delete_task(task_id)

        undo_available = self._remember(
            {"action": "task.delete", "task_id": task_id, "task": snapshot}
        )
        if self.session is not None:
            forget = getattr(self.session, "forget", None)
            if callable(forget):
                forget(obj)
        self._record(
            "task_deleted",
            obj,
            before=snapshot,
            work_session_before=work_session_before,
            work_session_after="none",
        )
        return ActionResult(True, affected=obj, undo_available=undo_available)
