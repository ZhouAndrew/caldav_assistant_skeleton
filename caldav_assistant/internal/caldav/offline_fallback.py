"""Read-only fallback to the last verified CalDAV snapshot.

Healthy reads still use live CalDAV unless the separate fast-query experiment is
enabled.  Only an availability failure may use this layer.  Returned objects are
always marked stale, and every mutation continues to the authoritative adapter.
"""
from __future__ import annotations

from dataclasses import replace
from threading import RLock
from typing import Any, Mapping, Sequence

from ...api import Event, Task
from ...api.v1.errors import UnavailableError
from .experimental_cache import _matches


class OfflineFallbackCalDAVAdapter:
    """Serve explicitly stale reads only when live CalDAV is unavailable."""

    def __init__(self, adapter: Any, sync: Any) -> None:
        self.adapter = adapter
        self.sync = sync
        self._fallback_lock = RLock()
        self._fallback_generation = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self.adapter, name)

    @property
    def fallback_generation(self) -> int:
        with self._fallback_lock:
            return self._fallback_generation

    def _record_fallback(self) -> None:
        with self._fallback_lock:
            self._fallback_generation += 1

    def _snapshot_available(self) -> bool:
        snapshot = self.sync.cached_snapshot()
        if not isinstance(snapshot, Mapping):
            return False
        expected_version = int(getattr(self.sync, "SCHEMA_VERSION", 1))
        return (
            snapshot.get("schema_version") == expected_version
            and isinstance(snapshot.get("synced_at"), str)
            and bool(str(snapshot.get("synced_at") or "").strip())
            and isinstance(snapshot.get("tasks"), list)
            and isinstance(snapshot.get("events"), list)
        )

    @staticmethod
    def _stale_task(task: Task) -> Task:
        return replace(task, stale=True, _service=None)

    @staticmethod
    def _stale_event(event: Event) -> Event:
        return replace(event, stale=True, _service=None)

    def cached_tasks(self, **filters: Any) -> list[Task]:
        """Return stale cached Task facts without attempting another live read."""
        if not self._snapshot_available():
            raise UnavailableError("No verified Task/Event snapshot is available")
        return [
            self._stale_task(task)
            for task in self.sync.cached_tasks()
            if _matches(task, filters)
        ]

    def cached_events(self, **filters: Any) -> list[Event]:
        """Return stale cached Event facts without attempting another live read."""
        if not self._snapshot_available():
            raise UnavailableError("No verified Task/Event snapshot is available")
        return [
            self._stale_event(event)
            for event in self.sync.cached_events()
            if _matches(event, filters)
        ]

    def list_tasks(self, **filters: Any) -> Sequence[Task]:
        try:
            return self.adapter.list_tasks(**filters)
        except UnavailableError:
            values = self.cached_tasks(**filters)
            self._record_fallback()
            return values

    def get_task(self, task_id: str) -> Task:
        try:
            return self.adapter.get_task(task_id)
        except UnavailableError:
            if not self._snapshot_available():
                raise
            wanted = str(task_id)
            for task in self.sync.cached_tasks():
                if str(task.id) == wanted:
                    self._record_fallback()
                    return self._stale_task(task)
            # A cache miss is not authoritative while offline.
            raise

    def list_events(self, **filters: Any) -> Sequence[Event]:
        try:
            return self.adapter.list_events(**filters)
        except UnavailableError:
            values = self.cached_events(**filters)
            self._record_fallback()
            return values

    def list_events_between(
        self,
        start: Any,
        end: Any,
        **filters: Any,
    ) -> Sequence[Event]:
        reader = getattr(self.adapter, "list_events_between", None)
        if not callable(reader):
            return self.list_events(**filters)
        try:
            return reader(start, end, **filters)
        except UnavailableError:
            # AgendaEngine remains the final time-window authority.
            values = self.cached_events(**filters)
            self._record_fallback()
            return values

    def get_event(self, event_id: str) -> Event:
        try:
            return self.adapter.get_event(event_id)
        except UnavailableError:
            if not self._snapshot_available():
                raise
            wanted = str(event_id)
            for event in self.sync.cached_events():
                if str(event.id) == wanted:
                    self._record_fallback()
                    return self._stale_event(event)
            raise


__all__ = ["OfflineFallbackCalDAVAdapter"]
