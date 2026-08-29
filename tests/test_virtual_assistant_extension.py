from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from caldav_assistant.api import Task
from caldav_assistant.builtin_extensions.virtual_assistant import (
    ClassicAssistantPolicy,
    build_summary,
)


def test_high_priority_task_gets_explainable_early_nudges():
    now = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
    task = Task(
        id="report",
        summary="Finish report",
        due=now + timedelta(hours=26),
        priority=1,
    )

    requests = ClassicAssistantPolicy().evaluate(task, now)

    assert [item.metadata["trigger"] for item in requests] == ["24h", "2h", "30m"]
    assert all(item.source == "virtual_assistant" for item in requests)
    assert all(item.object_id == "report" for item in requests)
    assert all("score" in item.metadata for item in requests)
    assert all("reasons" in item.metadata for item in requests)
    assert requests[0].key.endswith(":24h")


def test_completed_task_never_gets_assistant_nudges():
    now = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
    task = Task(
        id="done",
        summary="Already done",
        due=now + timedelta(hours=1),
        priority=1,
        status="COMPLETED",
        completed=True,
    )

    assert ClassicAssistantPolicy().evaluate(task, now) is None


def test_progress_summary_uses_task_facts_and_session_work_time():
    now = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
    current = Task(
        id="current",
        summary="Prepare lesson",
        due=now + timedelta(hours=4),
        status="IN-PROCESS",
    )
    overdue = Task(
        id="late",
        summary="Mark papers",
        due=now - timedelta(hours=1),
    )
    completed = Task(
        id="complete",
        summary="Email parent",
        status="COMPLETED",
        completed=True,
        completed_at=now - timedelta(hours=1),
    )

    ctx = SimpleNamespace(
        tasks=SimpleNamespace(list=lambda: [current, overdue, completed]),
        session=SimpleNamespace(
            current_task=lambda: current,
            paused_tasks=lambda: [overdue],
            work_seconds=lambda task: 90 * 60,
        ),
    )

    text = build_summary(ctx, now=now)

    assert "Completed today: 1" in text
    assert "Active tasks: 2" in text
    assert "Overdue: 1" in text
    assert "Current: Prepare lesson" in text
    assert "Accumulated active time: 1h 30m" in text
    assert "Paused tasks: 1" in text
