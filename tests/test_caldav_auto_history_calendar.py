from __future__ import annotations

from caldav_assistant.internal.caldav.setup import CalDAVSetupService
from caldav_assistant.internal.settings.keys import CALDAV_WORKLOG_COLLECTION_URL


class Settings:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        return value

    def delete(self, key):
        self.values.pop(key, None)


class Discovery:
    def resolve(self):
        raise RuntimeError("unused")


class Adapter:
    def __init__(self):
        self.calls = 0

    def ensure_calendar(self, name, *, components):
        self.calls += 1
        assert name == "CalDAV Assistant History"
        assert components == ("VEVENT",)
        return {
            "name": name,
            "url": "http://example.test/history/",
            "components": ["VEVENT"],
        }


def test_history_calendar_is_created_once_then_reused_from_settings():
    settings = Settings()
    adapter = Adapter()
    setup = CalDAVSetupService(settings, Discovery(), adapter)

    first = setup.ensure_worklog_collection()
    second = setup.ensure_worklog_collection()

    assert first["url"] == "http://example.test/history/"
    assert first["created"] is True
    assert second == {
        "url": "http://example.test/history/",
        "created": False,
        "configured": True,
    }
    assert adapter.calls == 1
    assert settings.get(CALDAV_WORKLOG_COLLECTION_URL) == "http://example.test/history/"
