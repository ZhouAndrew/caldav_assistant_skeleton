"""SyncEngine wrapper that refreshes small background-ready auxiliary snapshots.

Task/Event synchronization remains authoritative CalDAV -> SQLite cache. Ready-state
hooks refresh independent Assistant state such as the current Work VEVENT snapshot.
They are failure-isolated from a successful Task/Event sync, but can also be executed
as an independent maintenance lane so a slow Task/Event sync cannot starve them.
"""
from __future__ import annotations

from threading import RLock
from typing import Any, Callable

from .sync import SyncEngine as _BaseSyncEngine


class SyncEngine(_BaseSyncEngine):
    """Base SyncEngine plus serialized ready-state refresh hooks."""

    def __init__(self, adapter: Any, cache: Any):
        super().__init__(adapter, cache)
        self._post_sync_hooks: list[Callable[[], Any]] = []
        self._ready_lock = RLock()

    def register_post_sync_hook(self, hook: Callable[[], Any]) -> None:
        if callable(hook) and hook not in self._post_sync_hooks:
            self._post_sync_hooks.append(hook)

    def _run_post_sync_hooks(self) -> None:
        # Preserve the historical contract: auxiliary failure never makes an
        # otherwise successful Task/Event sync fail.
        with self._ready_lock:
            for hook in tuple(self._post_sync_hooks):
                try:
                    hook()
                except Exception:
                    continue

    def refresh_ready_state(self) -> dict[str, int]:
        """Refresh ready-state independently and report failures to maintenance."""
        completed = 0
        errors: list[BaseException] = []
        with self._ready_lock:
            for hook in tuple(self._post_sync_hooks):
                try:
                    hook()
                except BaseException as exc:
                    errors.append(exc)
                else:
                    completed += 1
        if errors:
            first = errors[0]
            raise RuntimeError(
                f"{len(errors)} ready-state refresh hook(s) failed; "
                f"first: {type(first).__name__}: {first}"
            ) from first
        return {"hooks": completed}

    def refresh(self):
        result = super().refresh()
        self._run_post_sync_hooks()
        return result

    def incremental_sync(self):
        result = super().incremental_sync()
        self._run_post_sync_hooks()
        return result


__all__ = ["SyncEngine"]
