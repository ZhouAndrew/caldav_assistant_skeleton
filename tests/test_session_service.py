from caldav_assistant.api import Task
from caldav_assistant.internal.session import SessionService


class MemoryState:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


class Tasks:
    def __init__(self, items):
        self.items = {item.id: item for item in items}

    def list(self, **filters):
        result = list(self.items.values())
        for key, value in filters.items():
            result = [item for item in result if getattr(item, key) == value]
        return result

    def get(self, uid):
        return self.items[uid]


def test_recovers_exactly_one_legacy_in_process_task():
    task = Task(id="1", summary="Legacy work", status="IN-PROCESS")
    state = MemoryState()
    session = SessionService(state, Tasks([task]))

    assert session.current_task_id() == "1"
    assert state.values["current_task_uid"] == "1"
    assert session.current_task() is task


def test_does_not_guess_when_multiple_legacy_tasks_are_in_process():
    tasks = Tasks([
        Task(id="1", summary="One", status="IN-PROCESS"),
        Task(id="2", summary="Two", status="IN-PROCESS"),
    ])
    state = MemoryState()
    session = SessionService(state, tasks)

    assert session.current_task_id() is None
    assert "current_task_uid" not in state.values


def test_paused_in_process_task_is_not_recovered_as_current():
    task = Task(id="1", summary="Paused", status="IN-PROCESS")
    state = MemoryState({"paused_task_uids": ["1"]})
    session = SessionService(state, Tasks([task]))

    assert session.current_task_id() is None
