"""Experimental-cache wrapper with stable authoritative write-through.

Cache-first *reads* remain an opt-in experiment.  The last verified background
snapshot, however, is also the stable startup fallback.  Once an authoritative
CalDAV mutation succeeds, keeping that auxiliary snapshot coherent is safe and
necessary regardless of whether experimental cache reads are enabled.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from ...api import Event, Task
from .conditional_write import update_event_from_snapshot, update_task_from_snapshot
from .experimental_cache import ExperimentalCacheCalDAVAdapter as _BaseExperimentalCache


class ExperimentalCacheCalDAVAdapter(_BaseExperimentalCache):
    """Transparent live reads plus coherent verified-snapshot write-through."""

    def _patch_snapshot(
        self,
        kind: str,
        *,
        obj: Task | Event | None = None,
        remove_id: str | None = None,
    ) -> None:
        """Patch a present snapshot after a successful authoritative CalDAV write.

        ``synced_at`` remains the time of the last full server verification.  The
        separate cache-update metadata records that one object was refreshed from a
        successful server mutation, so the cache never pretends a full sync occurred.
        """
        with self.sync._sync_lock:
            snapshot = self.sync.cached_snapshot()
            if not isinstance(snapshot, Mapping):
                return

            key = "tasks" if kind == "task" else "events"
            values = snapshot.get(key, [])
            if not isinstance(values, list):
                return

            updated_values = [
                dict(item)
                for item in values
                if isinstance(item, Mapping)
                and (
                    remove_id is None
                    or str(item.get("id") or "") != str(remove_id)
                )
            ]

            if obj is not None:
                serializer = (
                    self.sync._task_to_dict
                    if kind == "task"
                    else self.sync._event_to_dict
                )
                serialized = serializer(obj)
                obj_id = str(serialized.get("id") or "")
                updated_values = [
                    item
                    for item in updated_values
                    if str(item.get("id") or "") != obj_id
                ]
                updated_values.append(serialized)

            updated = dict(snapshot)
            updated[key] = updated_values
            updated["cache_updated_at"] = datetime.now(timezone.utc).isoformat()
            updated["cache_update_reason"] = "authoritative-write"
            self.sync.cache.set(self.sync.SNAPSHOT_KEY, updated)

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
