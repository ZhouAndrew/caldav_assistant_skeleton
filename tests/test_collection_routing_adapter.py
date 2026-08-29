from caldav_assistant.api import Event, Task
from caldav_assistant.internal.caldav.routing import CollectionRoutingCalDAVAdapter


class Adapter:
    def __init__(self):
        self.task = None
        self.event = None

    def create_task(self, task):
        self.task = task
        return task

    def create_event(self, event):
        self.event = event
        return event


def test_routes_new_task_and_event_to_user_selected_collection_roles():
    inner = Adapter()
    routed = CollectionRoutingCalDAVAdapter(
        inner,
        task_collection_url=lambda: "https://dav.example/tasks/",
        event_collection_url=lambda: "https://dav.example/calendar/",
    )

    routed.create_task(Task(summary="Homework"))
    routed.create_event(Event(summary="Class"))

    assert getattr(inner.task, "_caldav_collection_url") == "https://dav.example/tasks/"
    assert getattr(inner.event, "_caldav_collection_url") == "https://dav.example/calendar/"


def test_explicit_worklog_collection_overrides_default_event_collection():
    inner = Adapter()
    routed = CollectionRoutingCalDAVAdapter(
        inner,
        task_collection_url=lambda: None,
        event_collection_url=lambda: "https://dav.example/calendar/",
    )
    event = Event(summary="Work — Homework")
    setattr(event, "_caldav_collection_url", "https://dav.example/work/")

    routed.create_event(event)

    assert getattr(inner.event, "_caldav_collection_url") == "https://dav.example/work/"
