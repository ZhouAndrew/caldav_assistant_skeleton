"""CalDAV Assistant Full Extension / Object API v1.

Everything exported here is part of the versioned public API surface.
Implementations live behind AssistantContext namespaces; this module contains no
adapter selection, IPC wiring, storage access, or Core business logic.
"""
from .context import AssistantContext
from .errors import (
    AmbiguousError,
    CalDAVAssistantError,
    ConflictError,
    ExtensionError,
    NotFoundError,
    PermissionError,
    UnavailableError,
    ValidationError,
)
from .hooks import on
from .models import (
    ActionResult,
    Activity,
    Agenda,
    AgendaItem,
    Event,
    Reminder,
    Task,
)

__all__ = [
    "AssistantContext",
    "Task",
    "Event",
    "Agenda",
    "AgendaItem",
    "Reminder",
    "Activity",
    "ActionResult",
    "CalDAVAssistantError",
    "NotFoundError",
    "AmbiguousError",
    "ValidationError",
    "ConflictError",
    "UnavailableError",
    "PermissionError",
    "ExtensionError",
    "on",
]
