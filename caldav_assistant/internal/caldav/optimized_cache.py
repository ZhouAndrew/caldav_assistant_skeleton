"""Experimental-cache wrapper with the optional live-snapshot write capability.

The stable Core services only probe an adapter capability by name; they do not import
or understand the concrete CalDAV implementation.  This small subclass keeps the
existing experimental cache behavior intact while ensuring a successful fast
conditional write patches an active snapshot exactly like the ordinary mutation path.
"""
from __future__ import annotations

from typing import Any, Mapping

from ...api import Event, Task
from .conditional_write import update_event_from_snapshot, update_task_from_snapshot
from .experimental_cache import ExperimentalCacheCalDAVAdapter as _BaseExperimentalCache


class ExperimentalCacheCalDAVAdapter(_BaseExperimentalCache):
    """Transparent cache wrapper plus optional live-object conditional writes."""

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


__all__ = ["ExperimentalCacheCalDAVAdapter"]
