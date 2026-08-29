"""Stable public v1 domain objects.

These are deliberately small data objects. Validation and authoritative mutation
remain in Core Services. Convenience methods merely delegate to the service that
bound the object; they never reproduce Task/Event business rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterator

from .errors import UnavailableError


@dataclass
class ActionResult:
    success: bool
    message: str = ""
    affected: Any = None
    undo_available: bool = False


@dataclass
class Task:
    id: str = ""
    summary: str = ""
    description: str = ""
    start: date | datetime | None = None
    due: date | datetime | None = None
    status: str = "NEEDS-ACTION"
    completed: bool = False
    completed_at: datetime | None = None
    priority: int | None = None
    categories: list[str] = field(default_factory=list)
    overdue: bool = False
    raw: Any = None
    _service: Any = field(default=None, repr=False, compare=False)

    def _bound_service(self) -> Any:
        if self._service is None:
            raise UnavailableError(
                "Task is not bound to an Object API service; use ctx.tasks for this object"
            )
        return self._service

    def complete(self) -> ActionResult:
        return self._bound_service().complete(self)

    def start_task(self) -> ActionResult:
        """Start this Task through Core Service.

        ``task.start`` is the frozen DTSTART-like data attribute, so Python cannot
        simultaneously expose a callable ``task.start()`` under the same name.
        """
        return self._bound_service().start(self)

    def pause(self) -> ActionResult:
        return self._bound_service().pause(self)

    def resume(self) -> ActionResult:
        return self._bound_service().resume(self)

    def set_due(self, due: Any) -> ActionResult:
        return self._bound_service().update(self, due=due)

    def edit(self, **changes: Any) -> ActionResult:
        return self._bound_service().update(self, **changes)

    def delete(self) -> ActionResult:
        return self._bound_service().delete(self)


@dataclass
class Event:
    id: str = ""
    summary: str = ""
    start: date | datetime | None = None
    end: date | datetime | None = None
    location: str = ""
    description: str = ""
    categories: list[str] = field(default_factory=list)
    raw: Any = None
    _service: Any = field(default=None, repr=False, compare=False)

    def _bound_service(self) -> Any:
        if self._service is None:
            raise UnavailableError(
                "Event is not bound to an Object API service; use ctx.events for this object"
            )
        return self._service

    def edit(self, **changes: Any) -> ActionResult:
        return self._bound_service().update(self, **changes)

    def delete(self) -> ActionResult:
        return self._bound_service().delete(self)


@dataclass
class AgendaItem:
    value: Any
    when: date | datetime | None = None
    kind: str = ""


@dataclass
class Agenda:
    items: list[AgendaItem] = field(default_factory=list)

    def __iter__(self) -> Iterator[AgendaItem]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int | slice) -> AgendaItem | list[AgendaItem]:
        return self.items[index]


@dataclass(frozen=True, slots=True)
class NotificationRequest:
    """Platform-neutral notification decision returned by reminder rules."""

    key: str
    when: datetime
    title: str
    body: str = ""
    actions: tuple[str, ...] = ()
    source: str = ""
    object_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Reminder:
    id: str = ""
    title: str = ""
    when: date | datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Activity:
    timestamp: datetime
    action: str
    object_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "ActionResult",
    "Task",
    "Event",
    "AgendaItem",
    "Agenda",
    "NotificationRequest",
    "Reminder",
    "Activity",
]
