from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from caldav_assistant.api import ActionResult, Activity, Agenda, AgendaItem, Event, Task
from caldav_assistant.api.v1.errors import UnavailableError


class TaskFacade:
    def __init__(self):
        self.calls = []

    def complete(self, task):
        self.calls.append(("complete", task))
        return ActionResult(True, affected=task)

    def start(self, task):
        self.calls.append(("start", task))
        return ActionResult(True, affected=task)

    def pause(self, task):
        self.calls.append(("pause", task))
        return ActionResult(True, affected=task)

    def resume(self, task):
        self.calls.append(("resume", task))
        return ActionResult(True, affected=task)

    def update(self, task, **changes):
        self.calls.append(("update", task, changes))
        return ActionResult(True, affected=task)

    def delete(self, task):
        self.calls.append(("delete", task))
        return ActionResult(True, affected=task)


class EventFacade:
    def __init__(self):
        self.calls = []

    def update(self, event, **changes):
        self.calls.append(("update", event, changes))
        return ActionResult(True, affected=event)

    def delete(self, event):
        self.calls.append(("delete", event))
        return ActionResult(True, affected=event)


def test_task_public_fields_preserve_date_only_and_delegate_every_mutation():
    facade = TaskFacade()
    task = Task(
        id="t1",
        summary="Report",
        start=date(2026, 8, 26),
        due=date(2026, 8, 30),
        priority=3,
        categories=["school"],
        _service=facade,
    )

    assert task.start == date(2026, 8, 26)
    assert task.complete().success
    assert task.start_task().success
    assert task.pause().success
    assert task.resume().success
    assert task.set_due(date(2026, 9, 1)).success
    assert task.edit(summary="Final report").success
    assert task.delete().success

    assert [call[0] for call in facade.calls] == [
        "complete", "start", "pause", "resume", "update", "update", "delete"
    ]
    assert facade.calls[4][2] == {"due": date(2026, 9, 1)}


def test_task_start_name_collision_is_resolved_without_renaming_frozen_data_field():
    task = Task(start=date(2026, 8, 26), _service=TaskFacade())
    assert task.start == date(2026, 8, 26)
    assert callable(task.start_task)


def test_detached_object_does_not_silently_pretend_a_mutation_succeeded():
    with pytest.raises(UnavailableError):
        Task(id="t1", summary="Report").complete()
    with pytest.raises(UnavailableError):
        Event(id="e1", summary="Lesson").delete()


def test_event_convenience_methods_are_thin_service_delegates():
    facade = EventFacade()
    event = Event(id="e1", summary="Lesson", _service=facade)

    assert event.edit(location="Room 2").success
    assert event.delete().success
    assert facade.calls[0] == ("update", event, {"location": "Room 2"})
    assert facade.calls[1] == ("delete", event)


def test_agenda_is_a_small_domain_container_not_an_engine():
    item = AgendaItem(Task(id="t1", summary="Report"), date(2026, 8, 26), "task")
    agenda = Agenda([item])
    assert len(agenda) == 1
    assert list(agenda) == [item]
    assert agenda[0] is item


def test_activity_and_action_result_remain_plain_public_domain_objects():
    timestamp = datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc)
    activity = Activity(timestamp, "task_completed", "t1", {"source": "test"})
    result = ActionResult(True, "done", affected=activity, undo_available=True)

    assert result.success is True
    assert result.affected is activity
    assert activity.object_id == "t1"
