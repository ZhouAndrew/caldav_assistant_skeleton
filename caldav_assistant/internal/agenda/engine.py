"""Pure Agenda construction engine.

MODULE CONTRACT
- Imports/calls: public Task/Event/Agenda/AgendaItem models + stdlib only.
- Provides: AgendaEngine.
- Input: already-read Tasks, Events, time range, optional Assistant user state.
- Output: Agenda.
- Must not: query CalDAV, call TaskService/EventService, write SQLite, mutate
  Task/Event state, print CLI output, or make NextEngine recommendations.

AgendaEngine is a read-only projection layer.  It combines authoritative domain
objects into a deterministic agenda view; it never becomes a source of truth.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

from ...api import Agenda, AgendaItem, Event, Task
from ...api.v1.errors import ValidationError


class AgendaEngine:
    """Build deterministic Agenda views from Task/Event objects."""

    _INACTIVE_TASK_STATUSES = frozenset({"COMPLETED", "CANCELLED"})

    # Internal grouping order.
    #
    # The current public AgendaItem contract contains value/when/kind but no public
    # ``group`` field.  Therefore grouping is represented by stable contiguous order:
    #
    #   current -> overdue -> scheduled
    #
    # We deliberately do not expand the frozen public model from inside this module.
    _CURRENT = 0
    _OVERDUE = 1
    _SCHEDULED = 2

    def build(
        self,
        tasks: Sequence[Task],
        events: Sequence[Event],
        *,
        days: int = 1,
        now: datetime | None = None,
        user_state: Any = None,
    ) -> Agenda:
        """Merge Tasks and Events into an Agenda.

        ``days`` describes calendar days beginning with ``now.date()``.

        Active overdue Tasks and the current Task remain visible even when their
        date lies before the requested range.  Normal scheduled items must fall
        inside the range.

        Date-only values remain date-only.  They are never silently converted into
        midnight datetimes in the returned AgendaItem.
        """

        if isinstance(days, bool) or not isinstance(days, int) or days < 1:
            raise ValidationError("Agenda days must be a positive integer")

        if now is None:
            now = datetime.now().astimezone()
        elif not isinstance(now, datetime):
            raise ValidationError("Agenda now must be a datetime")

        start_day = now.date()
        end_day = start_day + timedelta(days=days)
        current_task_uid = self._current_task_uid(user_state)

        ranked: list[
            tuple[
                int,
                tuple[int, int, int, int],
                int,
                AgendaItem,
            ]
        ] = []

        sequence = 0

        # ------------------------------------------------------------------
        # Tasks
        # ------------------------------------------------------------------
        for task in tasks:
            if not isinstance(task, Task):
                raise TypeError("AgendaEngine tasks must contain Task objects")

            if self._task_is_inactive(task):
                continue

            when = task.due if task.due is not None else task.start

            is_current = (
                current_task_uid is not None
                and str(task.id or "") == current_task_uid
            )

            is_overdue = (
                task.due is not None
                and self._is_before(task.due, now)
            )

            in_range = (
                when is not None
                and self._day_in_range(
                    when,
                    start_day=start_day,
                    end_day=end_day,
                    now=now,
                )
            )

            # An undated task belongs to Agenda only when Assistant state says that
            # it is the task currently being worked on. General undated task
            # prioritisation belongs to NextEngine, not AgendaEngine.
            if not (is_current or is_overdue or in_range):
                continue

            if is_current:
                group = self._CURRENT
            elif is_overdue:
                group = self._OVERDUE
            else:
                group = self._SCHEDULED

            ranked.append(
                (
                    group,
                    self._when_sort_key(when, now),
                    sequence,
                    AgendaItem(
                        value=task,
                        when=when,
                        kind="task",
                    ),
                )
            )
            sequence += 1

        # ------------------------------------------------------------------
        # Events
        # ------------------------------------------------------------------
        for event in events:
            if not isinstance(event, Event):
                raise TypeError("AgendaEngine events must contain Event objects")

            if event.start is None:
                continue

            if not self._event_overlaps_range(
                event,
                start_day=start_day,
                end_day=end_day,
                now=now,
            ):
                continue

            ranked.append(
                (
                    self._SCHEDULED,
                    self._when_sort_key(event.start, now),
                    sequence,
                    AgendaItem(
                        value=event,
                        when=event.start,
                        kind="event",
                    ),
                )
            )
            sequence += 1

        ranked.sort(key=lambda row: (row[0], row[1], row[2]))

        return Agenda(items=[row[3] for row in ranked])

    # ------------------------------------------------------------------
    # Small reusable bricks
    # ------------------------------------------------------------------
    @classmethod
    def _task_is_inactive(cls, task: Task) -> bool:
        if task.completed:
            return True

        status = str(task.status or "").strip().upper()
        return status in cls._INACTIVE_TASK_STATUSES

    @staticmethod
    def _current_task_uid(user_state: Any) -> str | None:
        """Read current_task_uid without depending on a concrete repository."""

        if user_state is None:
            return None

        value: Any = None

        if isinstance(user_state, Mapping):
            value = user_state.get("current_task_uid")
        else:
            getter = getattr(user_state, "get", None)
            if callable(getter):
                try:
                    value = getter("current_task_uid", None)
                except TypeError:
                    value = getter("current_task_uid")
            else:
                value = getattr(user_state, "current_task_uid", None)

        if value is None:
            return None

        text = str(value).strip()
        return text or None

    @classmethod
    def _local_datetime(
        cls,
        value: datetime,
        now: datetime,
    ) -> datetime:
        """Place a datetime in the same comparison frame as ``now``.

        Aware datetimes are converted to ``now``'s timezone when possible.
        Naive datetimes retain wall-clock semantics instead of being guessed into
        UTC.
        """

        if value.tzinfo is not None and now.tzinfo is not None:
            return value.astimezone(now.tzinfo)

        if value.tzinfo is not None and now.tzinfo is None:
            return value.astimezone().replace(tzinfo=None)

        if value.tzinfo is None and now.tzinfo is not None:
            return value.replace(tzinfo=now.tzinfo)

        return value

    @classmethod
    def _date_of(
        cls,
        value: date | datetime,
        now: datetime,
    ) -> date:
        if isinstance(value, datetime):
            return cls._local_datetime(value, now).date()
        return value

    @classmethod
    def _is_before(
        cls,
        value: date | datetime,
        now: datetime,
    ) -> bool:
        # A date-only Due remains valid for the entire calendar date.
        # "today" is therefore not overdue merely because the clock passed 00:00.
        if not isinstance(value, datetime):
            return value < now.date()

        local_value = cls._local_datetime(value, now)

        if now.tzinfo is not None and local_value.tzinfo is None:
            local_value = local_value.replace(tzinfo=now.tzinfo)
        elif now.tzinfo is None and local_value.tzinfo is not None:
            local_value = local_value.replace(tzinfo=None)

        return local_value < now

    @classmethod
    def _day_in_range(
        cls,
        value: date | datetime,
        *,
        start_day: date,
        end_day: date,
        now: datetime,
    ) -> bool:
        day = cls._date_of(value, now)
        return start_day <= day < end_day

    @classmethod
    def _event_overlaps_range(
        cls,
        event: Event,
        *,
        start_day: date,
        end_day: date,
        now: datetime,
    ) -> bool:
        """Return True when an Event occupies at least one requested day."""

        if event.start is None:
            return False

        event_start_day = cls._date_of(event.start, now)

        if event.end is None:
            return start_day <= event_start_day < end_day

        event_end_day = cls._date_of(event.end, now)

        return (
            event_start_day < end_day
            and event_end_day >= start_day
        )

    @classmethod
    def _when_sort_key(
        cls,
        value: date | datetime | None,
        now: datetime,
    ) -> tuple[int, int, int, int]:
        """Create a comparable key without changing the returned temporal value.

        On the same calendar day:
        - date-only/all-day values sort first;
        - timed values sort by wall-clock time.

        ``None`` is used only for an undated current Task; its group rank already
        puts it before normal scheduled items.
        """

        if value is None:
            return (date.min.toordinal(), 0, 0, 0)

        if isinstance(value, datetime):
            local = cls._local_datetime(value, now)
            seconds = (
                local.hour * 3600
                + local.minute * 60
                + local.second
            )
            return (
                local.date().toordinal(),
                1,
                seconds,
                local.microsecond,
            )

        return (
            value.toordinal(),
            0,
            0,
            0,
        )
