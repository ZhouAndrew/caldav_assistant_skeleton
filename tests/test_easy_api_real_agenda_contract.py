from types import SimpleNamespace

import caldav_assistant.easy as easy
from caldav_assistant.api import AgendaItem, Event, Task


def test_next_task_unwraps_real_agenda_item_contract(monkeypatch):
    task = Task(id="t1", summary="Report")
    agenda = SimpleNamespace(next=lambda **kwargs: AgendaItem(task, kind="task"))
    monkeypatch.setattr(easy, "_ctx", lambda: SimpleNamespace(agenda=agenda))

    assert easy.next_task() is task


def test_next_event_unwraps_real_agenda_item_contract(monkeypatch):
    event = Event(id="e1", summary="Lesson")
    agenda = SimpleNamespace(next=lambda **kwargs: AgendaItem(event, kind="event"))
    monkeypatch.setattr(easy, "_ctx", lambda: SimpleNamespace(agenda=agenda))

    assert easy.next_event() is event
