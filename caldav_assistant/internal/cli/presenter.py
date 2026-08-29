"""Human-facing CLI presentation for public domain objects.

The presenter deliberately hides implementation details such as raw iCalendar,
CalDAV hrefs, Python reprs and service bindings. Debug commands may expose those
details explicitly; normal commands must not.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

from ...api.v1.models import Agenda, AgendaItem, Event, Task


def _when(value: date | datetime | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return value.strftime("%Y-%m-%d")


def _task_line(task: Task, *, index: int | None = None) -> str:
    prefix = f"{index:>3}. " if index is not None else ""
    marker = "OVERDUE" if task.overdue else task.status.replace("-", " ")
    due = _when(task.due)
    suffix = ""
    if due:
        suffix += f"  ·  due {due}"
    if marker and marker not in {"NEEDS ACTION", ""}:
        suffix += f"  ·  {marker.lower()}"
    return f"{prefix}{task.summary or '(untitled task)'}{suffix}"


def _event_line(event: Event, *, index: int | None = None) -> str:
    prefix = f"{index:>3}. " if index is not None else ""
    start = _when(event.start)
    suffix = f"  ·  {start}" if start else ""
    if event.location:
        suffix += f"  ·  {event.location}"
    return f"{prefix}{event.summary or '(untitled event)'}{suffix}"


def render_task(task: Task) -> list[str]:
    lines = [task.summary or "(untitled task)"]
    if task.start is not None:
        # Avoid overloading the human command "start" (begin working now) with
        # CalDAV DTSTART (the planned/scheduled start field).
        lines.append(f"Planned start: {_when(task.start)}")
    if task.due is not None:
        lines.append(f"Due: {_when(task.due)}")
    lines.append(f"Status: {'completed' if task.completed else task.status.lower()}")
    if task.priority is not None:
        lines.append(f"Priority: {task.priority}")
    if task.categories:
        lines.append("Categories: " + ", ".join(task.categories))
    if task.description:
        lines.extend(["", task.description])
    return lines


def render_event(event: Event) -> list[str]:
    lines = [event.summary or "(untitled event)"]
    if event.start is not None:
        lines.append(f"Starts: {_when(event.start)}")
    if event.end is not None:
        lines.append(f"Ends: {_when(event.end)}")
    if event.location:
        lines.append(f"Location: {event.location}")
    if event.categories:
        lines.append("Categories: " + ", ".join(event.categories))
    if event.description:
        lines.extend(["", event.description])
    return lines


def render_agenda_item(item: AgendaItem) -> list[str]:
    value = item.value
    if isinstance(value, Task):
        line = _task_line(value)
    elif isinstance(value, Event):
        line = _event_line(value)
    else:
        label = getattr(value, "summary", None) or getattr(value, "title", None) or "(item)"
        line = str(label)
    return ["Next", f"  {line}"]


def render_agenda(agenda: Agenda) -> list[str]:
    if not agenda.items:
        return ["Nothing scheduled."]

    lines = [f"Agenda · {len(agenda.items)} item{'s' if len(agenda.items) != 1 else ''}", ""]
    for index, item in enumerate(agenda.items, start=1):
        value = item.value
        if isinstance(value, Task):
            lines.append(_task_line(value, index=index))
        elif isinstance(value, Event):
            lines.append(_event_line(value, index=index))
        else:
            label = getattr(value, "summary", None) or getattr(value, "title", None)
            lines.append(f"{index:>3}. {label or '(item)'}")
    return lines


def render_lines(result: Any) -> list[str] | None:
    """Return safe human-readable lines, or ``None`` for unknown result types."""
    if isinstance(result, Agenda):
        return render_agenda(result)
    if isinstance(result, AgendaItem):
        return render_agenda_item(result)
    if isinstance(result, Task):
        return render_task(result)
    if isinstance(result, Event):
        return render_event(result)
    return None


def emit_lines(app: Any, lines: Iterable[str], *, paginate: bool = False, page_size: int = 10) -> None:
    materialized = list(lines)
    if not paginate or len(materialized) <= page_size:
        for line in materialized:
            app.ctx.ui.show(line)
        return

    position = 0
    total = len(materialized)
    while position < total:
        end = min(position + page_size, total)
        for line in materialized[position:end]:
            app.ctx.ui.show(line)
        position = end
        if position >= total:
            break
        try:
            answer = app.io.read(
                f"-- {position}/{total} -- [Enter] more, q stop: "
            ).strip().casefold()
        except (EOFError, KeyboardInterrupt):
            break
        if answer in {"q", "quit", "stop", "0"}:
            break


__all__ = [
    "render_lines",
    "render_agenda",
    "render_agenda_item",
    "render_task",
    "render_event",
    "emit_lines",
]
