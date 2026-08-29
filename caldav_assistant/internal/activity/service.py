"""Lightweight Assistant Activity Journal service.

MODULE CONTRACT
- Imports/calls: public Activity/Task models + stable validation errors + public
  Hook/Event emitter + injected ActivityRepository collaborator.
- Provides: ActivityService.record(), today(), and for_task().
- Must not: read/write SQLite directly, inspect or mutate CalDAV Task/Event state,
  create WordPress posts, print CLI output, or infer authoritative object status
  from journal entries.

The Activity Journal records Assistant behaviour history only.  CalDAV remains the
source of truth for Task/Event state.  Selected successful lifecycle records may
also publish Full Extension hooks; extensions decide whether those hooks cause any
secondary integration such as WordPress logging.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
from typing import Any, Callable

from ...api import Activity, Task
from ...api.v1.errors import ValidationError
from ...api.v1.hooks import emit


_TASK_LIFECYCLE_HOOKS = {
    "task_started": "task.started",
    "task_resumed": "task.resumed",
}


class ActivityService:
    """Canonical application service for the lightweight Activity Journal."""

    def __init__(
        self,
        repo: Any,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repo = repo
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------
    # Small reusable bricks
    # ------------------------------------------------------------------
    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise TypeError("ActivityService clock must return datetime")

        # Older callers/tests may provide a naive local datetime.  Make the
        # assumption explicit at this boundary, then store new records in UTC.
        if value.tzinfo is None:
            value = value.astimezone()
        return value.astimezone(timezone.utc)

    @staticmethod
    def _normalize_action(action: Any) -> str:
        if not isinstance(action, str) or not action.strip():
            raise ValidationError("Activity action must not be empty")
        return action.strip()

    @staticmethod
    def _object_id(value: Any, *, required: bool = False) -> str | None:
        if value is None:
            if required:
                raise ValidationError("Activity object id must not be empty")
            return None

        # Public callers commonly pass Task objects to for_task(); internal
        # services normally pass the already-authoritative UID string to record().
        candidate = getattr(value, "id", value)
        if not isinstance(candidate, str) or not candidate.strip():
            raise ValidationError("Activity object id must not be empty")
        return candidate.strip()

    @staticmethod
    def _as_activity_list(items: Any) -> list[Activity]:
        values = list(items or ())
        if not all(isinstance(item, Activity) for item in values):
            raise TypeError("ActivityRepository must return Activity objects")
        return values

    @staticmethod
    def _emit_lifecycle_hook(item: Activity) -> None:
        event_name = _TASK_LIFECYCLE_HOOKS.get(item.action)
        if event_name is None:
            return
        try:
            emit(
                event_name,
                payload={"activity": item},
                source="activity-journal",
            )
        except Exception:
            # The journal row is already durable and the authoritative Task action
            # already happened.  Extension infrastructure must never reverse it.
            return

    # ------------------------------------------------------------------
    # Public Object API
    # ------------------------------------------------------------------
    def record(
        self,
        action: str,
        object_id: str | None = None,
        **metadata: Any,
    ) -> Activity:
        """Persist one minimal Assistant behaviour event and return it.

        This method never changes Task/Event state.  Upstream business services
        must first complete their authoritative operation, then call record().
        """
        normalized_action = self._normalize_action(action)
        normalized_object_id = self._object_id(object_id)
        timestamp = self._now()
        safe_metadata = deepcopy(metadata)

        item = Activity(
            timestamp=timestamp,
            action=normalized_action,
            object_id=normalized_object_id,
            metadata=safe_metadata,
        )

        # Repository failure is visible to the caller.  Returning a fabricated
        # success would make the journal claim history that was never persisted.
        self.repo.record(
            item.timestamp,
            item.action,
            item.object_id,
            deepcopy(item.metadata),
        )
        self._emit_lifecycle_hook(item)
        return item

    def today(self) -> list[Activity]:
        """Return activities for the current *local* calendar day.

        Storage timestamps are normalized to UTC, while the meaning of "today"
        follows the machine's local timezone.  The repository only receives an
        explicit half-open UTC range and therefore owns no UI/timezone policy.
        """
        now_utc = self._now()
        local_now = now_utc.astimezone()
        local_tz = local_now.tzinfo
        assert local_tz is not None

        start_local = datetime.combine(local_now.date(), time.min, tzinfo=local_tz)
        end_local = start_local + timedelta(days=1)

        start_utc = start_local.astimezone(timezone.utc)
        end_utc = end_local.astimezone(timezone.utc)
        return self._as_activity_list(self.repo.between(start_utc, end_utc))

    def for_task(self, task: Task | str) -> list[Activity]:
        """Return journal history associated with a Task UID.

        The method deliberately does not fetch the Task from CalDAV and does not
        interpret activity actions as current Task state.
        """
        task_id = self._object_id(task, required=True)
        assert task_id is not None
        return self._as_activity_list(self.repo.for_object(task_id))