from __future__ import annotations

from datetime import datetime, timezone
from inspect import signature

from caldav_assistant.api import Task
from caldav_assistant.api.v1.protocols import TasksAPI
from caldav_assistant.internal.activity import ActivityService
from caldav_assistant.internal.tasks.service import TaskService
from caldav_assistant.internal.wordpress.service import WordPressService


def _parameter_names(callable_obj):
    return list(signature(callable_obj).parameters)


def test_frozen_task_api_does_not_gain_thunderbird_only_parameters_or_cancel():
    for name in ("start", "pause", "resume", "complete"):
        assert _parameter_names(getattr(TasksAPI, name)) == ["self", "task"]
        assert _parameter_names(getattr(TaskService, name)) == ["self", "task"]

    assert not hasattr(TasksAPI, "cancel")
    assert not hasattr(Task, "cancel")
    assert not hasattr(TaskService, "cancel")

    assert hasattr(TaskService, "_start")
    assert hasattr(TaskService, "_pause")
    assert hasattr(TaskService, "_resume")
    assert hasattr(TaskService, "_complete")
    assert hasattr(TaskService, "_cancel")


def test_frozen_activity_record_keeps_at_as_ordinary_metadata_name():
    params = signature(ActivityService.record).parameters
    assert "at" not in params
    assert list(params) == ["self", "action", "object_id", "metadata"]
    assert hasattr(ActivityService, "_record_at")


def test_wordpress_thunderbird_helpers_stay_internal():
    assert not hasattr(WordPressService, "attach_file")
    assert not hasattr(WordPressService, "daily_log_reference")
    assert hasattr(WordPressService, "_attach_file")
    assert hasattr(WordPressService, "_daily_log_reference")


class _ActivityRepo:
    def __init__(self):
        self.rows = []

    def record(self, timestamp, action, object_id, metadata):
        self.rows.append((timestamp, action, object_id, metadata))

    def between(self, start, end):
        return []

    def for_object(self, object_id):
        return []


def test_public_activity_record_still_treats_at_as_metadata():
    fixed_now = datetime(2026, 9, 27, 4, 0, tzinfo=timezone.utc)
    supplied_metadata_time = datetime(2026, 9, 26, 1, 2, tzinfo=timezone.utc)
    repo = _ActivityRepo()
    activity = ActivityService(repo, clock=lambda: fixed_now)

    item = activity.record("custom_event", "x", at=supplied_metadata_time)

    assert item.timestamp == fixed_now
    assert item.metadata["at"] == supplied_metadata_time
