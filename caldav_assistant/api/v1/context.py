"""Stable v1 Object API context.

MODULE CONTRACT
- Imports: stdlib dataclasses + public structural Protocols only.
- Provides: ``AssistantContext`` with the frozen public namespaces.
- Called by: bootstrap composition roots, extensions, Easy API.
- Must not: construct services/adapters, perform I/O, contain business rules,
  expose IPC details, or import ``caldav_assistant.internal``.

The namespace objects remain structural/duck-typed.  On the service side they are
authoritative Core services; on the CLI side they are Remote*API proxies or lightweight
local UI/session/time services.  The Protocol annotations exist for editor/static type
support and do not require implementations to subclass public API types.
"""
from __future__ import annotations

from dataclasses import dataclass

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


@dataclass
class AssistantContext:
    """The stable public Object API root for CalDAV Assistant v1."""

    tasks: TasksAPI
    events: EventsAPI
    agenda: AgendaAPI
    reminders: RemindersAPI
    notifications: NotificationsAPI
    wordpress: WordPressAPI
    ui: UIAPI
    time: TemporalAPI
    commands: CommandsAPI
    activity: ActivityAPI
    settings: SettingsAPI
    session: SessionAPI


__all__ = ["AssistantContext"]
