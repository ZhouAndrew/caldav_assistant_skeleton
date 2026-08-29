from datetime import date, datetime

from caldav_assistant.internal.reminders.service import ReminderService
from caldav_assistant.internal.temporal.parser import TemporalParser
from caldav_assistant.internal.temporal.service import TemporalService


class State:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


def make_service():
    temporal = TemporalService(
        TemporalParser(now=datetime(2026, 8, 29, 9, 0))
    )
    return ReminderService(
        object(),
        object(),
        temporal,
        State(),
        object(),
        object(),
    )


def test_date_only_reminder_text_stays_date_only():
    created = make_service().create("Submit report", "August5")

    assert created.when == date(2027, 8, 5)
    assert not isinstance(created.when, datetime)


def test_reminder_text_with_explicit_time_stays_datetime():
    created = make_service().create("Submit report", "tomorrow 17:00")

    assert created.when == datetime(2026, 8, 30, 17, 0)
