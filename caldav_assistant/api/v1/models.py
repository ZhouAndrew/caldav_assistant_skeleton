from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

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
    def complete(self): return self._service.complete(self) if self._service else None
    def start_task(self): return self._service.start(self) if self._service else None
    def pause(self): return self._service.pause(self) if self._service else None
    def resume(self): return self._service.resume(self) if self._service else None
    def set_due(self, due): return self._service.update(self, due=due) if self._service else None
    def edit(self, **changes): return self._service.update(self, **changes) if self._service else None
    def delete(self): return self._service.delete(self) if self._service else None

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

@dataclass
class AgendaItem:
    value: Any
    when: date | datetime | None = None
    kind: str = ""

@dataclass
class Agenda:
    items: list[AgendaItem] = field(default_factory=list)

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
