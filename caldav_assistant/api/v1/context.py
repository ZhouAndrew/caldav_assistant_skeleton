"""Stable v1 Object API context.

MODULE CONTRACT
- Imports: stdlib typing/dataclasses only.
- Provides: ``AssistantContext`` with the frozen public namespaces.
- Called by: bootstrap composition roots, extensions, Easy API.
- Must not: construct services/adapters, perform I/O, contain business rules,
  expose IPC details, or import ``caldav_assistant.internal``.

The namespace objects are intentionally structural/duck-typed.  On the service
side they are authoritative Core services; on the CLI side they are Remote*API
proxies or lightweight local UI/session/time services with the same public shape.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AssistantContext:
    """The stable public Object API root for CalDAV Assistant v1."""

    tasks: Any
    events: Any
    agenda: Any
    reminders: Any
    notifications: Any
    wordpress: Any
    ui: Any
    time: Any
    commands: Any
    activity: Any
    settings: Any
    session: Any


__all__ = ["AssistantContext"]
