"""Apply user-selected CalDAV collection roles to normal Task/Event traffic.

Collection roles are not only creation hints. Once the user has selected the Task,
Event and Work-log collections, ordinary reads should not rediscover and traverse
every compatible collection on every CLI command. CalDAV remains authoritative:
this wrapper only narrows the authoritative read to an explicitly configured
collection and reuses the already-discovered collection objects in this process.

The concrete python-caldav adapter exposes internal collection/mapping bricks. This
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
        self._calendar_cache_base: str | None = None
        self._calendar_cache: dict[str, list[Any]] = {}

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

    def _base_url(self) -> str:
        try:
            return _url(getattr(self.adapter, "base_url", ""))
        except Exception:
            return ""

    def _refresh_calendar_cache(self, calendars: Callable[[], Any]) -> None:
        values = list(calendars())
        index: dict[str, list[Any]] = {}
        for calendar in values:
            key = _url(getattr(calendar, "url", ""))
            if key:
                index.setdefault(key, []).append(calendar)
        self._calendar_cache_base = self._base_url()
        self._calendar_cache = index

    def _selected_calendar(self, wanted: str | None) -> Any | None:
        """Resolve a configured collection and reuse one discovery for all roles."""
        target = _url(wanted)
        calendars = getattr(self.adapter, "_calendars", None)
        if not target or not callable(calendars):
            return None

        base = self._base_url()
        if self._calendar_cache_base != base:
            self._refresh_calendar_cache(calendars)

        matches = self._calendar_cache.get(target, [])
        if not matches:
            # A collection may have been added while the service stayed alive.
            # Refresh once on a miss; normal Task/Event/WorkLog traffic remains a
            # one-discovery fast path.
            self._refresh_calendar_cache(calendars)
            matches = self._calendar_cache.get(target, [])

        if not matches:
            raise NotFoundError(f"Configured CalDAV collection not found: {wanted}")
        if len(matches) > 1:
            raise NotFoundError(f"Configured CalDAV collection is not unique: {wanted}")
        return matches[0]

    def list_tasks_in_collection(self, collection_url: str, **filters: Any):
        calendar = self._selected_calendar(collection_url)
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

    def list_events_in_collection(self, collection_url: str, **filters: Any):
        calendar = self._selected_calendar(collection_url)
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

    def list_tasks(self, **filters: Any):
        wanted = self.task_collection_url()
        if not _url(wanted):
            return self.adapter.list_tasks(**filters)
        return self.list_tasks_in_collection(str(wanted), **filters)

    def get_task(self, task_id: str) -> Task:
        wanted = self.task_collection_url()
        calendar = self._selected_calendar(wanted)
        mapper = getattr(self.adapter, "_to_task", None)
        if calendar is None or not callable(mapper):
            return self.adapter.get_task(task_id)
        try:
            return mapper(calendar.get_todo_by_uid(task_id), calendar)
        except Exception as exc:
            raise _app_error(exc) from exc

    def list_events(self, **filters: Any):
        wanted = self.event_collection_url()
        if not _url(wanted):
            return self.adapter.list_events(**filters)
        return self.list_events_in_collection(str(wanted), **filters)

    def get_event(self, event_id: str) -> Event:
        wanted = self.event_collection_url()
        calendar = self._selected_calendar(wanted)
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
