from __future__ import annotations

from datetime import datetime, timezone

from caldav_assistant.api import Event, Task
from caldav_assistant.internal.tasks import (
    CompletionLoggingTaskService,
    TaskCompletionLogService,
)
from caldav_assistant.internal.wordpress.service import WordPressService


class Outbox:
    def __init__(self):
        self.items = []

    def enqueue(self, payload):
        item = {
            "id": len(self.items) + 1,
            "payload": payload,
            "attempts": 0,
            "last_error": None,
        }
        self.items.append(item)
        return dict(item)

    def pending(self, limit=None):
        items = [dict(item) for item in self.items]
        return items if limit is None else items[:limit]

    def mark_sent(self, item_id):
        self.items = [item for item in self.items if item["id"] != item_id]

    def mark_failed(self, item_id, error):
        return None


class WordPressAdapter:
    def __init__(self):
        self.calls = []

    def create_log(self, text, **metadata):
        self.calls.append((text, metadata))
        return {"id": 10}

    def test_connection(self):
        return True


class ActivitySource:
    def __init__(self):
        self.records = []

    def record(self, action, object_id=None, **metadata):
        self.records.append((action, object_id, metadata))


class WorkLogSource:
    def __init__(self, segments=None):
        self.segments = list(segments or [])

    def segments_for(self, task):
        return list(self.segments)


class TaskAdapter:
    def __init__(self):
        self.task = Task(id="t1", summary="Report", status="NEEDS-ACTION")

    def get_task(self, task_id):
        assert task_id == "t1"
        return self.task

    def list_tasks(self, **filters):
        return [self.task]

    def update_task(self, task_id, changes, *, etag=None):
        values = {
            key: value
            for key, value in self.task.__dict__.items()
            if key != "_service"
        }
        values.update({key: value for key, value in changes.items() if key in values})
        self.task = Task(**values)
        return self.task

    def create_task(self, task):
        raise AssertionError("not used")

    def delete_task(self, task_id, *, etag=None):
        raise AssertionError("not used")


def dt(hour, minute=0):
    return datetime(2026, 8, 29, hour, minute, tzinfo=timezone.utc)


def test_queue_log_writes_only_outbox_until_background_flush():
    adapter = WordPressAdapter()
    outbox = Outbox()
    wordpress = WordPressService(adapter, outbox)

    result = wordpress.queue_log("Completed work", title="Completed — Report")

    assert result.success is True
    assert "outbox" in result.message.lower()
    assert len(outbox.pending()) == 1
    assert adapter.calls == []

    payload = outbox.pending()[0]["payload"]
    captured = payload["args"]["metadata"]
    assert captured["title"] == "Completed — Report"
    assert captured["_logged_at"]
    assert captured["_request_id"] == payload["request_id"]

    summary = wordpress.flush()
    assert summary["sent"] == 1
    assert outbox.pending() == []
    assert len(adapter.calls) == 1
    text, metadata = adapter.calls[0]
    assert text == "Completed work"
    assert metadata == captured


def test_completion_logs_only_the_final_segment_closed_by_done():
    segments = [
        Event(id="w1", summary="Work — Report", start=dt(10, 0), end=dt(10, 30)),
        Event(id="w2", summary="Work — Report", start=dt(11, 0), end=dt(12, 0)),
    ]
    worklog = WorkLogSource(segments)

    class WP:
        def __init__(self):
            self.calls = []

        def queue_log(self, text, **metadata):
            self.calls.append((text, metadata))
            return True

    wp = WP()
    logger = TaskCompletionLogService(worklog, wp)
    task = Task(
        id="t1",
        summary="Report",
        status="COMPLETED",
        completed=True,
        completed_at=dt(12, 0),
    )

    logger.queue_for(task)

    assert wp.calls == [
        ("11:00-12:00 Report", {"_show_clock": False}),
    ]


def test_completion_of_already_paused_task_does_not_duplicate_previous_segment():
    segments = [
        Event(id="w1", summary="Work — Report", start=dt(10, 0), end=dt(10, 30)),
    ]
    worklog = WorkLogSource(segments)

    class WP:
        def __init__(self):
            self.calls = []

        def queue_log(self, text, **metadata):
            self.calls.append((text, metadata))
            return True

    wp = WP()
    logger = TaskCompletionLogService(worklog, wp)
    task = Task(
        id="t1",
        summary="Report",
        status="COMPLETED",
        completed=True,
        completed_at=dt(11, 0),
    )

    assert logger.queue_for(task) is None
    assert wp.calls == []


def test_completion_log_queue_failure_never_rolls_back_completed_task():
    adapter = TaskAdapter()
    activity = ActivitySource()

    class BrokenCompletionLog:
        def queue_for(self, task):
            raise OSError("outbox unavailable")

    service = CompletionLoggingTaskService(
        adapter,
        activity,
        None,
        None,
        completion_log=BrokenCompletionLog(),
    )

    result = service.complete("t1")

    assert result.success is True
    assert result.affected.status == "COMPLETED"
    assert adapter.task.status == "COMPLETED"
    assert "task_completion_log_queue_failed" not in [item[0] for item in activity.records]
