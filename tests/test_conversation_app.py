from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from caldav_assistant.api import AgendaItem, Event, Task
from caldav_assistant.api.v1.errors import ValidationError
from caldav_assistant.internal.cli import conversation_app
from caldav_assistant.internal.cli.monitor_app import MonitorTarget
from caldav_assistant.internal.settings.keys import AGENDA_UPCOMING_HOURS
from caldav_assistant.internal.settings.schema import DEFAULT_SETTINGS_SCHEMA


def test_upcoming_setting_defaults_to_24h_and_accepts_user_window():
    spec = DEFAULT_SETTINGS_SCHEMA.get(AGENDA_UPCOMING_HOURS)

    assert spec.default_value() == 24
    assert spec.normalize("36") == 36
    assert spec.normalize(168) == 168

    with pytest.raises(ValidationError):
        spec.normalize(0)
    with pytest.raises(ValidationError):
        spec.normalize(745)


def test_upcoming_filter_excludes_overdue_and_outside_window():
    now = datetime.now().astimezone()
    end = now + timedelta(hours=24)
    task = Task(id="t1", summary="Report")

    inside = AgendaItem(task, when=now + timedelta(hours=2), kind="task")
    overdue = AgendaItem(task, when=now - timedelta(minutes=1), kind="task")
    later = AgendaItem(task, when=now + timedelta(hours=25), kind="task")

    assert conversation_app._item_in_window(inside, now, end) is True
    assert conversation_app._item_in_window(overdue, now, end) is False
    assert conversation_app._item_in_window(later, now, end) is False


def test_upcoming_text_distinguishes_tasks_and_events():
    now = datetime.now().astimezone()
    task = Task(id="t1", summary="English writing", due=now + timedelta(hours=1))
    event = Event(id="e1", summary="English class", start=now + timedelta(hours=2))
    snapshot = conversation_app.StartupSnapshot(
        upcoming=(
            AgendaItem(task, when=task.due, kind="task"),
            AgendaItem(event, when=event.start, kind="event"),
        ),
        window_hours=24,
    )

    text = conversation_app._snapshot_text(snapshot)

    assert "Upcoming · next 24h" in text
    assert "□ English writing" in text
    assert "◷ English class" in text


def test_waiting_line_shows_start_end_remaining_without_claiming_task_percent():
    now = datetime.now(timezone.utc).astimezone()
    task = Task(id="t1", summary="Anki", status="IN-PROCESS")
    target = MonitorTarget("task", "t1", "Anki", task, True)
    status = {
        "state": "scheduled",
        "deadline": (now + timedelta(minutes=30)).isoformat(),
        "remaining_seconds": 1800,
        "duration_seconds": 1800,
    }

    text = conversation_app._live_line(target, now, status)

    assert "Anki" in text
    assert "start" in text
    assert "end" in text
    assert "remaining 30m" in text
    assert "%" not in text


def test_work_plan_is_explicitly_separate_from_due_fields():
    task = Task(id="t1", summary="Report")

    text = conversation_app._period_plan_text(task, 25 * 60)

    assert "Task: Report" in text
    assert "Start:" in text
    assert "Planned end:" in text
    assert "Duration: 25m" in text


def test_configure_upcoming_persists_only_assistant_setting():
    writes = []

    class UI:
        def choose(self, title, items, **kwargs):
            return "3 days (72h)"

        def show(self, value):
            return None

    settings = SimpleNamespace(
        get=lambda key, default=None: 24,
        set=lambda key, value: writes.append((key, value)) or value,
    )
    app = SimpleNamespace(ctx=SimpleNamespace(ui=UI(), settings=settings))

    assert conversation_app._configure_upcoming(app) == 72
    assert writes == [(AGENDA_UPCOMING_HOURS, 72)]
