"""Canonical Task business service.

MODULE CONTRACT
- Imports/calls: public Task/ActionResult/errors + CalDAVAdapter + injected
  ActivityService/UndoManager collaborators.
- Provides: TaskService query and mutation actions.
- Must not: access CalDAV XML/HTTP directly, read/write SQLite directly, print CLI
  output, or contain Event/Agenda/Reminder/WordPress logic.

CalDAV remains the source of truth.  Mutations are considered successful only after
CalDAVAdapter confirms them.  Activity/Undo side effects happen afterwards.
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
    """Canonical Task business layer above :class:`CalDAVAdapter`."""

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
    _PAUSED_PROPERTY = "X-CALDAV-ASSISTANT-PAUSED"

    def __init__(
        self,
        adapter: CalDAVAdapter,
        activity: Any = None,
        undo: Any = None,
    ) -> None:
        self.adapter = adapter
        self.activity = activity
        self.undo = undo

    # ------------------------------------------------------------------
    # Small reusable bricks
    # ------------------------------------------------------------------
    def _bind(self, task: Task) -> Task:
        """Attach object convenience methods to this canonical service."""
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
                # datetime is intentionally accepted as well; it subclasses date.
                if value is not None and not isinstance(value, date):
                    raise ValidationError(
                        f"{key} must be date, datetime, or None"
                    )

        if "completed_at" in normalized:
            value = normalized["completed_at"]
            if value is not None and not isinstance(value, datetime):
                raise ValidationError("completed_at must be datetime or None")

        if "completed" in normalized and not isinstance(
            normalized["completed"], bool
        ):
            raise ValidationError("completed must be bool")

        if "priority" in normalized:
            value = normalized["priority"]
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value <= 9
            ):
                raise ValidationError(
                    "priority must be an integer from 0 to 9 or None"
                )

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
                raise ValidationError(
                    "completed=True requires STATUS:COMPLETED"
                )

        if status_present:
            if status == "COMPLETED":
                normalized.setdefault("completed", True)
                normalized.setdefault(
                    "completed_at", datetime.now(timezone.utc)
                )
            else:
                normalized.setdefault("completed", False)
                normalized.setdefault("completed_at", None)
        elif completed is True:
            normalized["status"] = "COMPLETED"
            normalized.setdefault("completed_at", datetime.now(timezone.utc))

        return normalized

    @classmethod
    def _copy_for_create(cls, value: Task) -> Task:
        """Validate a detached Task without mutating the caller's object."""
        task = replace(value, categories=list(value.categories), _service=None)
        task.summary = cls._validate_summary(task.summary)

        # A Task constructed with only status="COMPLETED" still carries the
        # dataclass defaults completed=False/completed_at=None.  Normalize that
        # convenience case before validating the complete public field set.
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
        """Keep only reconstructable Task facts; never persist ``raw`` here."""
        return {
            "id": task.id,
            **{
                name: deepcopy(getattr(task, name))
                for name in cls._MUTABLE_FIELDS
            },
        }

    def _record(self, action: str, task: Task, **metadata: Any) -> None:
        if self.activity is not None:
            self.activity.record(action, task.id, **metadata)

    def _remember(self, payload: dict[str, Any]) -> bool:
        if self.undo is None:
            return False
        self.undo.remember(payload)
        return True

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def list(self, **filters: Any) -> list[Task]:
        return [self._bind(task) for task in self.adapter.list_tasks(**filters)]

    def find(self, query: str, **filters: Any) -> Task:
        if not isinstance(query, str) or not query.strip():
            raise ValidationError("Task query must not be empty")

        needle = query.strip().casefold()
        items = self.list(**filters)

        # Prefer a unique exact title over broader substring matches.
        exact = [
            task for task in items if task.summary.casefold() == needle
        ]
        matches = exact or [
            task for task in items if needle in task.summary.casefold()
        ]

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
            # Concrete adapters should normally raise stable public errors, but
            # mapping KeyError here keeps simple/fake adapters inside the v1 model.
            raise NotFoundError(task) from exc

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------
    def create(self, summary: Task | str, **fields: Any) -> ActionResult:
        if isinstance(summary, Task):
            if fields:
                raise ValidationError(
                    "Do not pass fields when creating from a Task object"
                )
            candidate = self._copy_for_create(summary)
        else:
            if not isinstance(summary, str):
                raise ValidationError("Task summary must be text")
            unknown = set(fields) - self._MUTABLE_FIELDS
            if unknown:
                raise ValidationError(
                    f"Unsupported Task fields: {', '.join(sorted(unknown))}"
                )
            candidate = Task(
                summary=self._validate_summary(summary),
                **fields,
            )
            candidate = self._copy_for_create(candidate)

        # CalDAV is authoritative: no Activity/Undo is written before this succeeds.
        created = self._bind(self.adapter.create_task(candidate))
        self._require_id(created)

        undo_available = self._remember(
            {"action": "task.create", "task_id": created.id}
        )
        self._record("task_created", created)
        return ActionResult(
            True,
            affected=created,
            undo_available=undo_available,
        )

    def _update(
        self,
        task: Task | str,
        changes: dict[str, Any],
        *,
        activity_action: str = "task_updated",
        validate: bool = True,
        undo: bool = True,
    ) -> ActionResult:
        obj = self.get(task)
        task_id = self._require_id(obj)
        normalized = (
            self._normalize_changes(changes) if validate else dict(changes)
        )

        # Capture the authoritative object as seen before the mutation, but do not
        # mutate it locally.  A conflict/failure therefore cannot create a false
        # in-memory success state.
        before = {
            key: deepcopy(getattr(obj, key))
            for key in normalized
            if key in self._MUTABLE_FIELDS
        }

        updated = self._bind(
            self.adapter.update_task(task_id, normalized)
        )

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

        self._record(
            activity_action,
            updated,
            changes=deepcopy(normalized),
        )
        return ActionResult(
            True,
            affected=updated,
            undo_available=undo_available,
        )

    def update(self, task: Task | str, **changes: Any) -> ActionResult:
        action = (
            "task_due_changed"
            if set(changes) == {"due"}
            else "task_updated"
        )
        return self._update(task, changes, activity_action=action)

    def complete(self, task: Task | str) -> ActionResult:
        return self._update(
            task,
            {
                "status": "COMPLETED",
                "completed": True,
                "completed_at": datetime.now(timezone.utc),
            },
            activity_action="task_completed",
        )

    def start(self, task: Task | str) -> ActionResult:
        return self._update(
            task,
            {
                "status": "IN-PROCESS",
                "completed": False,
                "completed_at": None,
            },
            activity_action="task_started",
        )

    def pause(self, task: Task | str) -> ActionResult:
        obj = self.get(task)
        if obj.status != "IN-PROCESS":
            raise ValidationError("Only an in-process Task can be paused")

        # This is a Task business rule, not SyncEngine state.  The adapter decides
        # how the boolean becomes an iCalendar X-property on the wire.
        return self._update(
            obj,
            {self._PAUSED_PROPERTY: True},
            activity_action="task_paused",
            validate=False,
            undo=False,
        )

    def resume(self, task: Task | str) -> ActionResult:
        return self._update(
            task,
            {
                "status": "IN-PROCESS",
                self._PAUSED_PROPERTY: False,
            },
            activity_action="task_resumed",
            validate=False,
            undo=False,
        )

    def delete(self, task: Task | str) -> ActionResult:
        obj = self.get(task)
        task_id = self._require_id(obj)
        snapshot = self._snapshot(obj)

        self.adapter.delete_task(task_id)

        undo_available = self._remember(
            {
                "action": "task.delete",
                "task_id": task_id,
                "task": snapshot,
            }
        )
        self._record("task_deleted", obj)
        return ActionResult(
            True,
            affected=obj,
            undo_available=undo_available,
        )