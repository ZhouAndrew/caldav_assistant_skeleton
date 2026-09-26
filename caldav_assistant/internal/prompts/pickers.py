"""Reusable client-neutral picker state.

These controllers contain interaction state only. They do not read keys, write terminal
control sequences, mutate Tasks, or access CalDAV. Client adapters render the views and
translate raw input into abstract actions; PromptKit composes them with domain objects.
"""
from __future__ import annotations

from calendar import Calendar, month_name, monthrange
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterable, Sequence

from ..presentation import DatePickerView, ScrollableListView, TaskPickerView


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def task_matches_date(task: Any, selected: date) -> bool:
    """Presentation-only match: DTSTART or DUE falls on the selected date."""
    return any(
        _as_date(getattr(task, field_name, None)) == selected
        for field_name in ("start", "due")
    )


def _task_is_finished(task: Any) -> bool:
    if bool(getattr(task, "completed", False)):
        return True
    status = str(getattr(task, "status", "") or "").strip().upper()
    return status in {"COMPLETED", "CANCELLED"}


def task_is_overdue(task: Any, today: date) -> bool:
    """Return whether an unfinished Task belongs to today's overdue backlog."""
    if _task_is_finished(task):
        return False
    if bool(getattr(task, "overdue", False)):
        return True
    due = _as_date(getattr(task, "due", None))
    return due is not None and due < today


def task_matches_picker_date(task: Any, selected: date, today: date) -> bool:
    """Task Picker semantics: today includes overdue backlog; other dates stay exact."""
    if selected == today and task_is_overdue(task, today):
        return True
    return task_matches_date(task, selected)


@dataclass
class DateCursor:
    selected: date
    today: date

    def move_days(self, days: int) -> None:
        self.selected += timedelta(days=int(days))

    def move_weeks(self, weeks: int) -> None:
        self.move_days(int(weeks) * 7)

    def move_months(self, months: int) -> None:
        absolute = self.selected.year * 12 + (self.selected.month - 1) + int(months)
        year, month_index = divmod(absolute, 12)
        month = month_index + 1
        day = min(self.selected.day, monthrange(year, month)[1])
        self.selected = date(year, month, day)

    def reset_today(self) -> None:
        self.selected = self.today

    def view(
        self,
        title: str = "Choose date",
        *,
        marked_dates: Iterable[date] = (),
    ) -> DatePickerView:
        weeks = Calendar(firstweekday=0).monthdatescalendar(
            self.selected.year,
            self.selected.month,
        )
        return DatePickerView(
            title=title,
            selected=self.selected,
            today=self.today,
            month_label=f"{month_name[self.selected.month]} {self.selected.year}",
            weeks=tuple(tuple(day for day in week) for week in weeks),
            marked_dates=tuple(dict.fromkeys(marked_dates)),
        )


@dataclass
class ScrollCursor:
    items: list[Any] = field(default_factory=list)
    selected_index: int = 0
    offset: int = 0
    page_size: int = 8

    def _clamp(self) -> None:
        if not self.items:
            self.selected_index = 0
            self.offset = 0
            return
        self.selected_index = min(max(0, self.selected_index), len(self.items) - 1)
        if self.selected_index < self.offset:
            self.offset = self.selected_index
        if self.selected_index >= self.offset + self.page_size:
            self.offset = self.selected_index - self.page_size + 1
        max_offset = max(0, len(self.items) - self.page_size)
        self.offset = min(max(0, self.offset), max_offset)

    def replace(self, items: Iterable[Any], *, keep_index: bool = False) -> None:
        self.items = list(items)
        if not keep_index:
            self.selected_index = 0
            self.offset = 0
        self._clamp()

    def move(self, delta: int) -> None:
        if not self.items:
            return
        self.selected_index += int(delta)
        self._clamp()

    def page(self, delta: int) -> None:
        self.move(int(delta) * max(1, self.page_size))

    @property
    def selected(self) -> Any | None:
        if not self.items:
            return None
        self._clamp()
        return self.items[self.selected_index]

    def view(
        self,
        title: str,
        labels: Sequence[str],
    ) -> ScrollableListView:
        self._clamp()
        return ScrollableListView(
            title=title,
            labels=tuple(labels),
            selected_index=self.selected_index,
            offset=self.offset,
            page_size=self.page_size,
        )


class DatePickerController:
    """Standalone date-picker state reusable by any future UI workflow."""

    def __init__(self, selected: date, *, today: date | None = None) -> None:
        self.cursor = DateCursor(selected=selected, today=today or selected)

    @property
    def selected(self) -> date:
        return self.cursor.selected

    def apply(self, action: str) -> None:
        if action == "left":
            self.cursor.move_days(-1)
        elif action == "right":
            self.cursor.move_days(1)
        elif action == "week_up":
            self.cursor.move_weeks(-1)
        elif action == "week_down":
            self.cursor.move_weeks(1)
        elif action == "page_up":
            self.cursor.move_months(-1)
        elif action == "page_down":
            self.cursor.move_months(1)
        elif action == "today":
            self.cursor.reset_today()

    def view(
        self,
        title: str = "Choose date",
        *,
        marked_dates: Iterable[date] = (),
    ) -> DatePickerView:
        return self.cursor.view(title, marked_dates=marked_dates)


class TaskPickerController:
    """Composite date-filter + scrollable Task selection state."""

    def __init__(
        self,
        tasks: Iterable[Any],
        *,
        labeler: Callable[[Any], str],
        selected_date: date,
        today: date,
        title: str = "Choose a Task to work on",
        page_size: int = 8,
    ) -> None:
        self.all_tasks = list(tasks)
        self.labeler = labeler
        self.title = str(title)
        self.date = DateCursor(selected=selected_date, today=today)
        self.tasks = ScrollCursor(page_size=max(1, int(page_size)))
        self._filtered: list[Any] = []
        self._labels: list[str] = []
        self.refresh()

    def refresh(self) -> None:
        selected = self.date.selected
        today = self.date.today
        matched = [
            task
            for task in self.all_tasks
            if task_matches_picker_date(task, selected, today)
        ]
        if selected == today:
            overdue = [task for task in matched if task_is_overdue(task, today)]
            overdue_ids = {id(task) for task in overdue}
            due_today = [task for task in matched if id(task) not in overdue_ids]
            matched = overdue + due_today
        self._filtered = matched
        self._labels = [
            (
                f"OVERDUE · {self.labeler(task)}"
                if selected == today and task_is_overdue(task, today)
                else self.labeler(task)
            )
            for task in self._filtered
        ]
        self.tasks.replace(self._filtered)

    def set_date(self, value: date) -> None:
        self.date.selected = value
        self.refresh()

    def move_date_days(self, days: int) -> None:
        self.date.move_days(days)
        self.refresh()

    def move_date_months(self, months: int) -> None:
        self.date.move_months(months)
        self.refresh()

    def reset_today(self) -> None:
        self.date.reset_today()
        self.refresh()

    def move_task(self, delta: int) -> None:
        self.tasks.move(delta)

    def page_tasks(self, delta: int) -> None:
        self.tasks.page(delta)

    @property
    def selected_task(self) -> Any | None:
        return self.tasks.selected

    def search(self, query: str) -> None:
        needle = str(query).strip().casefold()
        if not needle:
            self.refresh()
            return
        selected = self.date.selected
        today = self.date.today
        matched = [
            task
            for task in self.all_tasks
            if task_matches_picker_date(task, selected, today)
            and needle in self.labeler(task).casefold()
        ]
        if selected == today:
            overdue = [task for task in matched if task_is_overdue(task, today)]
            overdue_ids = {id(task) for task in overdue}
            due_today = [task for task in matched if id(task) not in overdue_ids]
            matched = overdue + due_today
        self._filtered = matched
        self._labels = [
            (
                f"OVERDUE · {self.labeler(task)}"
                if selected == today and task_is_overdue(task, today)
                else self.labeler(task)
            )
            for task in self._filtered
        ]
        self.tasks.replace(self._filtered)

    def marked_dates(self) -> tuple[date, ...]:
        values: list[date] = []
        for task in self.all_tasks:
            for field_name in ("start", "due"):
                value = _as_date(getattr(task, field_name, None))
                if value is not None:
                    values.append(value)
        return tuple(dict.fromkeys(values))

    def view(self) -> TaskPickerView:
        footer = (
            "←/→ date · PgUp/PgDn month · ↑/↓ task · Enter choose · "
            "i input date · t today · / search · q cancel"
        )
        overdue_count = 0
        if self.date.selected == self.date.today:
            overdue_count = sum(
                1 for task in self._filtered if task_is_overdue(task, self.date.today)
            )
        count_text = f"{len(self._filtered)}"
        if overdue_count:
            count_text += f" · {overdue_count} overdue"
        return TaskPickerView(
            title=self.title,
            calendar=self.date.view(
                "Calendar",
                marked_dates=self.marked_dates(),
            ),
            tasks=self.tasks.view(
                f"Tasks · {self.date.selected.isoformat()} · {count_text}",
                self._labels,
            ),
            footer=footer,
        )


__all__ = [
    "DateCursor",
    "DatePickerController",
    "ScrollCursor",
    "TaskPickerController",
    "task_matches_date",
    "task_matches_picker_date",
    "task_is_overdue",
]
