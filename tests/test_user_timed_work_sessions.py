from __future__ import annotations

from datetime import datetime, timezone

from caldav_assistant.api import Event, Task
from caldav_assistant.internal.activity import ActivityService
from caldav_assistant.internal.tasks.service import TaskService
from caldav_assistant.internal.worklog import WorkLogService


class ActivityRepo:
    def __init__(self):
        self.rows = []

    def record(self, timestamp, action, object_id, metadata):
        self.rows.append((timestamp, action, object_id, metadata))

    def between(self, start, end):
        return []

    def for_object(self, object_id):
        return []


class TaskAdapter:
    def __init__(self, task):
        self.task = task

    def get_task(self, task_id):
        assert task_id == self.task.id
        return self.task

    def list_tasks(self, **filters):
        return [self.task]

    def update_task(self, task_id, changes):
        assert task_id == self.task.id
        for key, value in changes.items():
            setattr(self.task, key, value)
        return self.task


class EventAdapter:
    def __init__(self):
        self.events = {}
        self.next_id = 1

    def create_event(self, event):
        event.id = f"e{self.next_id}"
        self.next_id += 1
        self.events[event.id] = event
        return event

    def get_event(self, event_id):
        return self.events[event_id]

    def update_event_in_collection(self, collection_url, event_id, changes):
        event = self.events[event_id]
        for key, value in changes.items():
            setattr(event, key, value)
        return event

    def list_events_in_collection(self, collection_url, **filters):
        values = list(self.events.values())
        category = filters.get("category")
        if category:
            values = [e for e in values if category in (e.categories or [])]
        return values


class ReferenceEventAdapter(EventAdapter):
    def __init__(self):
        super().__init__()
        self.reference_calls = []
        self.get_collection_calls = []

    def get_event_in_collection(self, collection_url, event_id):
        self.get_collection_calls.append((collection_url, event_id))
        return self.events[event_id]

    def update_event_references_in_collection(
        self,
        collection_url,
        event_id,
        *,
        description,
        wordpress_url=None,
        attachment_urls=(),
    ):
        self.reference_calls.append(
            {
                "collection_url": collection_url,
                "event_id": event_id,
                "description": description,
                "wordpress_url": wordpress_url,
                "attachment_urls": list(attachment_urls),
            }
        )
        event = self.events[event_id]
        event.description = description
        return event


def test_activity_can_use_user_entered_timestamp():
    repo = ActivityRepo()
    service = ActivityService(repo)
    supplied = datetime(2026, 9, 27, 9, 20, tzinfo=timezone.utc)

    item = service._record_at(supplied, "task_started", "task-1")

    assert item.timestamp == supplied
    assert repo.rows[0][0] == supplied


def test_work_segment_uses_supplied_start_and_end_times():
    adapter = EventAdapter()
    service = WorkLogService(adapter, lambda: "http://example.invalid/work/")
    task = Task(id="task-1", summary="Prepare Python course")
    start = datetime(2026, 9, 27, 9, 20, tzinfo=timezone.utc)
    end = datetime(2026, 9, 27, 10, 5, tzinfo=timezone.utc)

    opened = service.start_segment(task, at=start, snapshot=())
    assert opened.start == start
    assert opened.end is None

    closed = service.close_segment(task, at=end, snapshot=(opened,))
    assert closed.start == start
    assert closed.end == end
    assert WorkLogService.OPEN_CATEGORY not in closed.categories


def test_cancel_uses_user_time_and_keeps_task_as_cancelled_not_deleted():
    task = Task(id="task-1", summary="Prepare Python course", status="IN-PROCESS")
    repo = ActivityRepo()
    activity = ActivityService(repo)
    service = TaskService(TaskAdapter(task), activity=activity)
    at = datetime(2026, 9, 27, 11, 10, tzinfo=timezone.utc)

    result = service._cancel(task, at=at)

    assert result.success is True
    assert task.status == "CANCELLED"
    assert task.completed is False
    assert repo.rows[-1][0] == at
    assert repo.rows[-1][1] == "task_cancelled"


def test_work_segment_can_point_back_to_wordpress_and_attachment():
    adapter = EventAdapter()
    service = WorkLogService(adapter, lambda: "http://example.invalid/work/")
    task = Task(id="task-1", summary="Prepare Python course")
    start = datetime(2026, 9, 27, 9, 20, tzinfo=timezone.utc)
    end = datetime(2026, 9, 27, 10, 5, tzinfo=timezone.utc)

    opened = service.start_segment(task, at=start, snapshot=())
    closed = service.close_segment(task, at=end, snapshot=(opened,))
    updated = service.add_references(
        closed.id,
        wordpress_url="https://wordpress.example/2026/09/27/log/",
        attachment_urls=["https://wordpress.example/uploads/lesson.png"],
    )

    assert "WordPress: https://wordpress.example/2026/09/27/log/" in updated.description
    assert "Attachment: https://wordpress.example/uploads/lesson.png" in updated.description


def test_references_are_read_and_written_in_the_work_history_collection():
    adapter = ReferenceEventAdapter()
    work_url = "http://example.invalid/history/"
    service = WorkLogService(adapter, lambda: work_url)
    task = Task(id="task-1", summary="Prepare Python course")
    start = datetime(2026, 9, 27, 9, 20, tzinfo=timezone.utc)
    end = datetime(2026, 9, 27, 10, 5, tzinfo=timezone.utc)

    opened = service.start_segment(task, at=start, snapshot=())
    closed = service.close_segment(task, at=end, snapshot=(opened,))
    service.add_references(
        closed.id,
        wordpress_url="https://wordpress.example/log/",
        attachment_urls=["https://wordpress.example/uploads/evidence.pdf"],
    )

    assert adapter.get_collection_calls == [(work_url, closed.id)]
    assert adapter.reference_calls == [
        {
            "collection_url": work_url,
            "event_id": closed.id,
            "description": (
                "CalDAV Assistant Work Segment\n"
                "Task-UID: task-1\n"
                "WordPress: https://wordpress.example/log/\n"
                "Attachment: https://wordpress.example/uploads/evidence.pdf"
            ),
            "wordpress_url": "https://wordpress.example/log/",
            "attachment_urls": [
                "https://wordpress.example/uploads/evidence.pdf"
            ],
        }
    ]
