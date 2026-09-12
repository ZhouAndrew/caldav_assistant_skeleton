"""Stable read-only fallback to the last verified CalDAV snapshot.

This is deliberately separate from the opt-in fast-query cache. Healthy reads keep
using the configured authoritative adapter unless the user enabled that experiment.
Only an ``UnavailableError`` may trigger this reliability fallback. Mutations always
pass through to CalDAV and therefore can never report success from cached data.
"""
from __future__ import annotations

from dataclasses import replace
from threading import RLock
from typing import Any, Mapping, Sequence

from ...api import Event, Task
from ...api.v1.errors import UnavailableError
from .experimental_cache import _matches


class OfflineFallbackCalDAVAdapter:
    """Use stale, explicitly marked snapshot objects only when CalDAV is unavailable."""

    def __init__(self, adapter: Any, sync: Any) -> None:
        self.adapter = adapter
        self.sync = sync
        self._fallback_lock = RLock()
        self._fallback_generation = 0

    @property
    def fallback_generation(self) -> int:
        """Monotonic signal for callers that must label even an empty stale read."""
        with self._fallback_lock:
            return self._fallback_generation

    def _record_fallback(self) -> None:
        with self._fallback_lock:
            self._fallback_generation += 1

    def __getattr__(self, name: str) -> Any:
        return getattr(self.adapter, name)

    def _snapshot_available(self) -> bool:
        return isinstance(self.sync.cached_snapshot(), Mapping)

    @staticmethod
    def _stale_task(task: Task) -> Task:
        return replace(task, stale=True, _service=None)

    @staticmethod
    def _stale_event(event: Event) -> Event:
        return replace(event, stale=True, _service=None)

    def _cached_tasks(self, **filters: Any) -> list[Task]:
        return [
            self._stale_task(task)
            for task in self.sync.cached_tasks()
            if _matches(task, filters)
        ]

    def _cached_events(self, **filters: Any) -> list[Event]:
        return [
            self._stale_event(event)
            for event in self.sync.cached_events()
            if _matches(event, filters)
        ]

    def list_tasks(self, **filters: Any) -> Sequence[Task]:
        try:
            return self.adapter.list_tasks(**filters)
        except UnavailableError:
            if not self._snapshot_available():
                raise
            self._record_fallback()
            return self._cached_tasks(**filters)

    def get_task(self, task_id: str) -> Task:
        try:
            return self.adapter.get_task(task_id)
        except UnavailableError:
            if not self._snapshot_available():
                raise
            self._record_fallback()
            wanted = str(task_id)
            for task in self.sync.cached_tasks():
                if str(task.id) == wanted:
                    return self._stale_task(task)
            # We cannot claim authoritative absence while offline. Preserve the
            # availability failure rather than converting a cache miss to NotFound.
            raise

    def list_events(self, **filters: Any) -> Sequence[Event]:
        try:
            return self.adapter.list_events(**filters)
        except UnavailableError:
            if not self._snapshot_available():
                raise
            self._record_fallback()
            return self._cached_events(**filters)

    def list_events_between(self, start: Any, end: Any, **filters: Any) -> Sequence[Event]:
        """Keep Agenda's optimized bounded read inside the reliability boundary.

        On an outage it is safe to return the full cached Event subset: AgendaEngine
        remains the final time-window authority. This costs only local work and avoids
        duplicating the engine's overlap rules in the infrastructure adapter.
        """
        reader = getattr(self.adapter, "list_events_between", None)
        if not callable(reader):
            return self.list_events(**filters)
        try:
            return reader(start, end, **filters)
        except UnavailableError:
            if not self._snapshot_available():
                raise
            self._record_fallback()
            return self._cached_events(**filters)

    def get_event(self, event_id: str) -> Event:
        try:
            return self.adapter.get_event(event_id)
        except UnavailableError:
            if not self._snapshot_available():
                raise
            self._record_fallback()
            wanted = str(event_id)
            for event in self.sync.cached_events():
                if str(event.id) == wanted:
                    return self._stale_event(event)
            raise


__all__ = ["OfflineFallbackCalDAVAdapter"]
