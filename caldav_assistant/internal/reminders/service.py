"""Reminder orchestration service.

MODULE CONTRACT
- Imports/calls: ReminderEngine, Task/Event query services, TemporalService,
  assistant-state repository, and NotificationService.
- Provides: ReminderService list/create/snooze/cancel/next_due/process_due.
- Must not: call OS notification APIs, write CalDAV directly, decide VALARM/Due
  reminder policy, or turn Assistant local state into a second Task/Event database.

Responsibilities
----------------
1. Keep *Assistant-owned* explicit reminders and delivery de-duplication state.
2. Read Task/Event facts through TaskService/EventService.
3. Ask ReminderEngine for NotificationRequest decisions.
4. Deliver due requests through NotificationService.
5. Mark a request delivered only after NotificationService succeeds.

The service deliberately accepts the small variations of the internal ReminderEngine
call signature that existed during the scaffold phase (``reminders`` vs
``explicit_reminders``).  That compatibility is internal only; public v1 APIs do not
depend on these names.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import inspect
from typing import Any
from uuid import uuid4

from ...api import Reminder
from ...api.v1.errors import NotFoundError, ValidationError


class ReminderService:
    """Application-level orchestration around the pure ReminderEngine."""

    _ITEMS_KEY = "reminders.items.v1"
    _DELIVERED_KEY = "reminders.delivered_keys.v1"

    def __init__(
        self,
        engine: Any,
        notifications: Any,
        temporal: Any,
        state: Any,
        tasks: Any,
        events: Any,
    ) -> None:
        self.engine = engine
        self.notifications = notifications
        self.temporal = temporal
        self.state = state
        self.tasks = tasks
        self.events = events

    # ------------------------------------------------------------------
    # Explicit Assistant reminders (local auxiliary state, not CalDAV facts)
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_title(title: Any) -> str:
        if not isinstance(title, str) or not title.strip():
            raise ValidationError("Reminder title must not be empty")
        return title.strip()

    def _parse_when(self, value: Any) -> date | datetime:
        if isinstance(value, str):
            parsed = self.temporal.parse_datetime(value, bias="future")
            if not isinstance(parsed, date):
                raise ValidationError("Reminder time must be a date or datetime")
            return parsed
        if isinstance(value, date):
            return value
        raise ValidationError("Reminder time must be a date, datetime, or text")

    @staticmethod
    def _encode_when(value: date | datetime) -> dict[str, str]:
        return {
            "kind": "datetime" if isinstance(value, datetime) else "date",
            "value": value.isoformat(),
        }

    @staticmethod
    def _decode_when(value: Any) -> date | datetime:
        if isinstance(value, dict):
            raw = str(value.get("value", ""))
            if value.get("kind") == "datetime":
                return datetime.fromisoformat(raw)
            return date.fromisoformat(raw)

        # Read old/simple state defensively if it already exists.
        raw = str(value)
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return date.fromisoformat(raw)

    def _load_items(self) -> list[Reminder]:
        raw_items = self.state.get(self._ITEMS_KEY, []) or []
        result: list[Reminder] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            try:
                result.append(
                    Reminder(
                        id=str(raw.get("id", "")),
                        title=str(raw.get("title", "")),
                        when=self._decode_when(raw.get("when")),
                        metadata=dict(raw.get("metadata") or {}),
                    )
                )
            except (TypeError, ValueError):
                # A single corrupt local helper row must not hide valid reminders.
                continue
        return result

    def _save_items(self, items: list[Reminder]) -> None:
        payload = [
            {
                "id": item.id,
                "title": item.title,
                "when": self._encode_when(item.when),
                "metadata": dict(item.metadata),
            }
            for item in items
            if isinstance(item.when, date)
        ]
        self.state.set(self._ITEMS_KEY, payload)

    def list(self, **filters: Any) -> list[Reminder]:
        """Return explicit Assistant reminders, optionally filtered by metadata.

        ``id`` and ``title`` filter their public fields; all other filters match
        ``Reminder.metadata``. Unknown filters simply produce no match.
        """
        items = self._load_items()
        if not filters:
            return sorted(items, key=self._reminder_sort_key)

        def matches(item: Reminder) -> bool:
            for key, expected in filters.items():
                if key == "id":
                    actual = item.id
                elif key == "title":
                    actual = item.title
                else:
                    actual = item.metadata.get(key)
                if actual != expected:
                    return False
            return True

        return sorted(
            [item for item in items if matches(item)],
            key=self._reminder_sort_key,
        )

    @staticmethod
    def _reminder_sort_key(item: Reminder) -> tuple[int, str]:
        when = item.when
        if isinstance(when, datetime):
            return (0, when.isoformat())
        if isinstance(when, date):
            return (1, when.isoformat())
        return (2, "")

    def create(self, title: str, when: Any, **options: Any) -> Reminder:
        title = self._validate_title(title)
        parsed = self._parse_when(when)

        reminder = Reminder(
            id=f"rem-{uuid4().hex}",
            title=title,
            when=parsed,
            metadata=dict(options),
        )
        items = self._load_items()
        items.append(reminder)
        self._save_items(items)
        return reminder

    def _resolve(self, reminder: Reminder | str) -> Reminder:
        reminder_id = reminder.id if isinstance(reminder, Reminder) else reminder
        if not isinstance(reminder_id, str) or not reminder_id.strip():
            raise ValidationError("Reminder id must not be empty")

        for item in self._load_items():
            if item.id == reminder_id.strip():
                return item
        raise NotFoundError(reminder_id)

    def snooze(self, reminder: Reminder | str, until: Any) -> Reminder:
        target = self._resolve(reminder)
        target.when = self._parse_when(until)

        items = self._load_items()
        items = [target if item.id == target.id else item for item in items]
        self._save_items(items)

        # A snoozed explicit reminder is a new delivery opportunity.  Engine delivery
        # keys normally contain the reminder id; remove only those keys, leaving Task/
        # Event de-duplication untouched.
        delivered = self._delivered_keys()
        retained = {key for key in delivered if target.id not in key}
        if retained != delivered:
            self._save_delivered_keys(retained)

        return target

    def cancel(self, reminder: Reminder | str) -> Reminder:
        target = self._resolve(reminder)
        items = [item for item in self._load_items() if item.id != target.id]
        self._save_items(items)
        return target

    # ------------------------------------------------------------------
    # Delivery de-duplication state
    # ------------------------------------------------------------------
    def _delivered_keys(self) -> set[str]:
        value = self.state.get(self._DELIVERED_KEY, []) or []
        if not isinstance(value, (list, tuple, set)):
            return set()
        return {str(item) for item in value}

    def _save_delivered_keys(self, values: set[str]) -> None:
        self.state.set(self._DELIVERED_KEY, sorted(values))

    @staticmethod
    def _request_key(request: Any) -> str:
        for name in (
            "delivery_key",
            "dedupe_key",
            "key",
            "reminder_id",
            "id",
        ):
            value = getattr(request, name, None)
            if callable(value):
                value = value()
            if value not in (None, ""):
                return str(value)

        when = ReminderService._request_when(request)
        kind = getattr(request, "kind", "")
        entity = (
            getattr(request, "entity_id", None)
            or getattr(request, "object_id", None)
            or ""
        )
        title = getattr(request, "title", "")
        return "|".join(
            [
                str(kind),
                str(entity),
                when.isoformat() if isinstance(when, date) else "",
                str(title),
            ]
        )

    @staticmethod
    def _request_when(request: Any) -> date | datetime | None:
        for name in ("due_at", "when", "at", "trigger_at"):
            value = getattr(request, name, None)
            if isinstance(value, date):
                return value
        return None

    # ------------------------------------------------------------------
    # ReminderEngine bridge
    # ------------------------------------------------------------------
    def _engine_call(self, method_name: str, *, now: datetime | None = None):
        method = getattr(self.engine, method_name, None)
        if not callable(method):
            return None

        values = {
            "tasks": self.tasks.list(),
            "events": self.events.list(),
            "reminders": self.list(),
            "explicit_reminders": self.list(),
            "delivered_keys": self._delivered_keys(),
            "now": now,
            "at": now,
            "after": now,
        }

        signature = inspect.signature(method)
        kwargs: dict[str, Any] = {}
        unknown_required: list[str] = []

        for name, parameter in signature.parameters.items():
            if name in values:
                # ``None`` is meaningful for now/at/after and lets the engine use
                # its own clock when desired.
                kwargs[name] = values[name]
            elif (
                parameter.default is inspect.Parameter.empty
                and parameter.kind
                not in (
                    inspect.Parameter.VAR_POSITIONAL,
                    inspect.Parameter.VAR_KEYWORD,
                )
            ):
                unknown_required.append(name)

        if unknown_required:
            raise TypeError(
                f"Unsupported ReminderEngine.{method_name} contract; "
                f"required parameters: {', '.join(unknown_required)}"
            )

        return method(**kwargs)

    def _evaluate(self, now: datetime | None = None) -> list[Any]:
        result = self._engine_call("evaluate", now=now)
        if result is not None:
            return list(result)

        # Compatibility with engines that expose ``due`` directly.
        result = self._engine_call("due", now=now)
        if result is None:
            raise TypeError(
                "ReminderEngine must provide evaluate(...) or due(...)"
            )
        return list(result)

    @staticmethod
    def _coerce_now(now: datetime | None) -> datetime:
        if now is None:
            return datetime.now(timezone.utc)
        if not isinstance(now, datetime):
            raise ValidationError("now must be datetime")
        return now

    @staticmethod
    def _is_due(when: date | datetime | None, now: datetime) -> bool:
        # Date-only values deliberately are NOT converted to midnight. ReminderEngine
        # may apply an explicit configured policy later; this service does not invent it.
        if not isinstance(when, datetime):
            return False

        if when.tzinfo is None and now.tzinfo is not None:
            # Do not guess a timezone for a floating datetime.
            return False
        if when.tzinfo is not None and now.tzinfo is None:
            return False

        return when <= now

    def due(self, now: datetime | None = None) -> list[Any]:
        """Return due, not-yet-delivered NotificationRequests without sending."""
        moment = self._coerce_now(now)

        direct = self._engine_call("due", now=moment)
        requests = list(direct) if direct is not None else self._evaluate(moment)
        delivered = self._delivered_keys()

        return [
            request
            for request in requests
            if self._request_key(request) not in delivered
            and self._is_due(self._request_when(request), moment)
        ]

    def next_due(self, now: datetime | None = None) -> datetime | None:
        """Return the next precise wake time; never coerce date-only to midnight."""
        moment = self._coerce_now(now)

        direct = self._engine_call("next_due", now=moment)
        if direct is not None:
            if isinstance(direct, datetime):
                return direct
            direct_when = self._request_when(direct)
            if isinstance(direct_when, datetime):
                return direct_when

        delivered = self._delivered_keys()
        candidates: list[datetime] = []
        for request in self._evaluate(moment):
            if self._request_key(request) in delivered:
                continue
            when = self._request_when(request)
            if isinstance(when, datetime):
                candidates.append(when)

        return min(candidates) if candidates else None

    def process_due(self, now: datetime | None = None) -> list[Any]:
        """Deliver due requests and persist de-duplication only after success.

        If NotificationService raises, the failing request is intentionally not marked
        delivered.  Successfully delivered requests before it stay marked, so a retry
        cannot duplicate them.
        """
        sent: list[Any] = []
        delivered = self._delivered_keys()

        for request in self.due(now):
            title = self._validate_title(getattr(request, "title", ""))
            body = getattr(request, "body", None)
            if body is None:
                body = getattr(request, "description", "")
            if body is None:
                body = ""
            actions = getattr(request, "actions", None)

            self.notifications.send(title, str(body), actions)

            key = self._request_key(request)
            delivered.add(key)
            self._save_delivered_keys(delivered)
            sent.append(request)

        return sent
