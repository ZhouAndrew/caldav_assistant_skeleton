from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from caldav_assistant.api import Event, Task
from caldav_assistant.internal.session import CalDAVSessionService
from caldav_assistant.internal.tasks import CalDAVWorkTaskService
from caldav_assistant.internal.worklog import WorkLogService


WORK_URL = "https://dav.example/work/"


class CountingAdapter:
    def __init__(self, tasks):
        self.tasks = {task.id: task for task in tasks}
        self.events: list[Event] = []
        self.task_list_reads = 0
        self.work_event_reads = 0
        self.next_event_id = 1

    def get_task(self, task_id):
        return self.tasks[task_id]

    def list_tasks(self, **filters):
        self.task_list_reads += 1
        items = list(self.tasks.values())
        for key, value in filters.items():
            items = [item for item in items if getattr(item, key) == value]
        return items

    def update_task(self, task_id, changes, *, etag=None):
        task = self.tasks[task_id]
        values = {
            key: value
            for key, value in task.__dict__.items()
            if not key.startswith("_")
        }
        values.update({key: value for key, value in changes.items() if key in values})
        updated = Task(**values)
        self.tasks[task_id] = updated
        return updated

    def list_events(self, **filters):
        self.work_event_reads += 1
        items = list(self.events)
        category = filters.get("category")
        if category is not None:
            items = [event for event in items if category in event.categories]
        description = filters.get("description")
        if description is not None:
            items = [event for event in items if event.description == description]
        return items

    def create_event(self, event):
        copied = replace(
            event,
            id=f"w{self.next_event_id}",
            categories=list(event.categories),
        )
        self.next_event_id += 1
        setattr(copied, "_caldav_collection_url", getattr(event, "_caldav_collection_url"))
        self.events.append(copied)
        return copied

    def update_event(self, event_id, changes, *, etag=None):
        for index, event in enumerate(self.events):
            if event.id != event_id:
                continue
            values = {
                key: value
                for key, value in event.__dict__.items()
                if not key.startswith("_")
            }
            values.update({key: value for key, value in changes.items() if key in values})
            updated = Event(**values)
            setattr(updated, "_caldav_collection_url", getattr(event, "_caldav_collection_url"))
            self.events[index] = updated
            return updated
        raise KeyError(event_id)

    def delete_event(self, event_id, *, etag=None):
        self.events = [event for event in self.events if event.id != event_id]


class Clock:
    def __init__(self):
        self.value = datetime(2026, 9, 6, 6, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, minutes):
        self.value += timedelta(minutes=minutes)


def _build_service():
    task = Task(id="t1", summary="Report", status="NEEDS-ACTION")
    adapter = CountingAdapter([task])
    clock = Clock()
    worklog = WorkLogService(adapter, lambda: WORK_URL, clock=clock)
    session = CalDAVSessionService(worklog)
    service = CalDAVWorkTaskService(adapter, None, None, session, worklog=worklog)
    session.bind_tasks(service)
    return adapter, clock, worklog, session, service


def _assert_work_reads(adapter, expected, operation):
    before = adapter.work_event_reads
    operation()
    assert adapter.work_event_reads - before == expected


def test_caldav_work_lifecycle_uses_bounded_targeted_reads_not_full_history_per_action():
    adapter, clock, _worklog, _session, service = _build_service()

    # Start and pause need only the current/open Work set.
    _assert_work_reads(adapter, 1, lambda: service.start("t1"))

    clock.advance(10)
    _assert_work_reads(adapter, 1, lambda: service.pause("t1"))

    # Resume needs two bounded facts: the open set plus this Task's own history.
    # It deliberately does not load all historical Work VEVENTs.
    clock.advance(10)
    _assert_work_reads(adapter, 2, lambda: service.resume("t1"))

    # Completing the current Task reuses the open snapshot; its open interval is
    # already proof that the Task was worked, so no history query is needed.
    clock.advance(10)
    _assert_work_reads(adapter, 1, lambda: service.complete("t1"))


def _closed_work_event(task_id: str, event_id: str) -> Event:
    event = Event(
        id=event_id,
        summary=f"Work — {task_id}",
        start=datetime(2026, 9, 6, 5, 0, tzinfo=timezone.utc),
        end=datetime(2026, 9, 6, 5, 10, tzinfo=timezone.utc),
        description=(
            f"{WorkLogService.DESCRIPTION_HEADER}\n"
            f"{WorkLogService.TASK_PREFIX}{task_id}"
        ),
        categories=[WorkLogService.CATEGORY],
    )
    setattr(event, "_caldav_collection_url", WORK_URL)
    return event


def test_paused_session_lookup_is_constant_worklog_reads_not_one_scan_per_task():
    tasks = [
        Task(id="t1", summary="One", status="IN-PROCESS"),
        Task(id="t2", summary="Two", status="IN-PROCESS"),
        Task(id="t3", summary="Three", status="IN-PROCESS"),
    ]
    adapter = CountingAdapter(tasks)
    adapter.events.extend(
        [
            _closed_work_event("t1", "w1"),
            _closed_work_event("t2", "w2"),
        ]
    )
    worklog = WorkLogService(adapter, lambda: WORK_URL)
    session = CalDAVSessionService(worklog)

    class Tasks:
        def list(self, **filters):
            return adapter.list_tasks(**filters)

        def get(self, task_id):
            return adapter.get_task(task_id)

    session.bind_tasks(Tasks())

    assert session.paused_task_ids() == ("t1", "t2")
    assert adapter.task_list_reads == 1
    assert adapter.work_event_reads == 1


def test_paused_tasks_reuses_listed_task_objects_without_per_uid_gets():
    tasks = [
        Task(id="t1", summary="One", status="IN-PROCESS"),
        Task(id="t2", summary="Two", status="IN-PROCESS"),
    ]
    adapter = CountingAdapter(tasks)
    adapter.events.append(_closed_work_event("t1", "w1"))
    worklog = WorkLogService(adapter, lambda: WORK_URL)
    session = CalDAVSessionService(worklog)

    class Tasks:
        get_calls = 0

        def list(self, **filters):
            return adapter.list_tasks(**filters)

        def get(self, task_id):
            self.get_calls += 1
            return adapter.get_task(task_id)

    task_api = Tasks()
    session.bind_tasks(task_api)

    assert [task.id for task in session.paused_tasks()] == ["t1"]
    assert adapter.task_list_reads == 1
    assert adapter.work_event_reads == 1
    assert task_api.get_calls == 0
