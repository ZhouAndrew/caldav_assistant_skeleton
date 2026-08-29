from __future__ import annotations

from datetime import date, datetime, time as Time

import pytest

import caldav_assistant.easy as easy
from caldav_assistant.api import AssistantContext, Event, Task
from caldav_assistant.api.v1.errors import AmbiguousError, NotFoundError, ValidationError
from caldav_assistant.internal.runtime.current_context import (
    bind_current_context,
    clear_current_context,
)


class Calls:
    def __init__(self):
        self.items = []

    def add(self, name, *args, **kwargs):
        self.items.append((name, args, kwargs))
        return (name, args, kwargs)


def make_context():
    calls = Calls()
    next_task = Task(id="t1", summary="Report final")
    next_event = Event(id="e1", summary="Lesson")

    class Tasks:
        def list(self, **kwargs):
            calls.add("tasks.list", **kwargs)
            return [next_task]

        def find(self, query, **kwargs):
            calls.add("tasks.find", query, **kwargs)
            if query.casefold() == "report":
                return next_task
            raise NotFoundError(query)

        def get(self, task):
            calls.add("tasks.get", task)
            if task == "t1":
                return next_task
            raise NotFoundError(task)

        def create(self, summary, **kwargs): return calls.add("tasks.create", summary, **kwargs)
        def update(self, task, **kwargs): return calls.add("tasks.update", task, **kwargs)
        def start(self, task): return calls.add("tasks.start", task)
        def pause(self, task): return calls.add("tasks.pause", task)
        def resume(self, task): return calls.add("tasks.resume", task)
        def complete(self, task): return calls.add("tasks.complete", task)
        def delete(self, task): return calls.add("tasks.delete", task)

    class Events:
        def list(self, **kwargs):
            calls.add("events.list", **kwargs)
            return [next_event]

        def find(self, query, **kwargs):
            calls.add("events.find", query, **kwargs)
            if query.casefold() == "lesson":
                return next_event
            raise NotFoundError(query)

        def get(self, event):
            calls.add("events.get", event)
            if event == "e1":
                return next_event
            raise NotFoundError(event)

        def create(self, summary, **kwargs): return calls.add("events.create", summary, **kwargs)
        def update(self, event, **kwargs): return calls.add("events.update", event, **kwargs)
        def delete(self, event): return calls.add("events.delete", event)

    class Agenda:
        def today(self): return calls.add("agenda.today")
        def range(self, **kwargs): return calls.add("agenda.range", **kwargs)
        def next(self, **kwargs):
            calls.add("agenda.next", **kwargs)
            if kwargs.get("kind") == "task":
                return next_task
            if kwargs.get("kind") == "event":
                return next_event
            return "next"

    class TimeAPI:
        def parse_date(self, text, *, bias="any"):
            calls.add("time.parse_date", text, bias=bias)
            values = {
                "August5": date(2027, 8, 5),
                "tomorrow": date(2026, 8, 30),
            }
            if text in values:
                return values[text]
            raise ValidationError(f"not a date: {text}")

        def parse_datetime(self, text, *, bias="any"):
            calls.add("time.parse_datetime", text, bias=bias)
            if text == "12:34":
                return datetime(2026, 8, 29, 12, 34)
            if text == "tomorrow 17:00":
                return datetime(2026, 8, 30, 17, 0)
            raise ValidationError(f"not a datetime: {text}")

        def parse_time(self, text):
            calls.add("time.parse_time", text)
            if text == "12:34":
                return Time(12, 34)
            raise ValidationError(text)

    class UI:
        def show(self, value): return calls.add("ui.show", value)
        def ask_date(self, prompt): return calls.add("ui.ask_date", prompt)
        def ask_time(self, prompt): return calls.add("ui.ask_time", prompt)
        def ask_datetime(self, prompt): return calls.add("ui.ask_datetime", prompt)

        def choose(self, title, items, **kwargs):
            calls.add("ui.choose", title, items, **kwargs)
            values = list(items)
            return values[0] if values else None

        def choose_many(self, title, items, **kwargs):
            return calls.add("ui.choose_many", title, items, **kwargs)

        def confirm(self, text, **kwargs):
            return calls.add("ui.confirm", text, **kwargs)

        def choose_task(self, **kwargs):
            return calls.add("ui.choose_task", **kwargs)

        def choose_event(self, **kwargs):
            return calls.add("ui.choose_event", **kwargs)

    class Reminders:
        def create(self, title, when, **kwargs):
            return calls.add("reminders.create", title, when, **kwargs)

        def snooze(self, reminder, until):
            return calls.add("reminders.snooze", reminder, until)

    class Notifications:
        def send(self, title, body="", actions=None):
            return calls.add("notifications.send", title, body, actions)

    class WordPress:
        def log(self, text, **kwargs):
            return calls.add("wordpress.log", text, **kwargs)

    ctx = AssistantContext(
        tasks=Tasks(),
        events=Events(),
        agenda=Agenda(),
        reminders=Reminders(),
        notifications=Notifications(),
        wordpress=WordPress(),
        ui=UI(),
        time=TimeAPI(),
        commands=object(),
        activity=object(),
        settings=object(),
        session=object(),
    )
    return ctx, calls, next_task, next_event


def setup_function():
    clear_current_context()


def teardown_function():
    clear_current_context()


def test_easy_exports_the_frozen_scratch_blocks():
    required = {
        "show",
        "tasks", "today_tasks", "overdue_tasks", "next_task", "find_task",
        "events", "today_events", "next_event", "find_event",
        "today", "agenda", "next",
        "add_task", "edit_task", "start", "pause", "resume", "complete",
        "remove", "set_due",
        "add_event", "edit_event", "remove_event",
        "parse_date", "parse_time", "parse_datetime",
        "ask_date", "ask_time", "ask_datetime",
        "choose", "choose_many", "confirm", "choose_task", "choose_event",
        "remind", "notify", "snooze", "write_log", "command",
    }
    assert required <= set(easy.__all__)


def test_easy_queries_and_actions_delegate_to_object_api_namespaces():
    ctx, calls, next_task, next_event = make_context()
    bind_current_context(ctx)

    easy.today_tasks(category="school")
    assert calls.items[-1] == (
        "tasks.list", (), {"today": True, "category": "school"}
    )

    assert easy.next_task() is next_task
    assert calls.items[-1] == ("agenda.next", (), {"kind": "task"})

    assert easy.next_event() is next_event
    assert calls.items[-1] == ("agenda.next", (), {"kind": "event"})

    easy.set_due("t1", "tomorrow")
    assert calls.items[-1] == (
        "tasks.update", (next_task,), {"due": date(2026, 8, 30)}
    )

    easy.remove_event("e1")
    assert calls.items[-1] == ("events.delete", (next_event,), {})

    easy.write_log("Finished report", project="school")
    assert calls.items[-1] == (
        "wordpress.log", ("Finished report",), {"project": "school"}
    )


def test_easy_string_actions_accept_human_task_titles_not_only_ids():
    ctx, calls, next_task, _ = make_context()
    bind_current_context(ctx)

    easy.complete("Report")

    assert ("tasks.find", ("Report",), {}) in calls.items
    assert calls.items[-1] == ("tasks.complete", (next_task,), {})


def test_easy_ambiguous_task_title_uses_promptkit_choice():
    ctx, calls, first, _ = make_context()
    second = Task(id="t2", summary="Report draft")

    def no_id(value):
        calls.add("tasks.get", value)
        raise NotFoundError(value)

    def ambiguous(query, **kwargs):
        calls.add("tasks.find", query, **kwargs)
        raise AmbiguousError(query)

    def many(**kwargs):
        calls.add("tasks.list", **kwargs)
        return [first, second]

    ctx.tasks.get = no_id
    ctx.tasks.find = ambiguous
    ctx.tasks.list = many
    bind_current_context(ctx)

    easy.complete("Report")

    assert any(item[0] == "ui.choose" for item in calls.items)
    assert calls.items[-1] == ("tasks.complete", (first,), {})


def test_task_lifecycle_rejects_event_objects_explicitly():
    ctx, calls, _, event = make_context()
    bind_current_context(ctx)

    with pytest.raises(ValidationError, match="Event has no Task work lifecycle"):
        easy.complete(event)

    assert not any(item[0] == "tasks.complete" for item in calls.items)


def test_event_mutation_rejects_task_objects_explicitly():
    ctx, calls, task, _ = make_context()
    bind_current_context(ctx)

    with pytest.raises(ValidationError, match="Task is not an Event"):
        easy.edit_event(task, location="Room 2")

    assert not any(item[0] == "events.update" for item in calls.items)


def test_easy_temporal_text_preserves_date_only_and_uses_datetime_when_needed():
    ctx, calls, task, event = make_context()
    bind_current_context(ctx)

    easy.set_due(task, "August5")
    assert calls.items[-1] == (
        "tasks.update", (task,), {"due": date(2027, 8, 5)}
    )

    easy.edit_event(event, start="tomorrow 17:00")
    assert calls.items[-1] == (
        "events.update",
        (event,),
        {"start": datetime(2026, 8, 30, 17, 0)},
    )


def test_easy_time_and_menu_blocks_reuse_public_ui_and_time_services():
    ctx, calls, _, _ = make_context()
    bind_current_context(ctx)

    assert easy.parse_date("August5", bias="future") == date(2027, 8, 5)
    assert calls.items[-1] == (
        "time.parse_date", ("August5",), {"bias": "future"}
    )

    assert easy.parse_time("12:34") == Time(12, 34)
    assert calls.items[-1][0] == "time.parse_time"

    easy.choose_many(("a", "b"), title="Pick")
    assert calls.items[-1] == (
        "ui.choose_many", ("Pick", ("a", "b")), {}
    )
