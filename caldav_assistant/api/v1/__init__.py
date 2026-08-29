"""CalDAV Assistant Full Extension / Object API v1.

Everything exported here is part of the versioned public API surface.
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
from .hooks import (
    EventBus,
    HookDispatchReport,
    HookEvent,
    HookFailure,
    HookHandle,
    emit,
    get_event_bus,
    off,
    on,
    unregister_owner,
)
from .models import (
    ActionResult,
    Activity,
    Agenda,
    AgendaItem,
    Event,
    Reminder,
    Task,
)
from .reminder_rules import NotificationRequest, reminder_rule

__all__ = [
    "AssistantContext",
    "Task",
    "Event",
    "Agenda",
    "AgendaItem",
    "Reminder",
    "Activity",
    "ActionResult",
    "NotificationRequest",
    "reminder_rule",
    "CalDAVAssistantError",
    "NotFoundError",
    "AmbiguousError",
    "ValidationError",
    "ConflictError",
    "UnavailableError",
    "PermissionError",
    "ExtensionError",
    "EventBus",
    "HookDispatchReport",
    "HookEvent",
    "HookFailure",
    "HookHandle",
    "emit",
    "get_event_bus",
    "off",
    "on",
    "unregister_owner",
]
