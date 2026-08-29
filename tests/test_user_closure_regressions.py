from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import caldav_assistant
from caldav_assistant.api import ActionResult, Activity, Event, Task
from caldav_assistant.api.v1.errors import ValidationError
from caldav_assistant.internal.activity import ActivityService
from caldav_assistant.internal.bootstrap import (
    _ensure_default_extension_settings,
    build_cli_application,
)
from caldav_assistant.internal.cli.crud import CrudActions, register_crud_cli_commands
from caldav_assistant.internal.cli.worklog_setup import WorkLogSetup
from caldav_assistant.internal.commands import CommandRegistry, CommandService
from caldav_assistant.internal.extensions import ExtensionManager, HookRegistry
from caldav_assistant.internal.session import CalDAVSessionService
from caldav_assistant.internal.settings.cli import SettingsActions
from caldav_assistant.internal.settings.keys import EXTENSIONS_ENABLED
from caldav_assistant.internal.settings.service import SettingsService
from caldav_assistant.internal.tasks.work_service import CalDAVWorkTaskService
from caldav_assistant.internal.worklog import WorkLogService


class MemoryActivityRepo:
    def __init__(self):
        self.items: list[Activity] = []

    def record(self, timestamp, action, object_id, metadata):
        self.items.append(
            Activity(
                timestamp=timestamp,
                action=action,
                object_id=object_id,
                metadata=dict(metadata),
            )
        )

    def between(self, start, end):
        return [item for item in self.items if start <= item.timestamp < end]

    def for_object(self, object_id):
        return [item for item in self.items if item.object_id == object_id]


class MemoryAdapter:
    def __init__(self):
        self.tasks: dict[str, Task] = {}
        self.events: list[Event] = []

    def list_tasks(self, **filters):
        items = list(self.tasks.values())
        status = filters.get("status")
        if status is not None:
            items = [item for item in items if item.status == status]
        return items

    def get_task(self, task_id):
        if task_id not in self.tasks:
            raise KeyError(task_id)
        return self.tasks[task_id]

    def create_task(self, task):
        task.id = task.id or f"t{len(self.tasks) + 1}"
        self.tasks[task.id] = task
        return task

    def update_task(self, task_id, changes):
        task = self.get_task(task_id)
        for key, value in changes.items():
            setattr(task, key, value)
        return task

    def delete_task(self, task_id):
        self.tasks.pop(task_id)

    def list_events(self, **filters):
        items = list(self.events)
        category = filters.get("category")
        if category is not None:
            items = [item for item in items if category in set(item.categories or ())]
        return items

    def get_event(self, event_id):
        for event in self.events:
            if event.id == event_id:
                return event
        raise KeyError(event_id)

    def create_event(self, event):
        event.id = event.id or f"e{len(self.events) + 1}"
        self.events.append(event)
        return event

    def update_event(self, event_id, changes):
        event = self.get_event(event_id)
        for key, value in changes.items():
            setattr(event, key, value)
        return event

    def delete_event(self, event_id):
        self.events = [item for item in self.events if item.id != event_id]


def make_work_stack(work_collection: str | None):
    adapter = MemoryAdapter()
    repo = MemoryActivityRepo()
    activity = ActivityService(repo)
    worklog = WorkLogService(adapter, lambda: work_collection)
    session = CalDAVSessionService(worklog, activity=activity)
    tasks = CalDAVWorkTaskService(
        adapter,
        activity,
        None,
        session,
        worklog=worklog,
    )
    session.bind_tasks(tasks)
    return adapter, repo, worklog, session, tasks


def test_task_lifecycle_works_without_vevent_collection_using_activity_fallback():
    adapter, repo, _, session, tasks = make_work_stack(None)
    adapter.tasks["t1"] = Task(id="t1", summary="Write report")

    assert tasks.start("t1").success is True
    assert adapter.events == []
    assert session.current_task_id() == "t1"

    assert tasks.pause("t1").success is True
    assert session.current_task_id() is None
    assert session.paused_task_ids() == ("t1",)

    assert tasks.resume("t1").success is True
    assert session.current_task_id() == "t1"

    assert tasks.complete("t1").success is True
    assert session.current_task_id() is None
    assert session.paused_task_ids() == ()
    assert adapter.tasks["t1"].status == "COMPLETED"

    assert [item.action for item in repo.items] == [
        "task_started",
        "task_paused",
        "task_resumed",
        "task_completed",
    ]


def test_caldav_work_segments_and_activity_journal_are_both_recorded_when_configured():
    adapter, repo, worklog, session, tasks = make_work_stack("caldav://work/")
    adapter.tasks["t1"] = Task(id="t1", summary="Study")

    tasks.start("t1")
    assert worklog.current_task_id() == "t1"
    tasks.pause("t1")
    assert session.paused_task_ids() == ("t1",)

    # A standard IN-PROCESS Task created by some other client is not an Assistant
    # pause unless there is explicit Assistant Work/Activity history for it.
    adapter.tasks["external"] = Task(
        id="external",
        summary="External client task",
        status="IN-PROCESS",
    )
    assert session.paused_task_ids() == ("t1",)

    tasks.resume("t1")
    tasks.complete("t1")

    assert len(adapter.events) == 2
    assert all(event.end is not None for event in adapter.events)
    assert [item.action for item in repo.items] == [
        "task_started",
        "task_paused",
        "task_resumed",
        "task_completed",
    ]


def test_worklog_setup_does_not_block_start_when_no_vevent_collection_exists():
    class Settings:
        def get(self, key, default=None):
            return default

        def set(self, key, value):
            raise AssertionError("no work-log role should be written")

        def caldav_collections(self):
            return [
                {
                    "name": "Tasks",
                    "url": "https://dav.example/tasks/",
                    "components": ["VTODO"],
                }
            ]

    class UI:
        def __init__(self):
            self.messages = []

        def show(self, value):
            self.messages.append(str(value))

        def choose(self, *args, **kwargs):
            raise AssertionError("there is no VEVENT choice to ask for")

    ui = UI()
    ctx = SimpleNamespace(settings=Settings(), ui=ui)

    assert WorkLogSetup(ctx).ensure() is True
    assert any("Activity Journal" in message for message in ui.messages)
    assert any("Starting the Task anyway" in message for message in ui.messages)


def test_build_cli_application_keeps_complete_alias_and_help_metadata():
    app = build_cli_application()

    done = app.commands.resolve("done")
    via_alias = app.commands.resolve("complete")

    assert via_alias.name == "done"
    assert done.description == "Mark a task complete."
    assert "complete" in done.aliases
    assert app.commands.resolve("today").description


class CrudUI:
    def __init__(self, *, choices=(), texts=(), dates=(), datetimes=(), confirms=()):
        self.choices = list(choices)
        self.texts = list(texts)
        self.dates = list(dates)
        self.datetimes = list(datetimes)
        self.confirms = list(confirms)
        self.messages = []

    def show(self, value):
        self.messages.append(str(value))

    def choose(self, title, items, **kwargs):
        if not self.choices:
            raise AssertionError(f"unexpected choice prompt: {title}")
        return self.choices.pop(0)

    def choose_task(self, **kwargs):
        raise AssertionError("test passes task names explicitly")

    def ask_text(self, prompt, **kwargs):
        if not self.texts:
            raise AssertionError(f"unexpected text prompt: {prompt}")
        return self.texts.pop(0)

    def ask_date(self, prompt, **kwargs):
        if not self.dates:
            raise AssertionError(f"unexpected date prompt: {prompt}")
        return self.dates.pop(0)

    def ask_datetime(self, prompt, **kwargs):
        if not self.datetimes:
            raise AssertionError(f"unexpected datetime prompt: {prompt}")
        return self.datetimes.pop(0)

    def confirm(self, prompt, **kwargs):
        if not self.confirms:
            raise AssertionError(f"unexpected confirmation prompt: {prompt}")
        return self.confirms.pop(0)


class CrudTasks:
    def __init__(self):
        self.items = [Task(id="t1", summary="Existing task")]
        self.created = []
        self.deleted = []

    def list(self, **filters):
        return list(self.items)

    def find(self, query, **filters):
        for item in self.items:
            if item.summary.casefold() == query.casefold():
                return item
        raise AssertionError(query)

    def create(self, summary, **fields):
        self.created.append((summary, fields))
        return ActionResult(True, affected=Task(id="new-task", summary=summary, **fields))

    def delete(self, task):
        self.deleted.append(task.id)
        return ActionResult(True, affected=task)


class CrudEvents:
    def __init__(self):
        self.items = [
            Event(id="e1", summary="Meeting"),
            Event(
                id="work1",
                summary="Work — Existing task",
                categories=["caldav-assistant-work"],
            ),
        ]
        self.created = []
        self.updated = []
        self.deleted = []

    def list(self, **filters):
        return list(self.items)

    def create(self, summary, **fields):
        self.created.append((summary, fields))
        return ActionResult(True, affected=Event(id="new-event", summary=summary, **fields))

    def update(self, event, **changes):
        self.updated.append((event.id, changes))
        return ActionResult(True, affected=event)

    def delete(self, event):
        self.deleted.append(event.id)
        return ActionResult(True, affected=event)


class CrudSession:
    def __init__(self, current=None):
        self.current = current

    def current_task_id(self):
        return self.current


def test_guided_add_covers_task_and_event_and_events_hide_internal_work_segments():
    tasks = CrudTasks()
    events = CrudEvents()

    task_ui = CrudUI(
        choices=["Due date", "Create"],
        dates=[date(2026, 9, 1)],
    )
    task_actions = CrudActions(
        SimpleNamespace(tasks=tasks, events=events, ui=task_ui, session=CrudSession())
    )
    task_actions.add("task", "Write", "report")
    assert tasks.created == [
        ("Write report", {"due": date(2026, 9, 1)})
    ]

    event_start = datetime(2026, 9, 2, 14, 30)
    event_ui = CrudUI(
        choices=["Date/time", "Location", "Create"],
        texts=["Room 2"],
        datetimes=[event_start],
    )
    event_actions = CrudActions(
        SimpleNamespace(tasks=tasks, events=events, ui=event_ui, session=CrudSession())
    )
    event_actions.add("event", "Team", "meeting")
    assert events.created == [
        ("Team meeting", {"start": event_start, "location": "Room 2"})
    ]

    list_ui = CrudUI()
    list_actions = CrudActions(
        SimpleNamespace(tasks=tasks, events=events, ui=list_ui, session=CrudSession())
    )
    list_actions.events()
    output = "\n".join(list_ui.messages)
    assert "Meeting" in output
    assert "Work — Existing task" not in output


def test_event_edit_ignores_internal_work_event_and_active_task_delete_is_rejected():
    tasks = CrudTasks()
    events = CrudEvents()
    edit_ui = CrudUI(choices=["Location"], texts=["Library"])
    actions = CrudActions(
        SimpleNamespace(tasks=tasks, events=events, ui=edit_ui, session=CrudSession())
    )

    actions.edit_event("Meeting")
    assert events.updated == [("e1", {"location": "Library"})]

    delete_ui = CrudUI(confirms=[True])
    delete_actions = CrudActions(
        SimpleNamespace(
            tasks=tasks,
            events=events,
            ui=delete_ui,
            session=CrudSession(current="t1"),
        )
    )
    with pytest.raises(ValidationError, match="cannot be deleted while work is active"):
        delete_actions.remove("task", "Existing task")
    assert tasks.deleted == []


def test_crud_command_registration_is_protected_and_idempotent():
    commands = CommandService(CommandRegistry())
    ctx = SimpleNamespace(tasks=CrudTasks(), events=CrudEvents(), ui=CrudUI(), session=CrudSession())

    register_crud_cli_commands(commands, ctx)
    register_crud_cli_commands(commands, ctx)

    assert commands.resolve("new").name == "add"
    assert commands.resolve("delete").name == "remove"
    assert commands.resolve("edit-event").protected is True


class DictRepo:
    def __init__(self, initial=None):
        self.values = dict(initial or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


class MessageUI:
    def __init__(self):
        self.messages = []

    def show(self, value):
        self.messages.append(str(value))


def test_default_bundled_extension_state_is_materialized_for_settings_display():
    repo = DictRepo()
    settings = SettingsService(repo)
    _ensure_default_extension_settings(settings)

    assert settings.get(EXTENSIONS_ENABLED) == {
        "software_intro": True,
        "wordpress_work_session_log": True,
    }

    ui = MessageUI()
    SettingsActions(SimpleNamespace(settings=settings, ui=ui))._extensions_panel()
    output = "\n".join(ui.messages)
    assert "software_intro" in output
    assert "wordpress_work_session_log" in output

    # Explicit user disable remains authoritative; newly missing packaged defaults
    # are filled without overwriting that explicit choice.
    settings.set(EXTENSIONS_ENABLED, {"software_intro": False})
    _ensure_default_extension_settings(settings)
    assert settings.get(EXTENSIONS_ENABLED) == {
        "software_intro": False,
        "wordpress_work_session_log": True,
    }


def test_bundled_intro_guides_first_run_before_showing_normal_commands(tmp_path):
    class IntroSettings:
        def __init__(self, values):
            self.values = dict(values)

        def get(self, key, default=None):
            return self.values.get(key, default)

        def set(self, key, value):
            self.values[key] = value
            return value

    commands = CommandService(CommandRegistry())
    hooks = HookRegistry()
    manager_settings = IntroSettings({})
    bundled_root = Path(caldav_assistant.__file__).resolve().parent / "builtin_extensions"
    manager = ExtensionManager(
        commands,
        hooks,
        manager_settings,
        root=tmp_path / "extensions",
        bundled_root=bundled_root,
        default_enabled=("software_intro",),
    )
    loaded = manager.load_enabled()
    assert loaded and loaded[0].status == "loaded"

    ui = MessageUI()
    first_run = SimpleNamespace(
        settings=IntroSettings({"ui.locale": "en"}),
        ui=ui,
    )
    hooks.emit("cli.repl.started", first_run)
    text = "\n".join(ui.messages)
    assert "First-run setup is not complete yet" in text
    assert "settings" in text
    assert "Collection roles" in text

    ui.messages.clear()
    ready = SimpleNamespace(
        settings=IntroSettings(
            {
                "ui.locale": "en",
                "caldav.base_url": "https://dav.example/",
                "caldav.task_collection_url": "https://dav.example/tasks/",
            }
        ),
        ui=ui,
    )
    hooks.emit("cli.repl.started", ready)
    text = "\n".join(ui.messages)
    assert "add" in text
    assert "edit-event" in text
    assert "First-run setup is not complete yet" not in text
