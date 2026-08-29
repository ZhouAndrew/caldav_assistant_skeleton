from types import SimpleNamespace

from caldav_assistant.api import Agenda, AgendaItem, Event, Task
from caldav_assistant.internal.agenda.service import AgendaService


class Tasks:
    def list(self, **filters):
        return [Task(id="active", summary="Active"), Task(id="paused", summary="Paused")]


class Events:
    def list(self, **filters):
        return [
            Event(id="normal", summary="Meeting", categories=[]),
            Event(id="work", summary="Work — Active", categories=["caldav-assistant-work"]),
        ]


class Engine:
    def __init__(self):
        self.last_events = None

    def build(self, tasks, events, **kwargs):
        self.last_events = list(events)
        return Agenda()

    def candidates(self, tasks, events):
        self.last_events = list(events)
        return Agenda([AgendaItem(tasks[0], kind="task")])


class Next:
    def __init__(self):
        self.options = None

    def choose(self, agenda, kind=None, **options):
        self.options = options
        return agenda[0]


class Session:
    def current_task_id(self):
        return "active"

    def paused_task_ids(self):
        return ("paused",)


def test_agenda_hides_internal_work_events_and_uses_caldav_session_for_next():
    engine = Engine()
    chooser = Next()
    service = AgendaService(
        Tasks(), Events(), engine, chooser, state={}, session=Session()
    )

    service.today()
    assert [event.id for event in engine.last_events] == ["normal"]

    service.next()
    assert [event.id for event in engine.last_events] == ["normal"]
    assert chooser.options["current_task_uid"] == "active"
    assert chooser.options["skipped_uids"] == ("paused",)
