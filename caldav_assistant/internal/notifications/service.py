"""Canonical notification application service.

MODULE CONTRACT
- Imports/calls: stable public validation errors + ``NotificationAdapter``.
- Provides: ``NotificationService.send``.
- Must not: choose reminder timing, read Task/Event state, call operating-system APIs
  directly, print CLI output, or access SQLite.

The service owns only application-level input validation and delegates the actual
delivery to the injected adapter.
"""
from __future__ import annotations

from typing import Any

from ...api.v1.errors import ValidationError
from .adapter import NotificationAdapter


class NotificationService:
    """Small stable facade shared by Reminder, IPC/Object API and Easy API."""

    def __init__(self, adapter: NotificationAdapter) -> None:
        self.adapter = adapter

    def send(
        self,
        title: str,
        body: str = "",
        actions: Any = None,
    ) -> None:
        if not isinstance(title, str) or not title.strip():
            raise ValidationError("Notification title must not be empty")
        if not isinstance(body, str):
            raise ValidationError("Notification body must be text")

        if actions is not None and not isinstance(actions, (list, tuple)):
            raise ValidationError(
                "Notification actions must be a list/tuple or None"
            )

        # Keep the public/service boundary stable.  Action semantics are deliberately
        # not invented here; concrete adapters either support them or fail explicitly.
        normalized_actions = None if actions is None else list(actions)

        return self.adapter.notify(
            title.strip(),
            body,
            normalized_actions,
        )
