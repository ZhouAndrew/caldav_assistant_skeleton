"""Experimental cache-first read adapter for low-latency CLI queries.

CalDAV remains authoritative.  This adapter only serves reads from the last
verified :class:`SyncEngine` snapshot when the explicit experimental setting is
enabled.  All mutations still go to the real CalDAV adapter first; the cache is
patched only after that authoritative write succeeds.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from ...api import Event, Task
from ...api.v1.errors import ValidationError


def _same_day(value: date | datetime | None, target: date) -> bool:
    if value is None:
        return False
    return value.date() == target if isinstance(value, datetime) else value == target


def _matches(item: Task | Event, filters: Mapping[str, Any]) -> bool:
    """Mirror the public CalDAV adapter's supported list filters."""
    for key, wanted in filters.items():
        if wanted is None:
            continue

        if key == "today":
            if not wanted:
                continue
            probe = item.start
            if isinstance(item, Task) and probe is None:
                probe = item.due
            if not _same_day(probe, date.today()):
                return False
            continue

        if key == "overdue" and isinstance(item, Task):
            if bool(item.overdue) != bool(wanted):
                return False
            continue

        if key in {"category", "categories"}:
            if isinstance(wanted, (list, tuple, set)):
                wanted_set = {str(value) for value in wanted}
            else:
                wanted_set = {str(wanted)}
            if not wanted_set.intersection(set(item.categories)):
                return False
            continue

        if not hasattr(item, key):
            raise ValidationError(f"Unsupported CalDAV filter: {key}")
        if getattr(item, key) != wanted:
            return False

    return True


class ExperimentalCacheCalDAVAdapter:
    """Opt-in cache-first wrapper around the authoritative CalDAV adapter."""

    def __init__(
        self,
        adapter: Any,
        sync: Any,
        *,
        enabled: Callable[[], bool],
    ) -> None:
        self.adapter = adapter
        self.sync = sync
        self.enabled = enabled

    def __getattr__(self, name: str) -> Any:
        return getattr(self.adapter, name)

    def _active(self) -> bool:
        try:
            return bool(self.enabled())
        except Exception:
            # Experimental acceleration must never make the stable path unusable.
            return False

    def _snapshot_available(self) -> bool:
        return self.sync.cached_snapshot() is not None

    def _patch_snapshot(
        self,
        kind: str,
        *,
        obj: Task | Event | None = None,
        remove_id: str | None = None,
    ) -> None:
        """Patch the last verified snapshot only after a successful server write.

        ``synced_at`` intentionally remains the timestamp of the last full remote
        verification.  ``cache_updated_at`` records the local write-through patch
        separately so diagnostics never pretend a full sync occurred.
        """
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
            and (remove_id is None or str(item.get("id") or "") != str(remove_id))
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

    def list_tasks(self, **filters: Any) -> Sequence[Task]:
        if not self._active() or not self._snapshot_available():
            return self.adapter.list_tasks(**filters)
        return [task for task in self.sync.cached_tasks() if _matches(task, filters)]

    def get_task(self, task_id: str) -> Task:
        if self._active() and self._snapshot_available():
            wanted = str(task_id)
            for task in self.sync.cached_tasks():
                if str(task.id) == wanted:
                    return task
        # A cache miss is not authoritative; fall back to CalDAV.
        return self.adapter.get_task(task_id)

    def list_events(self, **filters: Any) -> Sequence[Event]:
        if not self._active() or not self._snapshot_available():
            return self.adapter.list_events(**filters)
        return [event for event in self.sync.cached_events() if _matches(event, filters)]

    def get_event(self, event_id: str) -> Event:
        if self._active() and self._snapshot_available():
            wanted = str(event_id)
            for event in self.sync.cached_events():
                if str(event.id) == wanted:
                    return event
        return self.adapter.get_event(event_id)

    # Mutations remain authoritative.  The successful server result is then used
    # to keep the experimental snapshot coherent without an extra blocking scan.
    def create_task(self, task: Task) -> Task:
        result = self.adapter.create_task(task)
        self._patch_snapshot("task", obj=result)
        return result

    def update_task(
        self,
        task_id: str,
        changes: dict[str, Any],
        *,
        etag: str | None = None,
    ) -> Task:
        result = self.adapter.update_task(task_id, changes, etag=etag)
        self._patch_snapshot("task", obj=result)
        return result

    def delete_task(self, task_id: str, *, etag: str | None = None) -> None:
        self.adapter.delete_task(task_id, etag=etag)
        self._patch_snapshot("task", remove_id=task_id)

    def create_event(self, event: Event) -> Event:
        result = self.adapter.create_event(event)
        self._patch_snapshot("event", obj=result)
        return result

    def update_event(
        self,
        event_id: str,
        changes: dict[str, Any],
        *,
        etag: str | None = None,
    ) -> Event:
        result = self.adapter.update_event(event_id, changes, etag=etag)
        self._patch_snapshot("event", obj=result)
        return result

    def delete_event(self, event_id: str, *, etag: str | None = None) -> None:
        self.adapter.delete_event(event_id, etag=etag)
        self._patch_snapshot("event", remove_id=event_id)


__all__ = ["ExperimentalCacheCalDAVAdapter"]
