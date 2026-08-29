from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from caldav_assistant.api import Activity, Task
from caldav_assistant.internal.cli.actions import BuiltinActions
from caldav_assistant.internal.cli.presenter import render_lines


def _current_context(task: Task, activities: list[Activity]):
    return SimpleNamespace(
        session=SimpleNamespace(
            current_task=lambda: task,
            paused_tasks=lambda: [],
        ),
        activity=SimpleNamespace(for_task=lambda value: list(activities)),
    )


def test_current_separates_actual_work_start_from_old_planned_start():
    task = Task(
        id="anki",
        summary="Anki",
        start=datetime(2026, 5, 18, 17, 0),
        due=datetime(2026, 5, 18, 17, 0),
        status="IN-PROCESS",
        categories=["Projects"],
    )
    actual_start = datetime(2026, 8, 29, 14, 31)
    ctx = _current_context(
        task,
        [Activity(timestamp=actual_start, action="task_started", object_id="anki")],
    )

    result = BuiltinActions(ctx).current()
    lines = render_lines(result)

    assert result is not task
    assert lines is not None
    assert lines[0] == "Anki"
    assert "Working since: 2026-08-29 14:31" in lines
    assert "Planned start: 2026-05-18 17:00" in lines
    assert "Due: 2026-05-18 17:00" in lines
    assert "Status: in-process" in lines

    # The authoritative Task object remains untouched by CLI presentation state.
    assert not hasattr(task, "_assistant_working_since")


def test_current_uses_latest_resume_as_current_work_segment_start():
    task = Task(id="anki", summary="Anki", status="IN-PROCESS")
    ctx = _current_context(
        task,
        [
            Activity(
                timestamp=datetime(2026, 8, 29, 9, 0),
                action="task_started",
                object_id="anki",
            ),
            Activity(
                timestamp=datetime(2026, 8, 29, 10, 0),
                action="task_paused",
                object_id="anki",
            ),
            Activity(
                timestamp=datetime(2026, 8, 29, 11, 15),
                action="task_resumed",
                object_id="anki",
            ),
        ],
    )

    lines = render_lines(BuiltinActions(ctx).current())

    assert lines is not None
    assert "Working since: 2026-08-29 11:15" in lines
    assert "Working since: 2026-08-29 09:00" not in lines
