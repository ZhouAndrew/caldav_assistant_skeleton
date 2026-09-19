"""Low-overhead access to the last verified CalDAV snapshot.

The base offline fallback is intentionally conservative, but its separate availability
checks and Task/Event reads can deserialize the same large SQLite JSON snapshot several
times.  CLI startup needs one coherent local point-in-time view, so this production
wrapper loads and validates the snapshot once and derives both model collections from
that same value.
"""
from __future__ import annotations

from typing import Any, Mapping

from ...api.v1.errors import UnavailableError
from .experimental_cache import _matches
from .offline_fallback import OfflineFallbackCalDAVAdapter as _BaseOfflineFallback


class OfflineFallbackCalDAVAdapter(_BaseOfflineFallback):
    """Offline fallback with a single-read startup bundle capability."""

    def _verified_snapshot(self) -> Mapping[str, Any]:
        snapshot = self.sync.cached_snapshot()
        expected_version = int(getattr(self.sync, "SCHEMA_VERSION", 1))
        if not isinstance(snapshot, Mapping):
            raise UnavailableError("No verified Task/Event snapshot is available")
        if (
            snapshot.get("schema_version") != expected_version
            or not isinstance(snapshot.get("synced_at"), str)
            or not str(snapshot.get("synced_at") or "").strip()
            or not isinstance(snapshot.get("tasks"), list)
            or not isinstance(snapshot.get("events"), list)
        ):
            raise UnavailableError("No verified Task/Event snapshot is available")
        return snapshot

    def cached_startup_items(self, **task_filters: Any):
        """Return stale Task+Event models from exactly one SQLite snapshot read."""
        snapshot = self._verified_snapshot()
        task_decoder = getattr(self.sync, "_cached_task", None)
        event_decoder = getattr(self.sync, "_cached_event", None)
        if not callable(task_decoder) or not callable(event_decoder):
            # Compatibility with replacement SyncEngine implementations.
            return self.cached_tasks(**task_filters), self.cached_events()

        tasks = []
        for raw in snapshot.get("tasks", ()):
            if not isinstance(raw, Mapping):
                continue
            task = task_decoder(raw)
            if _matches(task, task_filters):
                tasks.append(self._stale_task(task))

        events = []
        for raw in snapshot.get("events", ()):
            if not isinstance(raw, Mapping):
                continue
            events.append(self._stale_event(event_decoder(raw)))
        return tasks, events

    def cached_tasks(self, **filters: Any):
        """Avoid the base class's availability-read + data-read duplication."""
        snapshot = self._verified_snapshot()
        decoder = getattr(self.sync, "_cached_task", None)
        if not callable(decoder):
            return super().cached_tasks(**filters)
        result = []
        for raw in snapshot.get("tasks", ()):
            if not isinstance(raw, Mapping):
                continue
            task = decoder(raw)
            if _matches(task, filters):
                result.append(self._stale_task(task))
        return result

    def cached_events(self, **filters: Any):
        """Avoid the base class's availability-read + data-read duplication."""
        snapshot = self._verified_snapshot()
        decoder = getattr(self.sync, "_cached_event", None)
        if not callable(decoder):
            return super().cached_events(**filters)
        result = []
        for raw in snapshot.get("events", ()):
            if not isinstance(raw, Mapping):
                continue
            event = decoder(raw)
            if _matches(event, filters):
                result.append(self._stale_event(event))
        return result


__all__ = ["OfflineFallbackCalDAVAdapter"]
