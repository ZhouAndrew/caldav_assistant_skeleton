from caldav_assistant.internal.agenda.service import AgendaService


class Query:
    def __init__(self, values):
        self.values = list(values)
        self.calls = []

    def list(self, **filters):
        self.calls.append(filters)
        return list(self.values)


class Engine:
    def __init__(self):
        self.calls = []
        self.candidate_calls = []

    def build(self, tasks, events, **kwargs):
        self.calls.append((tasks, events, kwargs))
        return "agenda"

    def candidates(self, tasks, events):
        self.candidate_calls.append((tasks, events))
        return "candidate-agenda"


class Next:
    def __init__(self):
        self.calls = []

    def choose(self, agenda, **kwargs):
        self.calls.append((agenda, kwargs))
        return "next-item"


class SnapshotSession:
    def __init__(self):
        self.calls = []

    def startup_snapshot(self, tasks):
        self.calls.append(list(tasks))
        return {
            "current_task_id": "task-current",
            "current_task": None,
            "paused_task_ids": ("task-paused",),
        }

    def current_task_id(self):
        raise AssertionError("next() must reuse startup_snapshot instead of re-reading current work")

    def paused_task_ids(self):
        raise AssertionError("next() must reuse startup_snapshot instead of re-reading paused work")


def test_today_is_projected_by_agenda_engine_not_forwarded_as_caldav_filter():
    tasks = Query(["task"])
    events = Query(["event"])
    engine = Engine()
    state = object()
    service = AgendaService(tasks, events, engine, Next(), state)

    assert service.today() == "agenda"
    assert tasks.calls == [{"completed": False}]
    assert events.calls == [{}]
    assert engine.calls == [(["task"], ["event"], {"days": 1, "user_state": state})]


def test_next_builds_candidate_agenda_and_uses_human_work_context():
    from datetime import datetime

    tasks = Query(["task"])
    events = Query(["event"])
    engine = Engine()
    next_engine = Next()
    service = AgendaService(
        tasks,
        events,
        engine,
        next_engine,
        {
            "current_task_uid": "task-current",
            "paused_task_uids": ["task-paused"],
        },
    )

    now = datetime.now().astimezone()
    assert service.next(kind="task", now=now) == "next-item"
    assert tasks.calls == [{"completed": False}]
    assert events.calls == [{}]
    assert engine.candidate_calls == [(["task"], ["event"])]
    assert next_engine.calls == [
        (
            "candidate-agenda",
            {
                "kind": "task",
                "now": now,
                "current_task_uid": "task-current",
                "skipped_uids": ("task-paused",),
            },
        )
    ]


def test_next_reuses_one_session_snapshot_from_already_fetched_tasks():
    from datetime import datetime

    tasks = Query(["task"])
    events = Query([])
    session = SnapshotSession()
    next_engine = Next()
    service = AgendaService(
        tasks,
        events,
        Engine(),
        next_engine,
        {},
        session=session,
    )

    now = datetime.now().astimezone()
    assert service.next(kind="task", now=now) == "next-item"
    assert tasks.calls == [{"completed": False}]
    assert session.calls == [["task"]]
    assert next_engine.calls[0][1]["current_task_uid"] == "task-current"
    assert next_engine.calls[0][1]["skipped_uids"] == ("task-paused",)
