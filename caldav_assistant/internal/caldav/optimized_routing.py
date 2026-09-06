"""Focused network optimizations for configured CalDAV collection routing.

This subclass keeps :mod:`routing` as the stable, readable collection-role layer and
only overrides hot paths that need transport metadata immediately.  The public/frozen
CalDAVAdapter contract is unchanged; Core code may merely probe the optional
``update_*_from_snapshot`` capability.

For the concrete python-caldav adapter, a UID read requests both calendar-data and
DAV:getetag in the same calendar-query REPORT.  A following update can therefore
issue an If-Match PUT without a second UID lookup.  Replacement adapters and servers
that reject the optimized query fall back to the original routing implementation.
"""
from __future__ import annotations

from typing import Any, Mapping

from ...api import Event, Task
from ...api.v1.errors import AmbiguousError, NotFoundError
from .conditional_write import update_event_from_snapshot, update_task_from_snapshot
from .library_adapter import _app_error
from .resource_lookup import resource_by_uid_with_etag
from .routing import CollectionRoutingCalDAVAdapter as _BaseRouting


class CollectionRoutingCalDAVAdapter(_BaseRouting):
    """Collection routing with one-REPORT UID reads when python-caldav supports it."""

    @staticmethod
    def _component_for_mapper(mapper_name: str) -> str | None:
        if mapper_name == "_to_task":
            return "task"
        if mapper_name == "_to_event":
            return "event"
        return None

    def _read_with_etag(self, calendar: Any, item_id: str, component: str) -> Any:
        try:
            return resource_by_uid_with_etag(
                calendar,
                item_id,
                component=component,  # type: ignore[arg-type]
            )
        except (NotFoundError, AmbiguousError):
            raise

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
        """Fresh-read + conditional PUT without a second UID lookup.

        If the concrete ETag-aware query cannot be used, delegate to the original
        routing implementation.  That keeps older/replacement CalDAV behavior intact.
        """
        calendar = self._selected_calendar(collection_url)
        editor = getattr(self.adapter, editor_name, None)
        mapper = getattr(self.adapter, mapper_name, None)
        checker = getattr(self.adapter, "_check_etag", None)
        component = self._component_for_mapper(mapper_name)
        if (
            calendar is None
            or component is None
            or not callable(editor)
            or not callable(mapper)
            or not callable(checker)
        ):
            return super()._scoped_update(
                collection_url,
                item_id,
                changes,
                etag=etag,
                getter_name=getter_name,
                editor_name=editor_name,
                mapper_name=mapper_name,
                fallback_name=fallback_name,
            )

        try:
            resource = self._read_with_etag(calendar, item_id, component)
        except (NotFoundError, AmbiguousError):
            raise
        except Exception:
            return super()._scoped_update(
                collection_url,
                item_id,
                changes,
                etag=etag,
                getter_name=getter_name,
                editor_name=editor_name,
                mapper_name=mapper_name,
                fallback_name=fallback_name,
            )

        try:
            checker(resource, etag)
            if changes:
                editor(resource, changes)
                resource.save()
            return mapper(resource, calendar)
        except Exception as exc:
            raise _app_error(exc) from exc

    def get_task(self, task_id: str) -> Task:
        wanted = self.task_collection_url()
        calendar = self._selected_calendar(wanted)
        mapper = getattr(self.adapter, "_to_task", None)
        if calendar is None or not callable(mapper):
            return super().get_task(task_id)
        try:
            resource = self._read_with_etag(calendar, task_id, "task")
            return mapper(resource, calendar)
        except (NotFoundError, AmbiguousError):
            raise
        except Exception:
            return super().get_task(task_id)

    def get_event(self, event_id: str) -> Event:
        wanted = self.event_collection_url()
        calendar = self._selected_calendar(wanted)
        mapper = getattr(self.adapter, "_to_event", None)
        if calendar is None or not callable(mapper):
            return super().get_event(event_id)
        try:
            resource = self._read_with_etag(calendar, event_id, "event")
            return mapper(resource, calendar)
        except (NotFoundError, AmbiguousError):
            raise
        except Exception:
            return super().get_event(event_id)

    def update_task_from_snapshot(
        self,
        task: Task,
        changes: Mapping[str, Any],
    ) -> Task | None:
        return update_task_from_snapshot(self, task, changes)

    def update_event_from_snapshot(
        self,
        event: Event,
        changes: Mapping[str, Any],
    ) -> Event | None:
        return update_event_from_snapshot(self, event, changes)


__all__ = ["CollectionRoutingCalDAVAdapter"]
