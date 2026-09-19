from __future__ import annotations

from threading import Barrier

import pytest

from caldav_assistant.api import Task
from caldav_assistant.api.v1.errors import ConflictError, UnavailableError, ValidationError
from caldav_assistant.internal.tasks import CalDAVWorkTaskService


class _Adapter:
    def __init__(self, barrier: Barrier, *, stale: bool = False) -> None:
        self.barrier = barrier
        self.stale = stale
        self.get_calls = 0

    def get_task(self, task_id: str) -> Task:
        self.get_calls += 1
        self.barrier.wait(timeout=0.5)
        return Task(
            id=task_id,
            summary="Requested",
            status="NEEDS-ACTION",
            stale=self.stale,
        )


class _WorkLog:
    def __init__(self, barrier: Barrier, *, current_id: str | None = "already-active") -> None:
        self.barrier = barrier
        self.current_id = current_id
        self.open_reads = 0
        self.start_calls = 0

    def configured(self) -> bool:
        return True

    def open_snapshot(self):
        self.open_reads += 1
        self.barrier.wait(timeout=0.5)
        return ("open-work",)

    def current_task_id(self, *, snapshot=None):
        assert snapshot == ("open-work",)
        return self.current_id

    def start_segment(self, task, *, snapshot=None):
        self.start_calls += 1
        raise AssertionError("start_segment must not run in these preflight tests")


@pytest.mark.parametrize(
    "requested",
    [
        "requested",
        Task(id="requested", summary="Cached requested", stale=True),
    ],
)
def test_start_reads_target_task_and_open_work_in_parallel_before_conflict(requested):
    barrier = Barrier(2)
    adapter = _Adapter(barrier)
    worklog = _WorkLog(barrier)
    service = CalDAVWorkTaskService(adapter, worklog=worklog)

    with pytest.raises(ValidationError, match="Another Task is currently being worked on"):
        service.start(requested)

    # A Task object from the stale startup menu must be reduced to its id and read
    # from CalDAV again; passing the object itself must never bypass this preflight.
    assert adapter.get_calls == 1
    assert worklog.open_reads == 1
    assert worklog.start_calls == 0


def test_start_refuses_stale_fallback_before_any_work_mutation():
    barrier = Barrier(2)
    adapter = _Adapter(barrier, stale=True)
    worklog = _WorkLog(barrier, current_id=None)
    service = CalDAVWorkTaskService(adapter, worklog=worklog)

    cached = Task(id="requested", summary="Cached requested", stale=True)
    with pytest.raises(UnavailableError, match="cannot use cached Task data"):
        service.start(cached)

    assert adapter.get_calls == 1
    assert worklog.open_reads == 1
    assert worklog.start_calls == 0


def test_start_without_work_collection_still_refreshes_cached_task_before_mutation():
    class StaleOnlyAdapter:
        def __init__(self) -> None:
            self.get_calls = 0
            self.update_calls = 0

        def get_task(self, task_id: str) -> Task:
            self.get_calls += 1
            return Task(
                id=task_id,
                summary="Cached fallback",
                status="NEEDS-ACTION",
                stale=True,
            )

        def update_task(self, task_id: str, changes):
            self.update_calls += 1
            raise AssertionError("stale Start must fail before update_task")

    adapter = StaleOnlyAdapter()
    service = CalDAVWorkTaskService(adapter, worklog=None)
    cached = Task(id="requested", summary="Cached requested", stale=True)

    with pytest.raises(UnavailableError, match="cannot use cached Task data"):
        service.start(cached)

    assert adapter.get_calls == 1
    assert adapter.update_calls == 0


def test_start_etag_race_aborts_and_rolls_back_new_work_segment():
    class RacingAdapter:
        def __init__(self) -> None:
            self.get_calls = 0
            self.fast_write_calls = 0
            self.ordinary_write_calls = 0

        def get_task(self, task_id: str) -> Task:
            self.get_calls += 1
            return Task(id=task_id, summary="Requested", status="NEEDS-ACTION")

        def update_task_from_snapshot(self, task: Task, changes):
            self.fast_write_calls += 1
            raise ConflictError("Task changed after the live preflight")

        def update_task(self, task_id: str, changes, **kwargs):
            self.ordinary_write_calls += 1
            raise AssertionError("a stale Start decision must not retry through ordinary update")

    class RacingWorkLog:
        def __init__(self) -> None:
            self.start_calls = 0
            self.discarded = []

        def configured(self) -> bool:
            return True

        def open_snapshot(self):
            return ("open-work",)

        def current_task_id(self, *, snapshot=None):
            assert snapshot == ("open-work",)
            return None

        def start_segment(self, task: Task, *, snapshot=None):
            assert snapshot == ("open-work",)
            self.start_calls += 1
            return "new-work-segment"

        def discard_segment(self, segment):
            self.discarded.append(segment)

    adapter = RacingAdapter()
    worklog = RacingWorkLog()
    service = CalDAVWorkTaskService(adapter, worklog=worklog)

    with pytest.raises(ConflictError, match="changed after the live preflight"):
        service.start("requested")

    assert adapter.get_calls == 1
    assert adapter.fast_write_calls == 1
    assert adapter.ordinary_write_calls == 0
    assert worklog.start_calls == 1
    assert worklog.discarded == ["new-work-segment"]
