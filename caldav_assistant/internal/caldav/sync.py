"""CalDAV synchronization and local cache refresh.

MODULE CONTRACT
- Calls: CalDAVAdapter + cache repository + optional internal sync-token transport.
- Provides: SyncEngine.
- Must not: access CalDAV XML/HTTP directly, print CLI output, or contain
  Task/Event business rules.

CalDAV is always the source of truth.
SQLite contains only the last verified cache snapshot and sync metadata.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from threading import RLock
from typing import Any, Mapping

from ...api import Event, Task
from ...api.v1.errors import ConflictError
from .sync_token import SyncTokenStale, SyncTokenTransport, SyncTokenUnavailable


class SyncEngine:
    """Synchronize authoritative CalDAV data into the local cache."""

    SNAPSHOT_KEY = "caldav.snapshot.v1"
    STATUS_KEY = "caldav.sync.status.v1"
    TOKEN_KEY = "caldav.sync.tokens.v1"
    SCHEMA_VERSION = 1
    TOKEN_RETRY_SECONDS = 6 * 60 * 60

    def __init__(self, adapter: Any, cache: Any):
        self.adapter = adapter
        self.cache = cache
        # Manual diagnostics may request an immediate refresh while the background
        # service is already running its periodic synchronization.  Serialize those
        # authoritative reads so they cannot race while replacing the same snapshot.
        self._sync_lock = RLock()
        self._token_transport = SyncTokenTransport(adapter)

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
        collection_url = getattr(obj, "_caldav_collection_url", None)
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
    def _check_unique(items: list[dict[str, Any]], *, kind: str) -> None:
        """Detect UID conflicts before replacing the good cache."""
        seen: dict[str, str | None] = {}
        for item in items:
            uid = str(item.get("id") or "")
            if not uid:
                raise ConflictError(f"Remote {kind} without UID cannot be synchronized.")
            metadata = item.get("_caldav", {})
            collection = metadata.get("collection_url") if isinstance(metadata, dict) else None
            if uid in seen:
                previous = seen[uid]
                raise ConflictError(
                    f"Duplicate remote {kind} UID {uid!r}: {previous!r} and {collection!r}"
                )
            seen[uid] = collection

    def _read_remote(self) -> dict[str, Any]:
        """Read and verify one complete CalDAV snapshot."""
        remote_tasks = list(self.adapter.list_tasks())
        remote_events = list(self.adapter.list_events())
        tasks = [self._task_to_dict(task) for task in remote_tasks]
        events = [self._event_to_dict(event) for event in remote_events]
        self._check_unique(tasks, kind="Task")
        self._check_unique(events, kind="Event")
        return {
            "schema_version": self.SCHEMA_VERSION,
            "synced_at": self._now().isoformat(),
            "tasks": tasks,
            "events": events,
        }

    @staticmethod
    def _index(snapshot: Mapping[str, Any] | None, key: str) -> dict[str, dict[str, Any]]:
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
        old = cls._index(previous, key)
        new = cls._index(current, key)
        old_ids = set(old)
        new_ids = set(new)
        return {
            "added": sorted(new_ids - old_ids),
            "updated": sorted(uid for uid in old_ids & new_ids if old[uid] != new[uid]),
            "removed": sorted(old_ids - new_ids),
        }

    def _record_error(self, *, mode: str, error: Exception) -> None:
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

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _token_state(self) -> Mapping[str, Any] | None:
        value = self.cache.get(self.TOKEN_KEY, None)
        return value if isinstance(value, Mapping) else None

    def _token_retry_blocked(
        self,
        state: Mapping[str, Any] | None,
        role_urls: Mapping[str, str],
    ) -> bool:
        if not state or state.get("supported") is not False:
            return False
        stored = state.get("role_urls")
        if not isinstance(stored, Mapping) or dict(stored) != dict(role_urls):
            return False
        retry_at = self._parse_time(state.get("retry_at"))
        return retry_at is not None and self._now() < retry_at

    def _unsupported_token_state(
        self,
        role_urls: Mapping[str, str],
        reason: str,
    ) -> dict[str, Any]:
        now = self._now()
        return {
            "supported": False,
            "role_urls": dict(role_urls),
            "checked_at": now.isoformat(),
            "retry_at": (now + timedelta(seconds=self.TOKEN_RETRY_SECONDS)).isoformat(),
            "reason": str(reason or "sync-token unavailable"),
        }

    def _seed_token_state(
        self,
        *,
        force: bool = False,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Get a token before a full scan so initialization cannot lose a race."""
        transport = self._token_transport
        role_urls = transport.role_urls()
        if not role_urls or not transport.available():
            return None, "sync-token capability unavailable"

        old_state = self._token_state()
        if not force and self._token_retry_blocked(old_state, role_urls):
            return None, str(old_state.get("reason") or "sync-token retry deferred")

        try:
            seeded = transport.seed()
        except SyncTokenUnavailable as exc:
            unsupported = self._unsupported_token_state(role_urls, str(exc))
            self.cache.set(self.TOKEN_KEY, unsupported)
            return None, str(exc)

        state = {
            "supported": True,
            "role_urls": dict(seeded["role_urls"]),
            "tokens": dict(seeded["tokens"]),
            "checked_at": self._now().isoformat(),
        }
        return state, None

    @staticmethod
    def _item_url(item: Mapping[str, Any]) -> str:
        metadata = item.get("_caldav")
        if not isinstance(metadata, Mapping):
            return ""
        return str(metadata.get("url") or "").strip().rstrip("/")

    @classmethod
    def _merge_kind(
        cls,
        previous: Mapping[str, Any],
        key: str,
        upserts: list[dict[str, Any]],
        deleted_urls: set[str],
    ) -> list[dict[str, Any]]:
        values = previous.get(key, [])
        existing = [dict(item) for item in values if isinstance(item, Mapping)] if isinstance(values, list) else []
        if deleted_urls:
            existing = [item for item in existing if cls._item_url(item) not in deleted_urls]
        by_id = {str(item.get("id") or ""): item for item in existing if item.get("id")}
        for item in upserts:
            uid = str(item.get("id") or "")
            if uid:
                by_id[uid] = item
        return list(by_id.values())

    def _merge_incremental(
        self,
        previous: Mapping[str, Any],
        changes: Mapping[str, Any],
    ) -> dict[str, Any]:
        deleted_urls = {
            str(value or "").strip().rstrip("/")
            for value in (changes.get("deleted_urls") or ())
            if str(value or "").strip()
        }
        task_upserts = [self._task_to_dict(item) for item in (changes.get("tasks") or ())]
        event_upserts = [self._event_to_dict(item) for item in (changes.get("events") or ())]
        tasks = self._merge_kind(previous, "tasks", task_upserts, deleted_urls)
        events = self._merge_kind(previous, "events", event_upserts, deleted_urls)
        self._check_unique(tasks, kind="Task")
        self._check_unique(events, kind="Event")
        return {
            "schema_version": self.SCHEMA_VERSION,
            "synced_at": self._now().isoformat(),
            "tasks": tasks,
            "events": events,
        }

    def _report(
        self,
        *,
        requested_mode: str,
        effective_mode: str,
        current: Mapping[str, Any],
        task_changes: Mapping[str, Any],
        event_changes: Mapping[str, Any],
        fallback_reason: str | None = None,
    ) -> dict[str, Any]:
        report = {
            "state": "ok",
            "synced_at": current["synced_at"],
            "requested_mode": requested_mode,
            "effective_mode": effective_mode,
            "task_count": len(current["tasks"]),
            "event_count": len(current["events"]),
            "changes": {
                "tasks": dict(task_changes),
                "events": dict(event_changes),
            },
        }
        if fallback_reason:
            report["fallback_reason"] = fallback_reason
        return report

    def _full_sync(
        self,
        *,
        requested_mode: str,
        force_token_seed: bool = False,
        fallback_reason: str | None = None,
    ) -> dict[str, Any]:
        previous = self.cache.get(self.SNAPSHOT_KEY, None)
        seed_state, seed_reason = self._seed_token_state(force=force_token_seed)
        if fallback_reason is None:
            fallback_reason = seed_reason

        current = self._read_remote()
        task_changes = self._delta(previous, current, "tasks")
        event_changes = self._delta(previous, current, "events")

        # Snapshot first, token second.  If a process dies between the two writes,
        # the older token only replays already-applied changes on the next run.
        self.cache.set(self.SNAPSHOT_KEY, current)
        if seed_state is not None:
            self.cache.set(self.TOKEN_KEY, seed_state)

        effective_mode = "full" if requested_mode == "full" else "full-scan"
        report = self._report(
            requested_mode=requested_mode,
            effective_mode=effective_mode,
            current=current,
            task_changes=task_changes,
            event_changes=event_changes,
            fallback_reason=fallback_reason if requested_mode == "incremental" else None,
        )
        self.cache.set(self.STATUS_KEY, report)
        return report

    def refresh(self) -> dict[str, Any]:
        """Perform a complete CalDAV -> cache refresh and seed RFC 6578 if possible."""
        with self._sync_lock:
            try:
                return self._full_sync(requested_mode="full")
            except Exception as exc:
                self._record_error(mode="full", error=exc)
                raise

    def incremental_sync(self) -> dict[str, Any]:
        """Use RFC 6578 deltas when available, with honest full-scan fallback.

        The frozen CalDAVAdapter API is unchanged.  Production collection routing
        exposes enough internal bricks for SyncTokenTransport to use python-caldav's
        high-level RFC 6578 implementation.  Replacement adapters keep the previous
        full-scan behavior.
        """
        with self._sync_lock:
            previous = self.cache.get(self.SNAPSHOT_KEY, None)
            state = self._token_state()
            role_urls = self._token_transport.role_urls()
            valid_state = (
                isinstance(previous, Mapping)
                and state is not None
                and state.get("supported") is True
                and isinstance(state.get("role_urls"), Mapping)
                and dict(state["role_urls"]) == dict(role_urls)
            )

            if valid_state:
                try:
                    changes = self._token_transport.changes(state)
                    current = self._merge_incremental(previous, changes)
                    task_changes = self._delta(previous, current, "tasks")
                    event_changes = self._delta(previous, current, "events")
                    self.cache.set(self.SNAPSHOT_KEY, current)
                    self.cache.set(
                        self.TOKEN_KEY,
                        {
                            "supported": True,
                            "role_urls": dict(changes["role_urls"]),
                            "tokens": dict(changes["tokens"]),
                            "checked_at": self._now().isoformat(),
                        },
                    )
                    report = self._report(
                        requested_mode="incremental",
                        effective_mode="sync-token",
                        current=current,
                        task_changes=task_changes,
                        event_changes=event_changes,
                    )
                    self.cache.set(self.STATUS_KEY, report)
                    return report
                except (SyncTokenStale, SyncTokenUnavailable) as exc:
                    try:
                        return self._full_sync(
                            requested_mode="incremental",
                            force_token_seed=True,
                            fallback_reason=f"{type(exc).__name__}: {exc}",
                        )
                    except Exception as fallback_exc:
                        self._record_error(mode="incremental", error=fallback_exc)
                        raise
                except Exception as exc:
                    self._record_error(mode="incremental", error=exc)
                    raise

            try:
                reason = None
                if state is not None and state.get("supported") is False:
                    reason = str(state.get("reason") or "sync-token unavailable")
                elif state is not None and role_urls and dict(state.get("role_urls") or {}) != dict(role_urls):
                    reason = "configured collection roles changed"
                return self._full_sync(
                    requested_mode="incremental",
                    force_token_seed=bool(state and state.get("supported") is True),
                    fallback_reason=reason,
                )
            except Exception as exc:
                self._record_error(mode="incremental", error=exc)
                raise

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
            priority=(int(item["priority"]) if item.get("priority") is not None else None),
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
        """Return Task facts from the last verified snapshot for background use."""
        snapshot = self.cached_snapshot() or {}
        values = snapshot.get("tasks", [])
        if not isinstance(values, list):
            return []
        return [self._cached_task(item) for item in values if isinstance(item, Mapping)]

    def cached_events(self) -> list[Event]:
        """Return Event facts from the last verified snapshot for background use."""
        snapshot = self.cached_snapshot() or {}
        values = snapshot.get("events", [])
        if not isinstance(values, list):
            return []
        return [self._cached_event(item) for item in values if isinstance(item, Mapping)]

    def cached_snapshot(self) -> Mapping[str, Any] | None:
        """Return the last known-good cache snapshot."""
        return self.cache.get(self.SNAPSHOT_KEY, None)

    def status(self) -> Mapping[str, Any] | None:
        """Return the most recent synchronization status."""
        return self.cache.get(self.STATUS_KEY, None)
