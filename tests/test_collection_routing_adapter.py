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


class TaskCalendar:
    url = "https://dav.example/tasks/"

    def __init__(self):
        self.include_completed_calls = []

    def get_todos(self, *, include_completed):
        self.include_completed_calls.append(include_completed)
        if include_completed:
            return [
                Task(id="pending", summary="Pending", completed=False),
                Task(id="done", summary="Done", completed=True, status="COMPLETED"),
            ]
        return [Task(id="pending", summary="Pending", completed=False)]


class ReadAdapter(Adapter):
    base_url = "https://dav.example/"

    def __init__(self):
        super().__init__()
        self.calendar = TaskCalendar()

    def _calendars(self):
        return [self.calendar]

    @staticmethod
    def _to_task(resource, calendar):
        return resource


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


def test_pending_task_filter_is_pushed_down_to_caldav_server_query():
    inner = ReadAdapter()
    routed = CollectionRoutingCalDAVAdapter(
        inner,
        task_collection_url=lambda: "https://dav.example/tasks/",
        event_collection_url=lambda: None,
    )

    result = routed.list_tasks(completed=False)

    assert [task.id for task in result] == ["pending"]
    assert inner.calendar.include_completed_calls == [False]


def test_general_task_listing_still_includes_completed_tasks():
    inner = ReadAdapter()
    routed = CollectionRoutingCalDAVAdapter(
        inner,
        task_collection_url=lambda: "https://dav.example/tasks/",
        event_collection_url=lambda: None,
    )

    result = routed.list_tasks()

    assert [task.id for task in result] == ["pending", "done"]
    assert inner.calendar.include_completed_calls == [True]
