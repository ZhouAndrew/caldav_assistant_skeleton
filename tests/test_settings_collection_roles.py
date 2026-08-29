from types import SimpleNamespace

from caldav_assistant.internal.settings.cli import SettingsActions
from caldav_assistant.internal.settings.keys import (
    CALDAV_TASK_COLLECTION_URL,
    CALDAV_WORKLOG_COLLECTION_URL,
)


COLLECTIONS = [
    {"name": "Tasks", "url": "https://dav.example/tasks/", "components": ["VTODO"]},
    {"name": "Personal", "url": "https://dav.example/personal/", "components": ["VEVENT"]},
    {"name": "School", "url": "https://dav.example/school/", "components": ["VEVENT", "VTODO"]},
]


class Settings:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        return value

    def caldav_collections(self):
        return list(COLLECTIONS)


class UI:
    def __init__(self, role):
        self.role = role
        self.role_menu_seen = 0
        self.compatible_choices = []
        self.messages = []

    def show(self, value):
        self.messages.append(str(value))

    def choose(self, title, items):
        if title == "Collection roles":
            self.role_menu_seen += 1
            if self.role_menu_seen > 1:
                return None
            return next(item for item in items if item.startswith(self.role + ":"))
        self.compatible_choices = list(items)
        if title == "Work log collection":
            return next(item for item in items if "School" in item)
        if title == "Default task collection":
            return next(item for item in items if "Tasks" in item)
        return None


def test_worklog_role_is_chosen_by_human_name_and_only_from_vevent_collections():
    settings = Settings()
    ui = UI("Work log collection")
    actions = SettingsActions(SimpleNamespace(settings=settings, ui=ui))

    actions._collection_roles_panel()

    assert settings.values[CALDAV_WORKLOG_COLLECTION_URL] == "https://dav.example/school/"
    assert all("Tasks [VTODO]" not in item for item in ui.compatible_choices)
    assert any("Personal" in item for item in ui.compatible_choices)
    assert any("School" in item for item in ui.compatible_choices)
    assert any("✓ Work log collection: School" in message for message in ui.messages)


def test_task_role_only_offers_vtodo_capable_collections():
    settings = Settings()
    ui = UI("Default task collection")
    actions = SettingsActions(SimpleNamespace(settings=settings, ui=ui))

    actions._collection_roles_panel()

    assert settings.values[CALDAV_TASK_COLLECTION_URL] == "https://dav.example/tasks/"
    assert any("Tasks" in item for item in ui.compatible_choices)
    assert any("School" in item for item in ui.compatible_choices)
    assert all("Personal [VEVENT]" not in item for item in ui.compatible_choices)
