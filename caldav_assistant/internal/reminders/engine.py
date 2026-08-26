"""Pure reminder scheduling and notification-request generation.

MODULE CONTRACT
- Reads: public Task/Event/Reminder objects and already-loaded ``raw`` data.
- Provides: NotificationRequest + ReminderEngine.
- Must not: call NotificationService/OS APIs, CalDAV/XML/HTTP, SQLite,
  CLI input/output, or mutate Task/Event/Reminder objects.

ReminderService owns persistence, snooze state and delivered-state.
NotificationService owns actual OS notification delivery.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ...api import Event, Reminder, Task


@dataclass(frozen=True, slots=True)
class NotificationRequest:
    """Platform-neutral output produced by ReminderEngine."""

    key: str
    when: datetime
    title: str
    body: str = ""
    actions: tuple[str, ...] = ()
    source: str = ""
    object_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ReminderEngine:
    """Combine reminder sources into deterministic NotificationRequests."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        tasks: Iterable[Task] = (),
        events: Iterable[Event] = (),
        reminders: Iterable[Reminder] = (),
        *,
        now: datetime | None = None,
        rules: Iterable[Any] = (),
    ) -> list[NotificationRequest]:
        """Build all concrete notification requests.

        Sources:
        - explicit Reminder objects;
        - Task due datetime;
        - Event start datetime;
        - DISPLAY VALARM;
        - injected user rules.

        Important temporal contract:
        date-only values remain date-only.  They are NOT silently converted to
        midnight merely to make scheduling convenient.
        """

        clock = self._clock(now)
        tz = clock.tzinfo or timezone.utc

        requests: list[NotificationRequest] = []

        # Explicit reminders.  A snoozed Reminder is still a Reminder whose
        # concrete ``when`` has been changed by ReminderService.
        for reminder in reminders:
            request = self._from_reminder(reminder, tz)
            if request is not None:
                requests.append(request)

        # Completed/cancelled tasks no longer create reminder requests.
        active_tasks = [
            task
            for task in tasks
            if self._active_task(task)
        ]

        for task in active_tasks:
            requests.extend(
                self._from_item(task, kind="task", tz=tz)
            )

        event_items = [
            event
            for event in events
            if isinstance(event, Event)
        ]

        for event in event_items:
            requests.extend(
                self._from_item(event, kind="event", tz=tz)
            )

        # User rules are ordinary injected bricks.  The engine itself does not
        # know where they came from or how extensions are loaded.
        for item in [*active_tasks, *event_items]:
            for rule in rules:
                requests.extend(
                    self._run_rule(rule, item, clock, tz)
                )

        # Stable key is the delivery/deduplication boundary.
        unique: dict[str, NotificationRequest] = {}

        for request in requests:
            unique.setdefault(request.key, request)

        return sorted(
            unique.values(),
            key=lambda request: (
                self._instant(request.when, tz),
                request.key,
            ),
        )

    def due(
        self,
        requests: Iterable[NotificationRequest],
        *,
        now: datetime | None = None,
        delivered: Iterable[str] = (),
    ) -> list[NotificationRequest]:
        """Return undelivered requests whose trigger time has arrived."""

        clock = self._clock(now)
        tz = clock.tzinfo or timezone.utc
        cutoff = self._instant(clock, tz)
        delivered_keys = set(delivered)

        ordered = sorted(
            requests,
            key=lambda request: (
                self._instant(request.when, tz),
                request.key,
            ),
        )

        return [
            request
            for request in ordered
            if request.key not in delivered_keys
            and self._instant(request.when, tz) <= cutoff
        ]

    def next_due(
        self,
        requests: Iterable[NotificationRequest],
        *,
        now: datetime | None = None,
        delivered: Iterable[str] = (),
    ) -> datetime | None:
        """Return earliest undelivered trigger.

        An overdue trigger is intentionally returned as-is.  ReminderService can
        therefore wake immediately instead of accidentally sleeping past it.
        """

        clock = self._clock(now)
        tz = clock.tzinfo or timezone.utc
        delivered_keys = set(delivered)

        pending = [
            request
            for request in requests
            if request.key not in delivered_keys
        ]

        if not pending:
            return None

        earliest = min(
            pending,
            key=lambda request: self._instant(request.when, tz),
        )

        return earliest.when

    # ------------------------------------------------------------------
    # Explicit Reminder
    # ------------------------------------------------------------------

    def _from_reminder(
        self,
        reminder: Reminder,
        tz: Any,
    ) -> NotificationRequest | None:
        if not isinstance(reminder, Reminder):
            return None

        metadata = dict(reminder.metadata or {})

        if metadata.get("cancelled") is True:
            return None

        when = self._datetime(reminder.when, tz)

        # Date-only Reminder is not silently turned into midnight.
        if when is None:
            return None

        title = str(reminder.title or "").strip() or "Reminder"
        reminder_id = str(reminder.id or "").strip()
        token = reminder_id or title

        source = (
            "snooze"
            if metadata.get("snoozed")
            else "reminder"
        )

        key = (
            str(metadata.get("key") or "").strip()
            or self._key(source, token, when)
        )

        return NotificationRequest(
            key=key,
            when=when,
            title=title,
            body=str(metadata.get("body") or ""),
            actions=self._actions(metadata.get("actions")),
            source=source,
            object_id=reminder_id or None,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Task / Event
    # ------------------------------------------------------------------

    def _from_item(
        self,
        item: Task | Event,
        *,
        kind: str,
        tz: Any,
    ) -> list[NotificationRequest]:
        requests = self._valarm_requests(
            item,
            kind=kind,
            tz=tz,
        )

        if kind == "task":
            when = self._datetime(item.due, tz)
            source = "task_due"
            body = "Task due"
        else:
            when = self._datetime(item.start, tz)
            source = "event_start"
            body = (
                str(item.location or "").strip()
                or "Event starting"
            )

        # If an explicit VALARM is already scheduled for exactly the same
        # instant, do not generate a duplicate synthetic notification.
        if (
            when is not None
            and not self._has_same_time(requests, when, tz)
        ):
            object_id = str(item.id or "").strip()
            title = (
                str(item.summary or "").strip()
                or kind.title()
            )

            requests.append(
                NotificationRequest(
                    key=self._key(
                        source,
                        object_id or title,
                        when,
                    ),
                    when=when,
                    title=title,
                    body=body,
                    source=source,
                    object_id=object_id or None,
                    metadata={
                        "kind": kind,
                        "reason": source,
                    },
                )
            )

        return requests

    # ------------------------------------------------------------------
    # User reminder rules
    # ------------------------------------------------------------------

    def _run_rule(
        self,
        rule: Any,
        item: Task | Event,
        clock: datetime,
        tz: Any,
    ) -> list[NotificationRequest]:
        function = (
            rule
            if callable(rule)
            else getattr(rule, "evaluate", None)
        )

        if not callable(function):
            raise TypeError(
                "Reminder rule must be callable or provide evaluate()"
            )

        produced = function(item, clock)

        if produced is None:
            return []

        if isinstance(produced, NotificationRequest):
            values = [produced]
        else:
            try:
                values = list(produced)
            except TypeError as exc:
                raise TypeError(
                    "Reminder rule must return NotificationRequest, "
                    "an iterable of NotificationRequest, or None"
                ) from exc

        rule_name = getattr(
            function,
            "__name__",
            rule.__class__.__name__,
        )

        kind = (
            "task"
            if isinstance(item, Task)
            else "event"
        )

        object_id = str(item.id or "").strip()
        token = (
            object_id
            or str(item.summary or "").strip()
            or kind
        )

        result: list[NotificationRequest] = []

        for index, request in enumerate(values):
            if not isinstance(request, NotificationRequest):
                raise TypeError(
                    "Reminder rule iterable must contain "
                    "NotificationRequest objects"
                )

            when = self._datetime(request.when, tz)

            if when is None:
                continue

            metadata = dict(request.metadata)
            metadata.setdefault("kind", kind)
            metadata.setdefault("rule", rule_name)

            result.append(
                replace(
                    request,
                    key=(
                        request.key.strip()
                        or self._key(
                            f"rule:{rule_name}:{index}",
                            token,
                            when,
                        )
                    ),
                    when=when,
                    source=request.source or "rule",
                    object_id=(
                        request.object_id
                        or object_id
                        or None
                    ),
                    metadata=metadata,
                )
            )

        return result

    # ------------------------------------------------------------------
    # VALARM
    # ------------------------------------------------------------------

    def _valarm_requests(
        self,
        item: Task | Event,
        *,
        kind: str,
        tz: Any,
    ) -> list[NotificationRequest]:
        alarms = self._alarm_components(
            getattr(item, "raw", None)
        )

        object_id = str(item.id or "").strip()
        title = (
            str(item.summary or "").strip()
            or kind.title()
        )
        token = object_id or title

        requests: list[NotificationRequest] = []

        for alarm_index, alarm in enumerate(alarms):
            action = self._text(
                self._decode(
                    self._property(alarm, "ACTION")
                )
            )

            # NotificationAdapter represents display notifications.
            # AUDIO/EMAIL must not be silently reinterpreted.
            if action and action.upper() != "DISPLAY":
                continue

            trigger_property = self._property(
                alarm,
                "TRIGGER",
            )
            trigger = self._decode(trigger_property)

            related = self._related(
                trigger_property,
                alarm,
            )

            first = self._resolve_trigger(
                item,
                trigger,
                related,
                tz,
            )

            if first is None:
                continue

            description = self._text(
                self._decode(
                    self._property(
                        alarm,
                        "DESCRIPTION",
                    )
                )
            )

            repeat = self._repeat_count(alarm)

            duration = self._decode(
                self._property(
                    alarm,
                    "DURATION",
                )
            )

            times = [first]

            if repeat > 0 and isinstance(
                duration,
                timedelta,
            ):
                times.extend(
                    first + duration * index
                    for index in range(
                        1,
                        repeat + 1,
                    )
                )

            for repeat_index, when in enumerate(times):
                requests.append(
                    NotificationRequest(
                        key=self._key(
                            "valarm",
                            token,
                            when,
                            suffix=(
                                f"{alarm_index}:"
                                f"{repeat_index}"
                            ),
                        ),
                        when=when,
                        title=title,
                        body=description,
                        source="valarm",
                        object_id=object_id or None,
                        metadata={
                            "kind": kind,
                            "reason": "valarm",
                            "alarm_index": alarm_index,
                            "repeat_index": repeat_index,
                        },
                    )
                )

        return requests

    def _resolve_trigger(
        self,
        item: Task | Event,
        trigger: Any,
        related: str,
        tz: Any,
    ) -> datetime | None:
        # Absolute VALARM datetime.
        if isinstance(trigger, datetime):
            return self._datetime(trigger, tz)

        # An absolute DATE is not secretly DATE-TIME 00:00.
        if isinstance(trigger, date):
            return None

        # Relative VALARM.
        if not isinstance(trigger, timedelta):
            return None

        if related == "END":
            basis = (
                item.end
                if isinstance(item, Event)
                else item.due
            )
        else:
            basis = item.start

        basis_datetime = self._datetime(
            basis,
            tz,
        )

        # This also rejects a date-only DTSTART/DUE.
        if basis_datetime is None:
            return None

        return basis_datetime + trigger

    @classmethod
    def _alarm_components(
        cls,
        raw: Any,
    ) -> list[Any]:
        if raw is None:
            return []

        # Lightweight normalized representation used easily by adapters/tests.
        if isinstance(raw, Mapping):
            for key in (
                "alarms",
                "valarms",
                "VALARM",
            ):
                if key not in raw:
                    continue

                value = raw[key]

                if value is None:
                    return []

                if isinstance(value, Mapping):
                    return [value]

                if isinstance(value, (str, bytes)):
                    return []

                try:
                    return list(value)
                except TypeError:
                    return [value]

            # A single alarm can itself be supplied as a mapping.
            if (
                "TRIGGER" in raw
                or "trigger" in raw
            ):
                return [raw]

        # Compatible with iCalendar-like objects without importing the library.
        walk = getattr(raw, "walk", None)

        if callable(walk):
            try:
                return list(walk("VALARM"))
            except TypeError:
                return [
                    component
                    for component in walk()
                    if str(
                        getattr(
                            component,
                            "name",
                            "",
                        )
                    ).upper()
                    == "VALARM"
                ]

        subcomponents = (
            getattr(
                raw,
                "subcomponents",
                None,
            )
            or ()
        )

        return [
            component
            for component in subcomponents
            if str(
                getattr(
                    component,
                    "name",
                    "",
                )
            ).upper()
            == "VALARM"
        ]

    @staticmethod
    def _property(
        component: Any,
        name: str,
    ) -> Any:
        if isinstance(component, Mapping):
            for key in (
                name,
                name.upper(),
                name.lower(),
            ):
                if key in component:
                    return component[key]

            return None

        getter = getattr(
            component,
            "get",
            None,
        )

        if callable(getter):
            for key in (
                name,
                name.upper(),
                name.lower(),
            ):
                try:
                    value = getter(key)
                except (KeyError, TypeError):
                    continue

                if value is not None:
                    return value

        return None

    @staticmethod
    def _decode(value: Any) -> Any:
        if value is None:
            return None

        decoded = getattr(
            value,
            "decoded",
            None,
        )

        if callable(decoded):
            try:
                value = decoded()
            except (TypeError, ValueError):
                pass

        dt_value = getattr(
            value,
            "dt",
            None,
        )

        if dt_value is not None:
            value = dt_value

        if isinstance(value, bytes):
            return value.decode(
                errors="replace"
            )

        return value

    @classmethod
    def _related(
        cls,
        trigger_property: Any,
        alarm: Any,
    ) -> str:
        related = cls._property(
            alarm,
            "RELATED",
        )

        # icalendar commonly stores RELATED in TRIGGER params.
        if related is None:
            params = getattr(
                trigger_property,
                "params",
                None,
            )

            if isinstance(params, Mapping):
                related = (
                    params.get("RELATED")
                    or params.get("related")
                )

        text = cls._text(
            cls._decode(related)
        ).upper()

        return (
            "END"
            if text == "END"
            else "START"
        )

    @classmethod
    def _repeat_count(
        cls,
        alarm: Any,
    ) -> int:
        value = cls._decode(
            cls._property(
                alarm,
                "REPEAT",
            )
        )

        try:
            return max(
                0,
                int(value or 0),
            )
        except (TypeError, ValueError):
            return 0

    # ------------------------------------------------------------------
    # Temporal / identity helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _active_task(task: Any) -> bool:
        if not isinstance(task, Task):
            return False

        status = str(
            task.status or ""
        ).upper()

        return (
            not task.completed
            and status
            not in {
                "COMPLETED",
                "CANCELLED",
            }
        )

    @staticmethod
    def _clock(
        now: datetime | None,
    ) -> datetime:
        if now is None:
            return datetime.now().astimezone()

        if not isinstance(now, datetime):
            raise TypeError(
                "now must be datetime or None"
            )

        # A naive test/injected clock is interpreted deterministically as UTC.
        return (
            now
            if now.tzinfo is not None
            else now.replace(
                tzinfo=timezone.utc
            )
        )

    @staticmethod
    def _datetime(
        value: Any,
        tz: Any,
    ) -> datetime | None:
        # datetime is deliberately checked directly:
        # date-only values return None.
        if not isinstance(value, datetime):
            return None

        if value.tzinfo is None:
            return value.replace(
                tzinfo=tz or timezone.utc
            )

        return value

    @staticmethod
    def _instant(
        value: datetime,
        tz: Any,
    ) -> datetime:
        if value.tzinfo is None:
            value = value.replace(
                tzinfo=tz or timezone.utc
            )

        return value.astimezone(
            timezone.utc
        )

    @classmethod
    def _has_same_time(
        cls,
        requests: Iterable[NotificationRequest],
        when: datetime,
        tz: Any,
    ) -> bool:
        instant = cls._instant(
            when,
            tz,
        )

        return any(
            cls._instant(
                request.when,
                tz,
            )
            == instant
            for request in requests
        )

    @staticmethod
    def _key(
        source: str,
        token: str,
        when: datetime,
        *,
        suffix: str = "",
    ) -> str:
        parts = [
            source,
            token or "-",
            when.isoformat(),
        ]

        if suffix:
            parts.append(suffix)

        return ":".join(parts)

    @staticmethod
    def _text(value: Any) -> str:
        return (
            ""
            if value is None
            else str(value).strip()
        )

    @staticmethod
    def _actions(
        value: Any,
    ) -> tuple[str, ...]:
        if value is None:
            return ()

        if isinstance(value, str):
            return (value,)

        try:
            return tuple(
                str(item)
                for item in value
            )
        except TypeError:
            return (str(value),)
