"""SyncEngine wrapper that refreshes small background-ready auxiliary snapshots.

Task/Event synchronization remains authoritative CalDAV -> SQLite cache.  Post-sync
hooks are advisory only: they may refresh independent Assistant state (for example the
last verified current-work fact) but can never make a successful Task/Event sync fail.
"""
from __future__ import annotations

from typing import Any, Callable

from .sync import SyncEngine as _BaseSyncEngine


class SyncEngine(_BaseSyncEngine):
    """Base SyncEngine plus failure-isolated post-sync hooks."""

    def __init__(self, adapter: Any, cache: Any):
        super().__init__(adapter, cache)
        self._post_sync_hooks: list[Callable[[], Any]] = []

    def register_post_sync_hook(self, hook: Callable[[], Any]) -> None:
        if callable(hook) and hook not in self._post_sync_hooks:
            self._post_sync_hooks.append(hook)

    def _run_post_sync_hooks(self) -> None:
        for hook in tuple(self._post_sync_hooks):
            try:
                hook()
            except Exception:
                # Auxiliary snapshot refresh must never turn a successful CalDAV
                # Task/Event sync into a failure.  The previous verified auxiliary
                # snapshot remains available and is visibly stale/background state.
                continue

    def refresh(self):
        result = super().refresh()
        self._run_post_sync_hooks()
        return result

    def incremental_sync(self):
        result = super().incremental_sync()
        self._run_post_sync_hooks()
        return result


__all__ = ["SyncEngine"]
