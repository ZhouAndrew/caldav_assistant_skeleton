"""Unified reversible mutation manager for Task/Event actions."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from ...api import ActionResult, Event, Task
from ...api.v1.errors import NotFoundError, ValidationError


class UndoManager:
    """Persist and apply the most recent reversible Core mutation.

    Task/Event services only record reconstructable facts here.  Applying an undo
    delegates back through those same services, so CalDAV remains authoritative and
    no second mutation implementation is created.
    """

    def __init__(self, repo: Any) -> None:
        self.repo = repo
        self._tasks: Any = None
        self._events: Any = None
        self._applying = False

    def bind(self, *, tasks: Any, events: Any) -> None:
        self._tasks = tasks
        self._events = events

    def remember(self, payload: dict[str, Any]) -> bool:
        if self._applying:
            return False
        remember = getattr(self.repo, "remember", None)
        if not callable(remember):
            return False
        remember(payload)
        return True

    @contextmanager
    def _suspended(self):
        previous = self._applying
        self._applying = True
        try:
            yield
        finally:
            self._applying = previous

    def _require_services(self) -> tuple[Any, Any]:
        if self._tasks is None or self._events is None:
            raise RuntimeError("UndoManager is not bound to Task/Event services")
        return self._tasks, self._events

    def _apply(self, payload: dict[str, Any]) -> ActionResult:
        tasks, events = self._require_services()
        action = payload.get("action")

        with self._suspended():
            if action == "task.create":
                result = tasks.delete(payload["task_id"])
            elif action == "task.update":
                result = tasks.update(payload["task_id"], **dict(payload["before"]))
            elif action == "task.delete":
                snapshot = dict(payload["task"])
                result = tasks.create(Task(**snapshot))
            elif action == "event.create":
                result = events.delete(payload["event_id"])
            elif action == "event.update":
                result = events.update(payload["event_id"], **dict(payload["before"]))
            elif action == "event.delete":
                snapshot = dict(payload["event"])
                result = events.create(Event(**snapshot))
            else:
                raise ValidationError(f"Unsupported undo action: {action}")

        result.undo_available = False
        result.message = "Undone."
        return result

    def undo_last(self) -> ActionResult:
        latest = getattr(self.repo, "latest", None)
        discard = getattr(self.repo, "discard", None)
        if not callable(latest) or not callable(discard):
            raise RuntimeError("Undo repository does not support retrieval")

        entry = latest()
        if entry is None:
            raise NotFoundError("No action is available to undo")
        if not isinstance(entry, dict) or not isinstance(entry.get("payload"), dict):
            raise ValidationError("Malformed undo entry")

        # Keep the durable recovery point until the authoritative CalDAV inverse
        # mutation succeeds.  A conflict/offline failure therefore remains retryable.
        result = self._apply(entry["payload"])
        discard(int(entry["id"]))
        return result


__all__ = ["UndoManager"]
