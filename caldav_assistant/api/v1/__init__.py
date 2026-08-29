"""CalDAV Assistant Full Extension / Object API v1.

Everything exported here is part of the versioned public API surface.
Implementations live behind AssistantContext namespaces; this module contains no
adapter selection, IPC wiring, storage access, or Core business logic.
"""
from .catalog import APIEntry, api_catalog, api_describe, api_exists, api_find
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
from .protocols import (
    ActivityAPI,
    AgendaAPI,
    CommandsAPI,
    EventsAPI,
    NotificationsAPI,
    RemindersAPI,
    SessionAPI,
    SettingsAPI,
    TasksAPI,
    TemporalAPI,
    UIAPI,
    WordPressAPI,
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
    "TasksAPI",
    "EventsAPI",
    "AgendaAPI",
    "RemindersAPI",
    "NotificationsAPI",
    "WordPressAPI",
    "UIAPI",
    "TemporalAPI",
    "CommandsAPI",
    "ActivityAPI",
    "SettingsAPI",
    "SessionAPI",
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
    "APIEntry",
    "api_catalog",
    "api_find",
    "api_exists",
    "api_describe",
]
