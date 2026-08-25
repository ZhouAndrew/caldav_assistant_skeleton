"""Deterministic next-action selection over an already-built Agenda.

MODULE CONTRACT
- Imports/calls: public Agenda/AgendaItem/Task/Event models + stdlib only.
- Consumes: Agenda + explicit current time + current-task/skip state.
- Provides: NextEngine.
- Must not:
  - query TaskService or EventService;
  - rebuild Agenda;
  - access CalDAV, XML, HTTP, SQLite, or network state;
  - modify Task/Event objects;
  - print CLI output;
  - send notifications.

AgendaEngine answers:
    "What items exist in the relevant agenda?"

NextEngine answers:
    "Given that agenda, what is the most reasonable next item?"

The policy is intentionally explicit and deterministic rather than a hidden
numeric score.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Iterable

from ...api import Agenda, AgendaItem, Event, Task
from ...api.v1.errors import ValidationError


class NextEngine:
    """Choose one reasonable next AgendaItem without side effects."""

    DEFAULT_EVENT_HORIZON = timedelta(hours=2)
    DEFAULT_DUE_HORIZON = timedelta(days=1)

    def __init__(
        self,
        *,
        event_horizon: timedelta = DEFAULT_EVENT_HORIZON,
        due_horizon: timedelta = DEFAULT_DUE_HORIZON,
    ) -> None:
        if event_horizon < timedelta(0):
            raise ValueError("event_horizon must not be negative")
        if due_horizon < timedelta(0):
            raise ValueError("due_horizon must not be negative")

        self.event_horizon = event_horizon
        self.due_horizon = due_horizon

    # ------------------------------------------------------------------
    # Public decision entry point
    # ------------------------------------------------------------------
    def choose(
        self,
        agenda: Agenda,
        *,
        now: datetime,
        current_task_uid: str | None = None,
        skipped_uids: Iterable[str] = (),
        kind: str | None = None,
    ) -> AgendaItem | None:
        """Return the best AgendaItem, or None when nothing is eligible.

        ``now`` is deliberately supplied by the caller.  The engine never calls
        datetime.now(), which keeps decisions reproducible and tests deterministic.

        ``kind`` may be:
            None      -> Task or Event
            "task"    -> Task only
            "event"   -> Event only
        """

        if not isinstance(agenda, Agenda):
            raise TypeError("NextEngine requires an Agenda")
        if not isinstance(now, datetime):
            raise TypeError("now must be a datetime")
        if kind not in (None, "task", "event"):
            raise ValidationError("kind must be 'task', 'event', or None")

        if isinstance(skipped_uids, str):
            skipped = {skipped_uids}
        else:
            skipped = {
                str(uid)
                for uid in skipped_uids
                if uid is not None and str(uid)
            }

        current_uid = (
            str(current_task_uid)
            if current_task_uid is not None
            else None
        )

        candidates: list[AgendaItem] = []

        for item in agenda.items:
            item_kind = self._kind(item)

            if item_kind is None:
                continue
            if kind is not None and item_kind != kind:
                continue

            uid = self._uid(item)
            if uid is not None and uid in skipped:
                continue

            if not self._eligible(item, now):
                continue

            candidates.append(item)

        if not candidates:
            return None

        return min(
            candidates,
            key=lambda item: self._rank(
                item,
                now=now,
                current_task_uid=current_uid,
            ),
        )

    # ------------------------------------------------------------------
    # Item identity / classification
    # ------------------------------------------------------------------
    @staticmethod
    def _kind(item: AgendaItem) -> str | None:
        if isinstance(item.value, Task):
            return "task"
        if isinstance(item.value, Event):
            return "event"
        return None

    @staticmethod
    def _uid(item: AgendaItem) -> str | None:
        value = item.value
        uid = getattr(value, "id", None)

        if uid is None:
            return None

        text = str(uid)
        return text if text else None

    @staticmethod
    def _stable_id(item: AgendaItem) -> str:
        uid = NextEngine._uid(item)
        if uid is not None:
            return uid

        summary = getattr(item.value, "summary", "")
        return str(summary)

    # ------------------------------------------------------------------
    # Time normalization
    # ------------------------------------------------------------------
    @staticmethod
    def _as_datetime(
        value: date | datetime | None,
        now: datetime,
    ) -> datetime | None:
        if value is None:
            return None

        if isinstance(value, datetime):
            # Keep comparisons deterministic when domain data mixes naive and
            # timezone-aware datetime objects.  A naive value is interpreted in
            # the caller's current timezone.
            if now.tzinfo is not None and value.tzinfo is None:
                return value.replace(tzinfo=now.tzinfo)

            if now.tzinfo is None and value.tzinfo is not None:
                return value.replace(tzinfo=None)

            if now.tzinfo is not None and value.tzinfo is not None:
                return value.astimezone(now.tzinfo)

            return value

        return datetime.combine(
            value,
            time.min,
            tzinfo=now.tzinfo,
        )

    @staticmethod
    def _far_future(now: datetime) -> datetime:
        return datetime.max.replace(tzinfo=now.tzinfo)

    @classmethod
    def _time_key(
        cls,
        value: date | datetime | None,
        now: datetime,
    ) -> datetime:
        normalized = cls._as_datetime(value, now)
        return normalized if normalized is not None else cls._far_future(now)

    # ------------------------------------------------------------------
    # Task policy bricks
    # ------------------------------------------------------------------
    @staticmethod
    def _priority(task: Task) -> int:
        """RFC-style priority ordering: 1 is highest; absent/0 sorts last."""
        value = task.priority

        if isinstance(value, int) and 1 <= value <= 9:
            return value

        return 10

    @classmethod
    def _task_overdue(cls, task: Task, now: datetime) -> bool:
        if task.overdue:
            return True

        due = task.due
        if due is None:
            return False

        # Date-only due remains date-only semantically.  "Due today" is not
        # overdue merely because midnight has passed.
        if isinstance(due, date) and not isinstance(due, datetime):
            return due < now.date()

        normalized = cls._as_datetime(due, now)
        return normalized is not None and normalized < now

    def _task_due_soon(self, task: Task, now: datetime) -> bool:
        due = task.due

        if due is None or self._task_overdue(task, now):
            return False

        if isinstance(due, date) and not isinstance(due, datetime):
            return (
                now.date()
                <= due
                <= (now + self.due_horizon).date()
            )

        normalized = self._as_datetime(due, now)
        if normalized is None:
            return False

        return now <= normalized <= now + self.due_horizon

    @classmethod
    def _task_available(cls, task: Task, now: datetime) -> bool:
        start = task.start

        if start is None:
            return True

        if isinstance(start, date) and not isinstance(start, datetime):
            return start <= now.date()

        normalized = cls._as_datetime(start, now)
        return normalized is not None and normalized <= now

    # ------------------------------------------------------------------
    # Event policy bricks
    # ------------------------------------------------------------------
    @classmethod
    def _event_start(
        cls,
        item: AgendaItem,
    ) -> date | datetime | None:
        event = item.value
        assert isinstance(event, Event)

        # Event.start is authoritative. AgendaItem.when is only a safe fallback
        # for an Agenda implementation that already normalized the event time.
        return event.start if event.start is not None else item.when

    @classmethod
    def _event_ongoing(cls, item: AgendaItem, now: datetime) -> bool:
        event = item.value
        assert isinstance(event, Event)

        start = cls._event_start(item)
        end = event.end

        if start is None:
            return False

        if (
            isinstance(start, date)
            and not isinstance(start, datetime)
            and (end is None or (
                isinstance(end, date)
                and not isinstance(end, datetime)
            ))
        ):
            if end is None:
                return start == now.date()

            # iCalendar all-day DTEND is normally exclusive.
            return start <= now.date() < end

        start_dt = cls._as_datetime(start, now)
        end_dt = cls._as_datetime(end, now)

        if start_dt is None or end_dt is None:
            return False

        return start_dt <= now < end_dt

    @classmethod
    def _event_past(cls, item: AgendaItem, now: datetime) -> bool:
        event = item.value
        assert isinstance(event, Event)

        start = cls._event_start(item)
        end = event.end

        if start is None:
            return False

        if isinstance(start, date) and not isinstance(start, datetime):
            if isinstance(end, date) and not isinstance(end, datetime):
                return now.date() >= end
            if end is None:
                return start < now.date()

        end_dt = cls._as_datetime(end, now)
        if end_dt is not None:
            return end_dt <= now

        start_dt = cls._as_datetime(start, now)
        return start_dt is not None and start_dt < now

    def _event_imminent(self, item: AgendaItem, now: datetime) -> bool:
        if self._event_ongoing(item, now):
            return False

        start = self._event_start(item)
        start_dt = self._as_datetime(start, now)

        if start_dt is None:
            return False

        return now <= start_dt <= now + self.event_horizon

    # ------------------------------------------------------------------
    # Eligibility and explicit ordering policy
    # ------------------------------------------------------------------
    def _eligible(self, item: AgendaItem, now: datetime) -> bool:
        value = item.value

        if isinstance(value, Task):
            if value.completed:
                return False
            if value.status in {"COMPLETED", "CANCELLED"}:
                return False
            return True

        if isinstance(value, Event):
            return not self._event_past(item, now)

        return False

    def _rank(
        self,
        item: AgendaItem,
        *,
        now: datetime,
        current_task_uid: str | None,
    ) -> tuple:
        """Return an explicit lexicographic policy rank.

        Lower tuple wins.

        Policy:
          0 current Task
          1 ongoing Event
          2 imminent Event
          3 overdue Task
          4 due-soon Task
          5 available ordinary Task
          6 future-start Task
          7 later Event

        There are no opaque accumulated "importance scores".
        """

        value = item.value
        stable_id = self._stable_id(item)

        if isinstance(value, Task):
            priority = self._priority(value)
            due_key = self._time_key(value.due, now)
            start_key = self._time_key(value.start, now)

            if (
                current_task_uid is not None
                and self._uid(item) == current_task_uid
            ):
                return (0, priority, due_key, stable_id)

            if self._task_overdue(value, now):
                # For overdue work, age of deadline matters first.
                return (3, due_key, priority, stable_id)

            if self._task_due_soon(value, now):
                # For near deadlines, deadline time matters before priority.
                return (4, due_key, priority, stable_id)

            if self._task_available(value, now):
                # Ordinary available work: explicit priority matters first.
                return (5, priority, due_key, stable_id)

            return (6, start_key, priority, due_key, stable_id)

        if isinstance(value, Event):
            start_key = self._time_key(self._event_start(item), now)

            if self._event_ongoing(item, now):
                return (1, start_key, stable_id)

            if self._event_imminent(item, now):
                return (2, start_key, stable_id)

            return (7, start_key, stable_id)

        return (99, stable_id)
