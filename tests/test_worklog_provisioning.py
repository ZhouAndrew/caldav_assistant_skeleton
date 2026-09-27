from __future__ import annotations

import pytest

from caldav_assistant.api.v1.errors import NotFoundError, ValidationError
from caldav_assistant.internal.settings.keys import CALDAV_WORKLOG_COLLECTION_URL
from caldav_assistant.internal.worklog import WorkLogProvisioner


class Settings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        return value


class Adapter:
    def __init__(self, collections=None):
        self.items = list(collections or [])
        self.created = []

    def collections(self):
        return [dict(item) for item in self.items]

    def create_collection(self, name, *, components=None, collection_id=None):
        self.created.append((name, list(components or ()), collection_id))
        item = {
            "id": collection_id,
            "name": name,
            "url": f"https://dav.example/{collection_id}/",
            "components": list(components or ()),
        }
        self.items.append(item)
        return dict(item)


def test_first_thunderbird_connection_creates_dedicated_history_calendar():
    settings = Settings()
    adapter = Adapter()
    service = WorkLogProvisioner(settings, adapter)

    result = service.ensure()

    assert result["created"] is True
    assert adapter.created == [
        ("CalDAV Assistant History", ["VEVENT"], "caldav-assistant-history"),
    ]
    assert settings.get(CALDAV_WORKLOG_COLLECTION_URL) == (
        "https://dav.example/caldav-assistant-history/"
    )


def test_existing_dedicated_history_calendar_is_reused_not_duplicated():
    item = {
        "id": "caldav-assistant-history",
        "name": "CalDAV Assistant History",
        "url": "https://dav.example/caldav-assistant-history/",
        "components": ["VEVENT"],
    }
    settings = Settings()
    adapter = Adapter([item])

    result = WorkLogProvisioner(settings, adapter).ensure()

    assert result["created"] is False
    assert adapter.created == []
    assert settings.get(CALDAV_WORKLOG_COLLECTION_URL) == item["url"]


def test_existing_configured_worklog_is_kept_when_it_still_exists():
    item = {
        "name": "Earlier work history",
        "url": "https://dav.example/earlier/",
        "components": ["VEVENT"],
    }
    settings = Settings({CALDAV_WORKLOG_COLLECTION_URL: item["url"]})
    adapter = Adapter([item])

    result = WorkLogProvisioner(settings, adapter).ensure()

    assert result["created"] is False
    assert result["collection"]["url"] == item["url"]
    assert adapter.created == []


def test_stale_configured_worklog_is_not_silently_replaced():
    settings = Settings(
        {CALDAV_WORKLOG_COLLECTION_URL: "https://dav.example/missing/"}
    )

    with pytest.raises(NotFoundError):
        WorkLogProvisioner(settings, Adapter()).ensure()


def test_duplicate_dedicated_calendars_are_not_guessed():
    items = [
        {
            "name": "CalDAV Assistant History",
            "url": f"https://dav.example/history-{number}/",
            "components": ["VEVENT"],
        }
        for number in (1, 2)
    ]

    with pytest.raises(ValidationError, match="More than one"):
        WorkLogProvisioner(Settings(), Adapter(items)).ensure()
