"""Fast startup Agenda service backed by the background verified snapshot.

Interactive CLI startup must not turn opening a terminal into a synchronous CalDAV
refresh.  The background Assistant already maintains the last verified Task/Event
snapshot through SyncEngine.  This production composition reads that local snapshot
only; authoritative live reads remain available explicitly for diagnostics or an
intentional refresh.
"""
from __future__ import annotations

from typing import Any

from ...api.v1.errors import UnavailableError
from .service import AgendaService as _LiveAgendaService


_TERMINAL_STATUSES = frozenset({"COMPLETED", "CANCELLED"})


class AgendaService(_LiveAgendaService):
    """Production AgendaService whose installed startup path is local-only."""

    @staticmethod
    def _actionable_startup_tasks(items: Any) -> list[Any]:
        """Never offer terminal Tasks from an older verified snapshot for Start."""
        return [
            task
            for task in (items or ())
            if not bool(getattr(task, "completed", False))
            and str(getattr(task, "status", "") or "") not in _TERMINAL_STATUSES
        ]

    def _has_startup_cache_capability(self) -> bool:
        adapter = getattr(self.tasks, "adapter", None)
        if callable(getattr(adapter, "cached_startup_items", None)):
            return True
        return callable(self.cached_tasks) and callable(self.cached_events)

    def _cached_startup_sources(self) -> tuple[list[Any], list[Any]]:
        """Read Task+Event startup facts from one verified local snapshot when able."""
        adapter = getattr(self.tasks, "adapter", None)
        bundle_reader = getattr(adapter, "cached_startup_items", None)
        if callable(bundle_reader):
            tasks, events = bundle_reader(completed=False)
            return (
                self._actionable_startup_tasks(tasks),
                self._ordinary_events(events),
            )

        # Compatibility for replacement adapters which provide separate cache bricks.
        if not callable(self.cached_tasks) or not callable(self.cached_events):
            raise UnavailableError("No verified Task/Event snapshot is available")
        try:
            tasks = list(self.cached_tasks(completed=False))
        except TypeError:
            tasks = [
                task
                for task in self.cached_tasks()
                if not bool(getattr(task, "completed", False))
            ]
        events = self._ordinary_events(self.cached_events())
        return self._actionable_startup_tasks(tasks), list(events)

    def startup_snapshot(self, days: int = 1, kind: str = "task"):
        """Return the background-maintained verified snapshot without live I/O.

        The installed application always supplies the cache capability.  Deliberately
        tiny replacement/test compositions that have no cache brick retain the base
        live behavior rather than being forced to emulate production infrastructure.
        If a cache capability exists but contains no verified snapshot, startup fails
        immediately as unknown/unavailable and never falls through to network I/O.
        """
        if not self._has_startup_cache_capability():
            return super().startup_snapshot(days=days, kind=kind)

        tasks, events = self._cached_startup_sources()
        cached_session = getattr(self.session, "cached_startup_snapshot", None)
        work_facts = cached_session(tasks) if callable(cached_session) else None
        return self._startup_result(
            tasks,
            events,
            days=days,
            kind=kind,
            work_facts=work_facts,
            stale=True,
        )

    def cached_startup_snapshot(self, days: int = 1, kind: str = "task"):
        """Read the cache route explicitly; never fall through to live CalDAV."""
        if not self._has_startup_cache_capability():
            raise UnavailableError("No verified Task/Event snapshot is available")
        tasks, events = self._cached_startup_sources()
        cached_session = getattr(self.session, "cached_startup_snapshot", None)
        work_facts = cached_session(tasks) if callable(cached_session) else None
        return self._startup_result(
            tasks,
            events,
            days=days,
            kind=kind,
            work_facts=work_facts,
            stale=True,
        )

    def live_startup_snapshot(self, days: int = 1, kind: str = "task"):
        """Explicit old live traversal for diagnostics/manual refresh only."""
        return super().startup_snapshot(days=days, kind=kind)


__all__ = ["AgendaService"]
