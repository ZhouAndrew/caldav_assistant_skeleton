from __future__ import annotations

from types import SimpleNamespace

from caldav_assistant.internal.cli.worklog_setup import WorkLogSetup
from caldav_assistant.internal.settings.keys import CALDAV_WORKLOG_COLLECTION_URL


class Settings:
    def __init__(self, collections):
        self.values = {}
        self._collections = collections
        self.writes = []

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        self.writes.append((key, value))
        return value

    def caldav_collections(self):
        return list(self._collections)


class UI:
    def __init__(self, answer=None):
        self.answer = answer
        self.choices = []
        self.shown = []

    def show(self, value):
        self.shown.append(str(value))

    def choose(self, title, items, **kwargs):
        self.choices.append((title, tuple(items)))
        return self.answer


def app(collections, answer=None):
    settings = Settings(collections)
    ui = UI(answer)
    return SimpleNamespace(ctx=SimpleNamespace(settings=settings, ui=ui)), settings, ui


def test_single_compatible_collection_is_selected_without_prompt():
    collection = {
        "name": "Personal",
        "url": "http://example.test/personal/",
        "components": ["VTODO", "VEVENT"],
    }
    wrapper, settings, ui = app([collection])

    assert WorkLogSetup(wrapper.ctx).ensure() is True
    assert ui.choices == []
    assert settings.values[CALDAV_WORKLOG_COLLECTION_URL] == collection["url"]
    assert any("only compatible calendar was selected automatically" in text for text in ui.shown)


def test_multiple_compatible_collections_remain_a_real_user_choice():
    first = {
        "name": "Personal",
        "url": "http://example.test/personal/",
        "components": ["VEVENT"],
    }
    second = {
        "name": "School",
        "url": "http://example.test/school/",
        "components": ["VEVENT", "VTODO"],
    }
    wrapper, settings, ui = app([first, second], answer="School [VEVENT, VTODO]")

    assert WorkLogSetup(wrapper.ctx).ensure() is True
    assert len(ui.choices) == 1
    assert ui.choices[0][0] == "Work log collection"
    assert settings.values[CALDAV_WORKLOG_COLLECTION_URL] == second["url"]


def test_no_compatible_collection_uses_activity_fallback_without_prompt():
    wrapper, settings, ui = app(
        [{"name": "Tasks only", "url": "http://example.test/tasks/", "components": ["VTODO"]}]
    )

    assert WorkLogSetup(wrapper.ctx).ensure() is True
    assert ui.choices == []
    assert CALDAV_WORKLOG_COLLECTION_URL not in settings.values
    assert any("Activity Journal" in text for text in ui.shown)
