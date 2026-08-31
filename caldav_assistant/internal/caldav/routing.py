"""Apply user-selected CalDAV collection roles to normal Task/Event traffic.

Collection roles are not only creation hints. Once the user has selected the Task,
Event and Work-log collections, ordinary reads and writes should not rediscover and
traverse every compatible collection on every CLI command. CalDAV remains
authoritative: this wrapper only narrows authoritative traffic to an explicitly
configured collection and reuses already-discovered collection objects in this
process.

The concrete python-caldav adapter exposes internal collection/mapping bricks. This
wrapper uses them opportunistically and falls back to the generic adapter contract
when a replacement adapter does not provide those bricks, preserving adapter
replaceability.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
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

    def _scoped_update(
        self,
        collection_url: str,
        item_id: str,
        changes: dict[str, Any],
        *,
        etag: str | None,
        getter_name: str,
        editor_name: str,
        mapper_name: str,
        fallback_name: str,
    ):
        """Update one object in a known collection without a cross-calendar UID scan."""
        calendar = self._selected_calendar(collection_url)
        editor = getattr(self.adapter, editor_name, None)
        mapper = getattr(self.adapter, mapper_name, None)
        checker = getattr(self.adapter, "_check_etag", None)
        if (
            calendar is None
            or not callable(editor)
            or not callable(mapper)
            or not callable(checker)
        ):
            return getattr(self.adapter, fallback_name)(item_id, changes, etag=etag)
        try:
            resource = getattr(calendar, getter_name)(item_id)
            checker(resource, etag)
            if changes:
                editor(resource, changes)
                resource.save()
            return mapper(resource, calendar)
        except Exception as exc:
            raise _app_error(exc) from exc

    def _scoped_delete(
        self,
        collection_url: str,
        item_id: str,
        *,
        etag: str | None,
        getter_name: str,
        fallback_name: str,
    ) -> None:
        """Delete one object in a known collection without a cross-calendar UID scan."""
        calendar = self._selected_calendar(collection_url)
        checker = getattr(self.adapter, "_check_etag", None)
        if calendar is None or not callable(checker):
            getattr(self.adapter, fallback_name)(item_id, etag=etag)
            return
        try:
            resource = getattr(calendar, getter_name)(item_id)
            checker(resource, etag)
            resource.delete()
        except Exception as exc:
            raise _app_error(exc) from exc

    def list_tasks_in_collection(self, collection_url: str, **filters: Any):
        calendar = self._selected_calendar(collection_url)
        mapper = getattr(self.adapter, "_to_task", None)
        if calendar is None or not callable(mapper):
            return self.adapter.list_tasks(**filters)
        try:
            result = []
            # Agenda/Next explicitly request completed=False.  python-caldav can
            # translate that to a server-side pending-VTODO REPORT, which avoids
            # downloading an ever-growing completed-task history just to discard it
            # locally.  Other callers keep the old include-completed semantics.
            include_completed = filters.get("completed") is not False
            for resource in calendar.get_todos(include_completed=include_completed):
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

    def create_task(self, task: Task) -> Task:
        wanted = getattr(task, "_caldav_collection_url", None) or self.task_collection_url()
        calendar = self._selected_calendar(wanted)
        mapper = getattr(self.adapter, "_to_task", None)
        editor = getattr(self.adapter, "_edit_task", None)
        if calendar is None or not callable(mapper) or not callable(editor):
            return self.adapter.create_task(self._copy_with_collection(task, wanted))
        try:
            kwargs: dict[str, Any] = {"summary": task.summary}
            values = {
                "uid": task.id or None,
                "description": task.description or None,
                "dtstart": task.start,
                "due": task.due,
                "status": task.status or None,
                "priority": task.priority,
                "categories": task.categories or None,
            }
            kwargs.update({key: value for key, value in values.items() if value is not None})
            resource = calendar.add_todo(**kwargs)
            if task.completed or task.completed_at is not None:
                editor(
                    resource,
                    {
                        "completed": True,
                        "completed_at": task.completed_at or datetime.now().astimezone(),
                        "status": "COMPLETED",
                    },
                )
                resource.save()
            return mapper(resource, calendar)
        except Exception as exc:
            raise _app_error(exc) from exc

    def update_task_in_collection(
        self,
        collection_url: str,
        task_id: str,
        changes: dict[str, Any],
        *,
        etag: str | None = None,
    ) -> Task:
        return self._scoped_update(
            collection_url,
            task_id,
            changes,
            etag=etag,
            getter_name="get_todo_by_uid",
            editor_name="_edit_task",
            mapper_name="_to_task",
            fallback_name="update_task",
        )

    def update_task(
        self,
        task_id: str,
        changes: dict[str, Any],
        *,
        etag: str | None = None,
    ) -> Task:
        wanted = self.task_collection_url()
        if not _url(wanted):
            return self.adapter.update_task(task_id, changes, etag=etag)
        return self.update_task_in_collection(str(wanted), task_id, changes, etag=etag)

    def delete_task_in_collection(
        self,
        collection_url: str,
        task_id: str,
        *,
        etag: str | None = None,
    ) -> None:
        self._scoped_delete(
            collection_url,
            task_id,
            etag=etag,
            getter_name="get_todo_by_uid",
            fallback_name="delete_task",
        )

    def delete_task(self, task_id: str, *, etag: str | None = None) -> None:
        wanted = self.task_collection_url()
        if not _url(wanted):
            self.adapter.delete_task(task_id, etag=etag)
            return
        self.delete_task_in_collection(str(wanted), task_id, etag=etag)

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

    def create_event(self, event: Event) -> Event:
        # Explicit object routing (used by WorkLogService) always wins over the
        # default human Event collection.
        wanted = getattr(event, "_caldav_collection_url", None) or self.event_collection_url()
        calendar = self._selected_calendar(wanted)
        mapper = getattr(self.adapter, "_to_event", None)
        if calendar is None or not callable(mapper):
            return self.adapter.create_event(self._copy_with_collection(event, wanted))
        try:
            kwargs: dict[str, Any] = {"summary": event.summary}
            values = {
                "uid": event.id or None,
                "dtstart": event.start,
                "dtend": event.end,
                "location": event.location or None,
                "description": event.description or None,
                "categories": event.categories or None,
            }
            kwargs.update({key: value for key, value in values.items() if value is not None})
            return mapper(calendar.add_event(**kwargs), calendar)
        except Exception as exc:
            raise _app_error(exc) from exc

    def update_event_in_collection(
        self,
        collection_url: str,
        event_id: str,
        changes: dict[str, Any],
        *,
        etag: str | None = None,
    ) -> Event:
        return self._scoped_update(
            collection_url,
            event_id,
            changes,
            etag=etag,
            getter_name="get_event_by_uid",
            editor_name="_edit_event",
            mapper_name="_to_event",
            fallback_name="update_event",
        )

    def update_event(
        self,
        event_id: str,
        changes: dict[str, Any],
        *,
        etag: str | None = None,
    ) -> Event:
        wanted = self.event_collection_url()
        if not _url(wanted):
            return self.adapter.update_event(event_id, changes, etag=etag)
        return self.update_event_in_collection(str(wanted), event_id, changes, etag=etag)

    def delete_event_in_collection(
        self,
        collection_url: str,
        event_id: str,
        *,
        etag: str | None = None,
    ) -> None:
        self._scoped_delete(
            collection_url,
            event_id,
            etag=etag,
            getter_name="get_event_by_uid",
            fallback_name="delete_event",
        )

    def delete_event(self, event_id: str, *, etag: str | None = None) -> None:
        wanted = self.event_collection_url()
        if not _url(wanted):
            self.adapter.delete_event(event_id, etag=etag)
            return
        self.delete_event_in_collection(str(wanted), event_id, etag=etag)


__all__ = ["CollectionRoutingCalDAVAdapter"]
