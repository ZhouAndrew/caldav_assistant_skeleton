"""Background-ready current-work snapshot for the CalDAV Session service.

The authoritative current-work fact remains the open Assistant Work VEVENT.  This
wrapper stores only the last successfully verified current Task UID so foreground CLI
startup can render the background snapshot without performing network I/O.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .caldav import CalDAVSessionService as _BaseCalDAVSessionService


class CalDAVSessionService(_BaseCalDAVSessionService):
    CURRENT_WORK_SNAPSHOT_KEY = "session.current_work.snapshot.v1"
    CURRENT_WORK_SCHEMA_VERSION = 1

    def __init__(self, worklog: Any, tasks: Any = None, activity: Any = None) -> None:
        super().__init__(worklog, tasks=tasks, activity=activity)
        sync = self._sync()
        register = getattr(sync, "register_post_sync_hook", None)
        if callable(register):
            register(self.refresh_cached_current_work)

    def _sync(self) -> Any:
        adapter = getattr(self.worklog, "adapter", None)
        return getattr(adapter, "sync", None)

    def _cache(self) -> Any:
        return getattr(self._sync(), "cache", None)

    def _cached_current(self) -> Mapping[str, Any] | None:
        cache = self._cache()
        getter = getattr(cache, "get", None)
        if not callable(getter):
            return None
        value = getter(self.CURRENT_WORK_SNAPSHOT_KEY, None)
        if not isinstance(value, Mapping):
            return None
        if (
            value.get("schema_version") != self.CURRENT_WORK_SCHEMA_VERSION
            or not isinstance(value.get("verified_at"), str)
            or not str(value.get("verified_at") or "").strip()
        ):
            return None
        return value

    def _write_cached_current(self, task_id: str | None) -> None:
        cache = self._cache()
        setter = getattr(cache, "set", None)
        if not callable(setter):
            return
        clean = str(task_id or "").strip() or None
        setter(
            self.CURRENT_WORK_SNAPSHOT_KEY,
            {
                "schema_version": self.CURRENT_WORK_SCHEMA_VERSION,
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "current_task_id": clean,
            },
        )

    def refresh_cached_current_work(self) -> dict[str, Any] | None:
        """Verify the open Work VEVENT in the background and cache only its Task UID."""
        if not self._worklog_configured():
            return None
        facts = self.startup_work_facts(include_history=False)
        if not isinstance(facts, dict):
            return None
        self._write_cached_current(facts.get("current_task_id"))
        return facts

    def cached_startup_snapshot(self, tasks):
        """Return current-work state without network I/O during foreground startup."""
        if self._worklog_configured():
            cached = self._cached_current()
            if cached is not None:
                return {
                    "current_task_id": cached.get("current_task_id"),
                    # Startup only needs current work. Exact paused history remains a
                    # command-time concern and is not promoted into this tiny cache.
                    "worked_task_ids": None,
                    "current_work_verified": True,
                    "verified_at": cached.get("verified_at"),
                }
            values = super().cached_startup_snapshot(tasks)
            result = dict(values)
            result["current_work_verified"] = False
            return result

        # Without a Work collection, Activity Journal is the configured Session
        # source; it is local and does not need a network verification round-trip.
        values = super().cached_startup_snapshot(tasks)
        result = dict(values)
        result["current_work_verified"] = True
        return result

    @staticmethod
    def _task_id(task: Any) -> str | None:
        value = str(getattr(task, "id", task) or "").strip()
        return value or None

    # These methods update only the auxiliary snapshot, and are called only after an
    # authoritative lifecycle operation has persisted the corresponding Work fact.
    def set_current(self, task: Any) -> None:
        self._write_cached_current(self._task_id(task))

    def clear_current(self, task: Any = None) -> None:
        cached = self._cached_current()
        if cached is None:
            return
        wanted = self._task_id(task) if task is not None else None
        current = str(cached.get("current_task_id") or "").strip() or None
        if wanted is None or current == wanted:
            self._write_cached_current(None)

    def mark_paused(self, task: Any) -> None:
        self.clear_current(task)

    def unpause(self, task: Any) -> None:
        return None

    def forget(self, task: Any) -> None:
        self.clear_current(task)


__all__ = ["CalDAVSessionService"]
