"""CalDAV-backed human work history.

Work history is authoritative CalDAV data, not Assistant-local journal state.
Each active work interval is represented by a VEVENT in the user-selected work-log
collection. An open interval has DTSTART and the open marker category; pause/done
closes it with DTEND. Resume creates a new interval.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from ...api import Event, Task
from ...api.v1.errors import AmbiguousError, NotFoundError, ValidationError
from ..progress import emit_progress


class WorkLogService:
    CATEGORY = "caldav-assistant-work"
    OPEN_CATEGORY = "caldav-assistant-work-open"
    DESCRIPTION_HEADER = "CalDAV Assistant Work Segment"
    TASK_PREFIX = "Task-UID: "

    def __init__(
        self,
        adapter: Any,
        collection_url_provider: Callable[[], str | None],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.adapter = adapter
        self.collection_url_provider = collection_url_provider
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise TypeError("WorkLogService clock must return datetime")
        if value.tzinfo is None:
            value = value.astimezone()
        return value.astimezone(timezone.utc)

    def configured(self) -> bool:
        value = self.collection_url_provider()
        return isinstance(value, str) and bool(value.strip())

    def _collection_url(self, *, required: bool = True) -> str | None:
        value = self.collection_url_provider()
        if not isinstance(value, str) or not value.strip():
            if not required:
                return None
            raise ValidationError(
                "Work log collection is not configured. Start/Pause/Resume records "
                "work history as CalDAV events; choose one in Settings > CalDAV > "
                "Collection roles > Work log collection. WordPress is not required."
            )
        return value.strip()

    @classmethod
    def _description(cls, task_id: str) -> str:
        return f"{cls.DESCRIPTION_HEADER}\n{cls.TASK_PREFIX}{task_id}"

    @classmethod
    def _task_id_from_event(cls, event: Event) -> str | None:
        lines = str(event.description or "").splitlines()
        if not lines or lines[0].strip() != cls.DESCRIPTION_HEADER:
            return None
        for line in lines[1:]:
            if line.startswith(cls.TASK_PREFIX):
                value = line[len(cls.TASK_PREFIX):].strip()
                return value or None
        return None

    @classmethod
    def _is_work_event(cls, event: Event) -> bool:
        return (
            cls.CATEGORY in set(event.categories or ())
            and cls._task_id_from_event(event) is not None
        )

    @classmethod
    def _is_open(cls, event: Event) -> bool:
        return (
            cls._is_work_event(event)
            and cls.OPEN_CATEGORY in set(event.categories or ())
            and event.end is None
        )

    def _all_work_events(self) -> list[Event]:
        target = self._collection_url(required=False)
        if target is None:
            return []
        items = self.adapter.list_events(category=self.CATEGORY)
        return [
            item
            for item in items
            if isinstance(item, Event)
            and self._is_work_event(item)
            and str(getattr(item, "_caldav_collection_url", "") or "") == target
        ]

    def open_events(self) -> list[Event]:
        return [event for event in self._all_work_events() if self._is_open(event)]

    def current_task_id(self) -> str | None:
        open_items = self.open_events()
        if not open_items:
            return None
        task_ids = {self._task_id_from_event(item) for item in open_items}
        task_ids.discard(None)
        if len(open_items) != 1 or len(task_ids) != 1:
            raise AmbiguousError(
                "More than one open CalDAV work interval exists; "
                "close the extra interval before starting another Task."
            )
        return next(iter(task_ids))

    def open_for(self, task: Task | str) -> Event | None:
        task_id = str(getattr(task, "id", task) or "").strip()
        if not task_id:
            raise ValidationError("Task id must not be empty")
        matches = [
            event
            for event in self.open_events()
            if self._task_id_from_event(event) == task_id
        ]
        if len(matches) > 1:
            raise AmbiguousError(f"Task {task_id!r} has more than one open work interval")
        return matches[0] if matches else None

    def start_segment(self, task: Task) -> Event:
        task_id = str(task.id or "").strip()
        if not task_id:
            raise ValidationError("Task id must not be empty")
        target = self._collection_url(required=True)
        current = self.current_task_id()
        if current:
            if current == task_id:
                raise ValidationError("This Task is already the current work")
            raise ValidationError(
                "Another Task is currently being worked on; pause or complete it first"
            )

        event = Event(
            summary=f"Work — {task.summary}",
            start=self.now(),
            end=None,
            description=self._description(task_id),
            categories=[self.CATEGORY, self.OPEN_CATEGORY],
        )
        setattr(event, "_caldav_collection_url", target)
        emit_progress(
            "worklog.open",
            f"Opening CalDAV Work interval for {task.summary}...",
            state="started",
            task_id=task_id,
            collection_url=target,
        )
        created = self.adapter.create_event(event)
        if not isinstance(created, Event):
            raise TypeError("CalDAVAdapter must return Event for work-log creation")
        emit_progress(
            "worklog.open",
            "CalDAV Work interval opened.",
            state="done",
            task_id=task_id,
            event_id=created.id,
            start=created.start.isoformat() if isinstance(created.start, datetime) else created.start,
        )
        return created

    def close_segment(self, task: Task | str, *, required: bool = True) -> Event | None:
        event = self.open_for(task)
        if event is None:
            if required:
                raise ValidationError("This Task has no open CalDAV work interval")
            return None
        task_id = str(getattr(task, "id", task) or "").strip()
        closed_at = self.now()
        emit_progress(
            "worklog.close",
            "Closing current CalDAV Work interval...",
            state="started",
            task_id=task_id,
            event_id=event.id,
        )
        updated = self.adapter.update_event(
            event.id,
            {
                "end": closed_at,
                "categories": [self.CATEGORY],
            },
        )
        if not isinstance(updated, Event):
            raise TypeError("CalDAVAdapter must return Event for work-log update")
        emit_progress(
            "worklog.close",
            "CalDAV Work interval closed (DTEND saved; open marker removed).",
            state="done",
            task_id=task_id,
            event_id=updated.id,
            end=updated.end.isoformat() if isinstance(updated.end, datetime) else updated.end,
        )
        return updated

    def reopen_segment(self, event: Event) -> Event:
        updated = self.adapter.update_event(
            event.id,
            {
                "end": None,
                "categories": [self.CATEGORY, self.OPEN_CATEGORY],
            },
        )
        if not isinstance(updated, Event):
            raise TypeError("CalDAVAdapter must return Event for work-log update")
        return updated

    def discard_segment(self, event: Event) -> None:
        try:
            self.adapter.delete_event(event.id)
        except NotFoundError:
            return

    def segments_for(self, task: Task | str) -> list[Event]:
        task_id = str(getattr(task, "id", task) or "").strip()
        if not task_id:
            raise ValidationError("Task id must not be empty")
        result = [
            event
            for event in self._all_work_events()
            if self._task_id_from_event(event) == task_id
        ]
        return sorted(
            result,
            key=lambda item: item.start or datetime.min.replace(tzinfo=timezone.utc),
        )


__all__ = ["WorkLogService"]
