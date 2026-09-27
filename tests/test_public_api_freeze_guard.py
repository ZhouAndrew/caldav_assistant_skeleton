from __future__ import annotations

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
