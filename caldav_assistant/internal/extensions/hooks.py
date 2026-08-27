"""Failure-isolated internal hook registry.

Hooks are extension points, never an alternate Task/Event source of truth.  One hook
failure is recorded and skipped; remaining handlers for the same event still run.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable

from ...api.v1.errors import NotFoundError, ValidationError


HookHandler = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class HookEntry:
    event: str
    handler: HookHandler
    owner: str | None = None


@dataclass(frozen=True, slots=True)
class HookFailure:
    event: str
    owner: str | None
    error_type: str
    message: str


class HookRegistry:
    def __init__(self) -> None:
        self._entries: list[HookEntry] = []
        self._failures: list[HookFailure] = []
        self._lock = RLock()

    @staticmethod
    def _event(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("Hook event must not be empty")
        return value.strip()

    @staticmethod
    def _owner(value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("Hook owner must be non-empty text")
        return value.strip()

    def register(
        self,
        event: str,
        handler: HookHandler,
        *,
        owner: str | None = None,
    ) -> HookEntry:
        clean_event = self._event(event)
        clean_owner = self._owner(owner)
        if not callable(handler):
            raise ValidationError("Hook handler must be callable")

        entry = HookEntry(clean_event, handler, clean_owner)
        with self._lock:
            for existing in self._entries:
                if (
                    existing.event == clean_event
                    and existing.handler is handler
                    and existing.owner == clean_owner
                ):
                    return existing
            self._entries.append(entry)
        return entry

    def unregister(self, event: str, handler: HookHandler) -> HookEntry:
        clean_event = self._event(event)
        with self._lock:
            for index, entry in enumerate(self._entries):
                if entry.event == clean_event and entry.handler is handler:
                    return self._entries.pop(index)
        raise NotFoundError(clean_event)

    def unregister_owner(self, owner: str) -> tuple[HookEntry, ...]:
        clean_owner = self._owner(owner)
        assert clean_owner is not None
        with self._lock:
            removed = tuple(
                entry for entry in self._entries if entry.owner == clean_owner
            )
            if removed:
                self._entries = [
                    entry for entry in self._entries if entry.owner != clean_owner
                ]
            return removed

    def entries(self, event: str | None = None) -> tuple[HookEntry, ...]:
        with self._lock:
            if event is None:
                return tuple(self._entries)
            clean_event = self._event(event)
            return tuple(
                entry for entry in self._entries if entry.event == clean_event
            )

    def emit(self, event: str, *args: Any, **kwargs: Any) -> list[Any]:
        clean_event = self._event(event)
        entries = self.entries(clean_event)
        results: list[Any] = []

        for entry in entries:
            try:
                results.append(entry.handler(*args, **kwargs))
            except Exception as exc:
                failure = HookFailure(
                    event=clean_event,
                    owner=entry.owner,
                    error_type=type(exc).__name__,
                    message=str(exc),
                )
                with self._lock:
                    self._failures.append(failure)
                # Isolation boundary: do not prevent later hooks from running.
                continue

        return results

    def failures(self, *, clear: bool = False) -> tuple[HookFailure, ...]:
        with self._lock:
            snapshot = tuple(self._failures)
            if clear:
                self._failures.clear()
            return snapshot


__all__ = ["HookEntry", "HookFailure", "HookRegistry"]
