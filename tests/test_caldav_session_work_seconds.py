from __future__ import annotations

from datetime import datetime, timedelta, timezone

from caldav_assistant.api import Event, Task
from caldav_assistant.internal.session.caldav import CalDAVSessionService


class FakeWorkLog:
    def __init__(self, now, segments):
        self._now = now
        self._segments = segments

    def now(self):
        return self._now

    def segments_for(self, task):
        return list(self._segments)

    def current_task_id(self):
        return "task-1"



def test_work_seconds_includes_closed_and_open_caldav_segments():
    now = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
    task = Task(id="task-1", summary="Prepare lesson")
    closed = Event(
        id="seg-1",
        start=now - timedelta(hours=2),
        end=now - timedelta(hours=1),
    )
    open_segment = Event(
        id="seg-2",
        start=now - timedelta(minutes=30),
        end=None,
    )

    service = CalDAVSessionService(FakeWorkLog(now, [closed, open_segment]))

    assert service.work_segments(task) == [closed, open_segment]
    assert service.work_seconds(task, now=now) == 90 * 60
