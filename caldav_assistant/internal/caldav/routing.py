"""Apply user-selected CalDAV collection roles to object creation.

This wrapper owns no CalDAV transport. It only attaches the selected collection URL
before delegating to the real adapter, so the transport never guesses when several
collections support the same component type.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from ...api import Event, Task


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

    def create_task(self, task: Task) -> Task:
        wanted = getattr(task, "_caldav_collection_url", None) or self.task_collection_url()
        return self.adapter.create_task(self._copy_with_collection(task, wanted))

    def create_event(self, event: Event) -> Event:
        # Explicit object routing (used by WorkLogService) always wins over the
        # default human Event collection.
        wanted = getattr(event, "_caldav_collection_url", None) or self.event_collection_url()
        return self.adapter.create_event(self._copy_with_collection(event, wanted))


__all__ = ["CollectionRoutingCalDAVAdapter"]
