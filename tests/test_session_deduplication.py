from __future__ import annotations

from caldav_assistant.api import Task
from caldav_assistant.internal.session import CalDAVSessionService


class DuplicateTasks:
    def __init__(self):
        self.task = Task(id="anki-1", summary="Anki", status="IN-PROCESS")

    def list(self, **filters):
        assert filters == {"status": "IN-PROCESS"}
        # Simulate the same logical CalDAV Task appearing twice in a read result.
        return [self.task, self.task]

    def get(self, uid):
        assert uid == "anki-1"
        return self.task


class WorkLog:
    def configured(self):
        return True

    def current_task_id(self):
        return None

    def segments_for(self, task):
        assert task.id == "anki-1"
        return [object()]


def test_paused_tasks_deduplicate_same_caldav_uid_before_resume_menu():
    tasks = DuplicateTasks()
    session = CalDAVSessionService(WorkLog(), tasks=tasks)

    assert session.paused_task_ids() == ("anki-1",)
    paused = session.paused_tasks()
    assert len(paused) == 1
    assert paused[0].summary == "Anki"
