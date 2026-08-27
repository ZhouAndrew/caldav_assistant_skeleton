from __future__ import annotations

import caldav_assistant.api as api
import caldav_assistant.api.v1 as v1


PUBLIC_NAMES = {
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
}


def test_default_api_is_the_current_stable_v1_surface():
    assert PUBLIC_NAMES <= set(api.__all__)
    assert PUBLIC_NAMES <= set(v1.__all__)

    for name in PUBLIC_NAMES:
        assert getattr(api, name) is getattr(v1, name)


def test_assistant_context_exposes_all_frozen_namespaces_in_order():
    values = {name: object() for name in (
        "tasks",
        "events",
        "agenda",
        "reminders",
        "notifications",
        "wordpress",
        "ui",
        "time",
        "commands",
        "activity",
        "settings",
        "session",
    )}

    ctx = api.AssistantContext(**values)

    for name, value in values.items():
        assert getattr(ctx, name) is value
