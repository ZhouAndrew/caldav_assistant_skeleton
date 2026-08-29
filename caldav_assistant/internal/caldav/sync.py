"""CalDAV synchronization and local cache refresh.

MODULE CONTRACT
- Calls: CalDAVAdapter + cache repository.
- Provides: SyncEngine.
- Must not: access CalDAV XML/HTTP directly, print CLI output, or contain
  Task/Event business rules.

CalDAV is always the source of truth.
SQLite contains only the last verified cache snapshot and sync metadata.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from threading import RLock
from typing import Any, Mapping

from ...api import Event, Task
from ...api.v1.errors import ConflictError


class SyncEngine:
    """Synchronize authoritative CalDAV data into the local cache."""

    SNAPSHOT_KEY = "caldav.snapshot.v1"
    STATUS_KEY = "caldav.sync.status.v1"
    SCHEMA_VERSION = 1

    def __init__(self, adapter: Any, cache: Any):
        self.adapter = adapter
        self.cache = cache
        # Manual diagnostics may request an immediate refresh while the background
        # service is already running its periodic synchronization.  Serialize those
        # authoritative scans so they cannot race while replacing the same snapshot.
        self._sync_lock = RLock()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _time_value(value: Any) -> Any:
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        return value

    @staticmethod
    def _transport_metadata(obj: Any) -> dict[str, Any]:
        """Keep useful CalDAV metadata without caching library objects."""

        result = {}

        etag = getattr(obj, "_caldav_etag", None)
        url = getattr(obj, "_caldav_url", None)
        collection_url = getattr(
            obj,
            "_caldav_collection_url",
            None,
        )

        if etag is not None:
            result["etag"] = str(etag)

        if url:
            result["url"] = str(url)

        if collection_url:
            result["collection_url"] = str(collection_url)

        return result

    @classmethod
    def _task_to_dict(cls, task: Task) -> dict[str, Any]:
        item = {
            "id": str(task.id or ""),
            "summary": task.summary,
            "description": task.description,
            "start": cls._time_value(task.start),
            "due": cls._time_value(task.due),
            "status": task.status,
            "completed": bool(task.completed),
            "completed_at": cls._time_value(task.completed_at),
            "priority": task.priority,
            "categories": list(task.categories),
            "overdue": bool(task.overdue),
        }

        metadata = cls._transport_metadata(task)

        if metadata:
            item["_caldav"] = metadata

        # raw may contain python-caldav / icalendar objects.
        # Never serialize those into the SQLite cache.
        return item

    @classmethod
    def _event_to_dict(cls, event: Event) -> dict[str, Any]:
        item = {
            "id": str(event.id or ""),
            "summary": event.summary,
            "start": cls._time_value(event.start),
            "end": cls._time_value(event.end),
            "location": event.location,
            "description": event.description,
            "categories": list(event.categories),
        }

        metadata = cls._transport_metadata(event)

        if metadata:
            item["_caldav"] = metadata

        return item

    @staticmethod
    def _check_unique(
        items: list[dict[str, Any]],
        *,
        kind: str,
    ) -> None:
        """Detect UID conflicts before replacing the good cache."""

        seen: dict[str, str | None] = {}

        for item in items:
            uid = str(item.get("id") or "")

            if not uid:
                raise ConflictError(
                    f"Remote {kind} without UID cannot be synchronized."
                )

            metadata = item.get("_caldav", {})

            if isinstance(metadata, dict):
                collection = metadata.get("collection_url")
            else:
                collection = None

            if uid in seen:
                previous = seen[uid]

                raise ConflictError(
                    f"Duplicate remote {kind} UID {uid!r}: "
                    f"{previous!r} and {collection!r}"
                )

            seen[uid] = collection

    def _read_remote(self) -> dict[str, Any]:
        """Read and verify one complete CalDAV snapshot."""

        remote_tasks = list(
            self.adapter.list_tasks()
        )

        remote_events = list(
            self.adapter.list_events()
        )

        tasks = [
            self._task_to_dict(task)
            for task in remote_tasks
        ]

        events = [
            self._event_to_dict(event)
            for event in remote_events
        ]

        self._check_unique(
            tasks,
            kind="Task",
        )

        self._check_unique(
            events,
            kind="Event",
        )

        return {
            "schema_version": self.SCHEMA_VERSION,
            "synced_at": self._now().isoformat(),
            "tasks": tasks,
            "events": events,
        }

    @staticmethod
    def _index(
        snapshot: Mapping[str, Any] | None,
        key: str,
    ) -> dict[str, dict[str, Any]]:
        if not snapshot:
            return {}

        values = snapshot.get(key, [])

        if not isinstance(values, list):
            return {}

        result = {}

        for item in values:
            if not isinstance(item, dict):
                continue

            uid = str(item.get("id") or "")

            if uid:
                result[uid] = item

        return result

    @classmethod
    def _delta(
        cls,
        previous: Mapping[str, Any] | None,
        current: Mapping[str, Any],
        key: str,
    ) -> dict[str, list[str]]:
        """Compare two snapshots and return UID-level changes."""

        old = cls._index(
            previous,
            key,
        )

        new = cls._index(
            current,
            key,
        )

        old_ids = set(old)
        new_ids = set(new)

        return {
            "added": sorted(
                new_ids - old_ids
            ),
            "updated": sorted(
                uid
                for uid in old_ids & new_ids
                if old[uid] != new[uid]
            ),
            "removed": sorted(
                old_ids - new_ids
            ),
        }

    def _record_error(
        self,
        *,
        mode: str,
        error: Exception,
    ) -> None:
        self.cache.set(
            self.STATUS_KEY,
            {
                "state": "error",
                "failed_at": self._now().isoformat(),
                "requested_mode": mode,
                "error_type": type(error).__name__,
                "error": str(error),
            },
        )

    def _sync(
        self,
        *,
        requested_mode: str,
    ) -> dict[str, Any]:
        """Perform synchronization without destroying good cache on failure."""

        with self._sync_lock:
            previous = self.cache.get(
                self.SNAPSHOT_KEY,
                None,
            )

            try:
                current = self._read_remote()

                task_changes = self._delta(
                    previous,
                    current,
                    "tasks",
                )

                event_changes = self._delta(
                    previous,
                    current,
                    "events",
                )

            except Exception as exc:
                # Network/auth/parser/conflict failure must not destroy the
                # last known-good local snapshot.
                self._record_error(
                    mode=requested_mode,
                    error=exc,
                )

                raise

            # One snapshot object prevents half-updated Task/Event caches.
            self.cache.set(
                self.SNAPSHOT_KEY,
                current,
            )

            effective_mode = (
                "full"
                if requested_mode == "full"
                else "full-scan"
            )

            report = {
                "state": "ok",
                "synced_at": current["synced_at"],
                "requested_mode": requested_mode,
                "effective_mode": effective_mode,
                "task_count": len(current["tasks"]),
                "event_count": len(current["events"]),
                "changes": {
                    "tasks": task_changes,
                    "events": event_changes,
                },
            }

            self.cache.set(
                self.STATUS_KEY,
                report,
            )

            return report

    def refresh(self) -> dict[str, Any]:
        """Perform a complete CalDAV -> cache refresh."""

        return self._sync(
            requested_mode="full",
        )

    def incremental_sync(self) -> dict[str, Any]:
        """Synchronize changes using the best currently available mechanism.

        The current frozen CalDAVAdapter has no sync-token / ctag API.

        Therefore this implementation performs a complete remote scan and
        compares it against the previous verified cache snapshot.

        It deliberately reports:

            effective_mode = "full-scan"

        rather than pretending protocol-level incremental sync occurred.
        """

        return self._sync(
            requested_mode="incremental",
        )

    @staticmethod
    def _cached_time(value: Any) -> date | datetime | None:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return value
        text = str(value)
        try:
            if "T" in text or " " in text:
                return datetime.fromisoformat(text)
            return date.fromisoformat(text)
        except ValueError:
            return None

    @classmethod
    def _cached_task(cls, item: Mapping[str, Any]) -> Task:
        return Task(
            id=str(item.get("id") or ""),
            summary=str(item.get("summary") or ""),
            description=str(item.get("description") or ""),
            start=cls._cached_time(item.get("start")),
            due=cls._cached_time(item.get("due")),
            status=str(item.get("status") or "NEEDS-ACTION"),
            completed=bool(item.get("completed", False)),
            completed_at=(
                value
                if isinstance((value := cls._cached_time(item.get("completed_at"))), datetime)
                else None
            ),
            priority=(
                int(item["priority"])
                if item.get("priority") is not None
                else None
            ),
            categories=list(item.get("categories") or []),
            overdue=bool(item.get("overdue", False)),
        )

    @classmethod
    def _cached_event(cls, item: Mapping[str, Any]) -> Event:
        return Event(
            id=str(item.get("id") or ""),
            summary=str(item.get("summary") or ""),
            start=cls._cached_time(item.get("start")),
            end=cls._cached_time(item.get("end")),
            location=str(item.get("location") or ""),
            description=str(item.get("description") or ""),
            categories=list(item.get("categories") or []),
        )

    def cached_tasks(self) -> list[Task]:
        """Return Task facts from the last verified snapshot for background use.

        This is explicitly a cache view, not a new source of truth.  Background
        reminder evaluation may consume it because SyncEngine is responsible for
        re-validating it against CalDAV.
        """
        snapshot = self.cached_snapshot() or {}
        values = snapshot.get("tasks", [])
        if not isinstance(values, list):
            return []
        return [
            self._cached_task(item)
            for item in values
            if isinstance(item, Mapping)
        ]

    def cached_events(self) -> list[Event]:
        """Return Event facts from the last verified snapshot for background use."""
        snapshot = self.cached_snapshot() or {}
        values = snapshot.get("events", [])
        if not isinstance(values, list):
            return []
        return [
            self._cached_event(item)
            for item in values
            if isinstance(item, Mapping)
        ]

    def cached_snapshot(
        self,
    ) -> Mapping[str, Any] | None:
        """Return the last known-good cache snapshot."""

        return self.cache.get(
            self.SNAPSHOT_KEY,
            None,
        )

    def status(
        self,
    ) -> Mapping[str, Any] | None:
        """Return the most recent synchronization status."""

        return self.cache.get(
            self.STATUS_KEY,
            None,
        )
