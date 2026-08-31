"""Apply user-selected CalDAV collection roles to normal Task/Event traffic.

Collection roles are not only creation hints.  Once the user has selected the Task
and Event collections, ordinary reads should not rediscover and traverse every
compatible collection on every CLI command.  CalDAV remains authoritative: this
wrapper merely narrows the authoritative read to the configured collection.

The concrete python-caldav adapter exposes internal collection/mapping bricks.  This
wrapper uses them opportunistically and falls back to the generic adapter contract
when a replacement adapter does not provide those bricks, preserving adapter
replaceability.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from ...api import Event, Task
from ...api.v1.errors import NotFoundError
from .library_adapter import _app_error, _matches


def _url(value: Any) -> str:
    return str(value or "").strip().rstrip("/")


class CollectionRoutingCalDAVAdapter:
    def __init__(
        self,
        adapter: Any,
        *,
        task_collection_url: Callable[[], str | None],
        event_collection_url: Callable[[], str | None],
    ) -> None:
        self.adapter = adapter
        self.task_collection_url = task_collection_url
        self.event_collection_url = event_collection_url
        self._calendar_cache: dict[tuple[str, str], Any] = {}

    def __getattr__(self, name: str) -> Any:
        return getattr(self.adapter, name)

    @staticmethod
    def _copy_with_collection(obj: Task | Event, url: str | None):
        copied = replace(obj, categories=list(obj.categories), _service=None)
        if isinstance(url, str) and url.strip():
            setattr(copied, "_caldav_collection_url", url.strip())
        elif hasattr(obj, "_caldav_collection_url"):
            setattr(copied, "_caldav_collection_url", getattr(obj, "_caldav_collection_url"))
        return copied

    def _selected_calendar(self, wanted: str | None) -> Any | None:
        """Resolve a configured collection once and reuse its CalDAV object.

        A replacement adapter that does not expose the concrete collection brick is
        allowed; callers then fall back to the ordinary adapter method.  The cache is
        keyed by both Base URL and selected collection URL so changing either setting
        cannot silently keep using the old collection.
        """
        target = _url(wanted)
        calendars = getattr(self.adapter, "_calendars", None)
        if not target or not callable(calendars):
            return None

        try:
            base = _url(getattr(self.adapter, "base_url", ""))
        except Exception:
            base = ""
        key = (base, target)
        cached = self._calendar_cache.get(key)
        if cached is not None:
            return cached

        values = list(calendars())
        matches = [
            calendar
            for calendar in values
            if _url(getattr(calendar, "url", "")) == target
        ]
        if not matches:
            raise NotFoundError(f"Configured CalDAV collection not found: {wanted}")
        if len(matches) > 1:
            raise NotFoundError(f"Configured CalDAV collection is not unique: {wanted}")

        calendar = matches[0]
        # Discard entries for older Base URLs/role values instead of growing forever.
        self._calendar_cache = {key: calendar}
        return calendar

    def list_tasks(self, **filters: Any):
        calendar = self._selected_calendar(self.task_collection_url())
        mapper = getattr(self.adapter, "_to_task", None)
        if calendar is None or not callable(mapper):
            return self.adapter.list_tasks(**filters)

        try:
            result = []
            for resource in calendar.get_todos(include_completed=True):
                task = mapper(resource, calendar)
                if _matches(task, filters):
                    result.append(task)
            return result
        except Exception as exc:
            raise _app_error(exc) from exc

    def get_task(self, task_id: str) -> Task:
        calendar = self._selected_calendar(self.task_collection_url())
        mapper = getattr(self.adapter, "_to_task", None)
        if calendar is None or not callable(mapper):
            return self.adapter.get_task(task_id)
        try:
            return mapper(calendar.get_todo_by_uid(task_id), calendar)
        except Exception as exc:
            raise _app_error(exc) from exc

    def list_events(self, **filters: Any):
        # WorkLogService deliberately queries by its private category and then
        # selects its own configured collection.  Preserve that cross-collection
        # internal query until WorkLog has a dedicated routed adapter; ordinary
        # agenda/event reads use the selected human Event collection fast path.
        if "category" in filters or "categories" in filters:
            return self.adapter.list_events(**filters)

        calendar = self._selected_calendar(self.event_collection_url())
        mapper = getattr(self.adapter, "_to_event", None)
        if calendar is None or not callable(mapper):
            return self.adapter.list_events(**filters)

        try:
            result = []
            for resource in calendar.get_events():
                event = mapper(resource, calendar)
                if _matches(event, filters):
                    result.append(event)
            return result
        except Exception as exc:
            raise _app_error(exc) from exc

    def get_event(self, event_id: str) -> Event:
        calendar = self._selected_calendar(self.event_collection_url())
        mapper = getattr(self.adapter, "_to_event", None)
        if calendar is None or not callable(mapper):
            return self.adapter.get_event(event_id)
        try:
            return mapper(calendar.get_event_by_uid(event_id), calendar)
        except Exception as exc:
            raise _app_error(exc) from exc

    def create_task(self, task: Task) -> Task:
        wanted = getattr(task, "_caldav_collection_url", None) or self.task_collection_url()
        return self.adapter.create_task(self._copy_with_collection(task, wanted))

    def create_event(self, event: Event) -> Event:
        # Explicit object routing (used by WorkLogService) always wins over the
        # default human Event collection.
        wanted = getattr(event, "_caldav_collection_url", None) or self.event_collection_url()
        return self.adapter.create_event(self._copy_with_collection(event, wanted))


__all__ = ["CollectionRoutingCalDAVAdapter"]
