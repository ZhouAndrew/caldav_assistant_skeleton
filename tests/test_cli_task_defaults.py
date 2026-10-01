from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from caldav_assistant.api import Task
from caldav_assistant.internal.cli.crud import CrudActions
from caldav_assistant.internal.settings.cli import SettingsActions
from caldav_assistant.internal.settings.keys import (
    CALDAV_TASK_COLLECTION_URL,
    TASK_DEFAULT_VIEW,
)


class Tasks:
    def __init__(self):
        today = datetime.now().astimezone().date()
        self.items = [
            Task(id="open", summary="Open"),
            Task(id="today", summary="Today", due=today),
            Task(id="late", summary="Late", due=today - timedelta(days=1)),
            Task(id="done", summary="Done", status="COMPLETED", completed=True),
            Task(id="cancelled", summary="Cancelled", status="CANCELLED"),
        ]
        self.calls = []

    def list(self, **filters):
        self.calls.append(dict(filters))
        items = list(self.items)
        if filters.pop("actionable", False):
            items = [
                item
                for item in items
                if not item.completed and item.status not in {"COMPLETED", "CANCELLED"}
            ]
        return items


class Settings:
    def __init__(self, *, view="incomplete", collections=()):
        self.values = {TASK_DEFAULT_VIEW: view}
        self.collections = list(collections)

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        if value is None:
            self.values.pop(key, None)
            return None
        self.values[key] = value
        return value

    def caldav_collections(self):
        return list(self.collections)


class UI:
    def __init__(self, selections=()):
        self.shown = []
        self.selections = list(selections)
        self.choices = []

    def show(self, value):
        self.shown.append(str(value))

    def choose(self, title, items, **kwargs):
        labels = list(items)
        self.choices.append((title, labels))
        if not self.selections:
            return None
        wanted = self.selections.pop(0)
        assert wanted in labels
        return wanted


def context(*, view="incomplete", collections=(), selections=()):
    tasks = Tasks()
    settings = Settings(view=view, collections=collections)
    ui = UI(selections)
    session = SimpleNamespace(last_items=[], current_selection=None)
    return (
        SimpleNamespace(tasks=tasks, settings=settings, ui=ui, session=session, commands=None),
        tasks,
        settings,
        ui,
        session,
    )


def test_tasks_defaults_to_incomplete_without_changing_object_api_list_default():
    ctx, tasks, _, ui, session = context()

    CrudActions(ctx).tasks()

    assert [item.id for item in session.last_items] == ["open", "today", "late"]
    assert tasks.calls[0] == {"actionable": True}
    assert any("Tasks · Incomplete · 3" in line for line in ui.shown)


def test_tasks_explicit_history_views_remain_available():
    ctx, _, _, ui, session = context()

    actions = CrudActions(ctx)
    actions.tasks("completed")
    assert [item.id for item in session.last_items] == ["done"]

    actions.tasks("all")
    assert [item.id for item in session.last_items] == [
        "open",
        "today",
        "late",
        "done",
        "cancelled",
    ]
    assert any("tasks incomplete" in line for line in ui.shown)


def test_tasks_today_and_overdue_are_small_cli_views_over_actionable_tasks():
    ctx, _, _, _, session = context()
    actions = CrudActions(ctx)

    actions.tasks("today")
    assert [item.id for item in session.last_items] == ["today"]

    actions.tasks("overdue")
    assert [item.id for item in session.last_items] == ["late"]


def test_saved_default_task_view_is_used_by_bare_tasks_command():
    ctx, _, _, _, session = context(view="completed")

    CrudActions(ctx).tasks()

    assert [item.id for item in session.last_items] == ["done"]


def test_single_vtodo_collection_is_selected_automatically_on_first_create():
    collections = [
        {"name": "Tasks", "url": "https://dav.example/tasks/", "components": ["VTODO"]},
        {"name": "Events", "url": "https://dav.example/events/", "components": ["VEVENT"]},
    ]
    ctx, _, settings, ui, _ = context(collections=collections)

    assert CrudActions(ctx)._ensure_default_task_collection() is True
    assert settings.get(CALDAV_TASK_COLLECTION_URL) == "https://dav.example/tasks/"
    assert ui.choices == []
    assert any("only compatible VTODO collection" in line for line in ui.shown)


def test_multiple_vtodo_collections_prompt_once_then_persist_choice():
    collections = [
        {"name": "Tasks", "url": "https://dav.example/tasks/", "components": ["VTODO"]},
        {"name": "School", "url": "https://dav.example/school/", "components": ["VTODO", "VEVENT"]},
    ]
    ctx, _, settings, ui, _ = context(
        collections=collections,
        selections=("School", "Continue"),
    )
    actions = CrudActions(ctx)

    assert actions._ensure_default_task_collection() is True
    assert settings.get(CALDAV_TASK_COLLECTION_URL) == "https://dav.example/school/"
    assert ui.choices[0][0] == "Where should new Tasks be saved by default?"

    ui.choices.clear()
    assert actions._ensure_default_task_collection() is True
    assert ui.choices == []


def test_first_collection_choice_can_be_undone_before_task_creation():
    collections = [
        {"name": "Tasks", "url": "https://dav.example/tasks/", "components": ["VTODO"]},
        {"name": "School", "url": "https://dav.example/school/", "components": ["VTODO"]},
    ]
    ctx, _, settings, _, _ = context(
        collections=collections,
        selections=("Tasks", "Undo"),
    )

    assert CrudActions(ctx)._ensure_default_task_collection() is False
    assert settings.get(CALDAV_TASK_COLLECTION_URL) is None


def test_tasks_settings_panel_reuses_existing_default_collection_setting():
    collections = [
        {"name": "Tasks", "url": "https://dav.example/tasks/", "components": ["VTODO"]},
        {"name": "Events", "url": "https://dav.example/events/", "components": ["VEVENT"]},
    ]
    ctx, _, settings, ui, _ = context(
        collections=collections,
        selections=(
            "Default task collection: Not configured",
            "1. Tasks [VTODO]",
            "Continue",
        ),
    )

    SettingsActions(ctx)._tasks_panel()

    assert settings.get(CALDAV_TASK_COLLECTION_URL) == "https://dav.example/tasks/"
    assert ui.choices[0][0] == "Tasks"
    assert "Default task view: incomplete" in ui.choices[0][1]
    assert "Default task collection: Not configured" in ui.choices[0][1]
