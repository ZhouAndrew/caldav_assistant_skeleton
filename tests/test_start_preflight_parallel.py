from __future__ import annotations

from threading import Barrier

import pytest

from caldav_assistant.api import Task
from caldav_assistant.api.v1.errors import ValidationError
from caldav_assistant.internal.tasks import CalDAVWorkTaskService


class _Adapter:
    def __init__(self, barrier: Barrier) -> None:
        self.barrier = barrier
        self.get_calls = 0

    def get_task(self, task_id: str) -> Task:
        self.get_calls += 1
        self.barrier.wait(timeout=0.5)
        return Task(id=task_id, summary="Requested", status="NEEDS-ACTION")


class _WorkLog:
    def __init__(self, barrier: Barrier) -> None:
        self.barrier = barrier
        self.open_reads = 0

    def configured(self) -> bool:
        return True

    def open_snapshot(self):
        self.open_reads += 1
        self.barrier.wait(timeout=0.5)
        return ("open-work",)

    def current_task_id(self, *, snapshot=None):
        assert snapshot == ("open-work",)
        return "already-active"


def test_start_reads_target_task_and_open_work_in_parallel_before_conflict():
    barrier = Barrier(2)
    adapter = _Adapter(barrier)
    worklog = _WorkLog(barrier)
    service = CalDAVWorkTaskService(adapter, worklog=worklog)

    with pytest.raises(ValidationError, match="Another Task is currently being worked on"):
        service.start("requested")

    assert adapter.get_calls == 1
    assert worklog.open_reads == 1
