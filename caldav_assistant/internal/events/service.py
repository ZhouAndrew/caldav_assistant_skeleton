"""Canonical Event business service.

MODULE CONTRACT
- Imports/calls: public Event/ActionResult/errors + CalDAVAdapter + injected
  ActivityService/UndoManager collaborators.
- Provides: EventService query and mutation actions.
- Must not: access CalDAV XML/HTTP directly, read/write SQLite directly, print CLI
  output, or contain Task/Agenda/Reminder/WordPress logic.

CalDAV remains the source of truth. Mutations are successful only after
CalDAVAdapter confirms them. Activity/Undo side effects happen afterwards.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime
from typing import Any

from ...api import ActionResult, Event
from ...api.v1.errors import AmbiguousError, NotFoundError, ValidationError
from ..caldav.adapter import CalDAVAdapter


class EventService:
    """Canonical Event business layer above :class:`CalDAVAdapter`."""

    _MUTABLE_FIELDS = frozenset(
        {
            "summary",
            "start",
            "end",
            "location",
            "description",
            "categories",
        }
    )

    def __init__(
        self,
        adapter: CalDAVAdapter,
        activity: Any = None,
        undo: Any = None,
    ) -> None:
        self.adapter = adapter
        self.activity = activity
        self.undo = undo

    # ------------------------------------------------------------------
    # Small reusable bricks
    # ------------------------------------------------------------------
    def _bind(self, event: Event) -> Event:
        """Attach this service for future object convenience methods."""
        if not isinstance(event, Event):
            raise TypeError("CalDAVAdapter must return Event objects")
        event._service = self
        return event

    @staticmethod
    def _require_id(event: Event) -> str:
        event_id = str(event.id or "").strip()
        if not event_id:
            raise ValidationError("Event has no id")
        return event_id

    @staticmethod
    def _validate_summary(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("Event summary must not be empty")
        return value.strip()

    @staticmethod
    def _validate_temporal(value: Any, name: str) -> date | datetime | None:
        if value is not None and not isinstance(value, date):
            raise ValidationError(f"{name} must be date, datetime, or None")
        return value

    @classmethod
    def _normalize_changes(cls, changes: dict[str, Any]) -> dict[str, Any]:
        if not changes:
            raise ValidationError("No event changes supplied")

        unknown = set(changes) - cls._MUTABLE_FIELDS
        if unknown:
            raise ValidationError(
                f"Unsupported Event fields: {', '.join(sorted(unknown))}"
            )

        normalized = dict(changes)

        if "summary" in normalized:
            normalized["summary"] = cls._validate_summary(normalized["summary"])

        for key in ("start", "end"):
            if key in normalized:
                normalized[key] = cls._validate_temporal(normalized[key], key)

        for key in ("location", "description"):
            if key in normalized and not isinstance(normalized[key], str):
                raise ValidationError(f"{key} must be text")

        if "categories" in normalized:
            value = normalized["categories"]
            if not isinstance(value, (list, tuple)) or not all(
                isinstance(item, str) for item in value
            ):
                raise ValidationError("categories must contain strings")
            normalized["categories"] = list(value)

        return normalized

    @classmethod
    def _copy_for_create(cls, value: Event) -> Event:
        """Validate a detached Event without mutating the caller's object."""
        event = replace(value, categories=list(value.categories), _service=None)
        event.summary = cls._validate_summary(event.summary)
        validated = cls._normalize_changes(
            {name: getattr(event, name) for name in cls._MUTABLE_FIELDS}
        )
        for name, item in validated.items():
            setattr(event, name, item)
        return event

    @classmethod
    def _snapshot(cls, event: Event) -> dict[str, Any]:
        """Keep reconstructable Event facts; never persist ``raw`` here."""
        return {
            "id": event.id,
            **{
                name: deepcopy(getattr(event, name))
                for name in cls._MUTABLE_FIELDS
            },
        }

    def _record(self, action: str, event: Event, **metadata: Any) -> None:
        if self.activity is not None:
            self.activity.record(action, event.id, **metadata)

    def _remember(self, payload: dict[str, Any]) -> bool:
        if self.undo is None:
            return False
        self.undo.remember(payload)
        return True

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def list(self, **filters: Any) -> list[Event]:
        return [self._bind(event) for event in self.adapter.list_events(**filters)]

    def find(self, query: str, **filters: Any) -> Event:
        if not isinstance(query, str) or not query.strip():
            raise ValidationError("Event query must not be empty")

        needle = query.strip().casefold()
        items = self.list(**filters)

        exact = [
            event for event in items if event.summary.casefold() == needle
        ]
        matches = exact or [
            event for event in items if needle in event.summary.casefold()
        ]

        if not matches:
            raise NotFoundError(query)
        if len(matches) > 1:
            raise AmbiguousError(query)
        return matches[0]

    def get(self, event: Event | str) -> Event:
        if isinstance(event, Event):
            return self._bind(event)
        if not isinstance(event, str) or not event.strip():
            raise ValidationError("Event id must not be empty")

        try:
            return self._bind(self.adapter.get_event(event.strip()))
        except KeyError as exc:
            raise NotFoundError(event) from exc

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------
    def create(self, summary: Event | str, **fields: Any) -> ActionResult:
        if isinstance(summary, Event):
            if fields:
                raise ValidationError(
                    "Do not pass fields when creating from an Event object"
                )
            candidate = self._copy_for_create(summary)
        else:
            if not isinstance(summary, str):
                raise ValidationError("Event summary must be text")

            unknown = set(fields) - self._MUTABLE_FIELDS
            if unknown:
                raise ValidationError(
                    f"Unsupported Event fields: {', '.join(sorted(unknown))}"
                )

            candidate = Event(
                summary=self._validate_summary(summary),
                **fields,
            )
            candidate = self._copy_for_create(candidate)

        created = self._bind(self.adapter.create_event(candidate))
        self._require_id(created)

        undo_available = self._remember(
            {"action": "event.create", "event_id": created.id}
        )
        self._record("event_created", created)
        return ActionResult(
            True,
            affected=created,
            undo_available=undo_available,
        )

    def update(self, event: Event | str, **changes: Any) -> ActionResult:
        obj = self.get(event)
        event_id = self._require_id(obj)
        normalized = self._normalize_changes(changes)

        before = {
            key: deepcopy(getattr(obj, key))
            for key in normalized
        }

        updated = self._bind(
            self.adapter.update_event(event_id, normalized)
        )

        undo_available = self._remember(
            {
                "action": "event.update",
                "event_id": event_id,
                "before": before,
                "after": deepcopy(normalized),
            }
        )
        self._record(
            "event_updated",
            updated,
            changes=deepcopy(normalized),
        )
        return ActionResult(
            True,
            affected=updated,
            undo_available=undo_available,
        )

    def delete(self, event: Event | str) -> ActionResult:
        obj = self.get(event)
        event_id = self._require_id(obj)
        snapshot = self._snapshot(obj)

        self.adapter.delete_event(event_id)

        undo_available = self._remember(
            {
                "action": "event.delete",
                "event_id": event_id,
                "event": snapshot,
            }
        )
        self._record("event_deleted", obj)
        return ActionResult(
            True,
            affected=obj,
            undo_available=undo_available,
        )