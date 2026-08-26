from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

import pytest

from caldav_assistant.api import Reminder
from caldav_assistant.api.v1.errors import NotFoundError
from caldav_assistant.internal.reminders.service import ReminderService


@dataclass
class Request:
    key: str
    title: str
    due_at: datetime | date
    description: str = ""
    actions: object = None


class FakeState:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


class FakeTemporal:
    def parse_datetime(self, text, *, bias="any"):
        assert bias == "future"
        assert text == "tomorrow 17:00"
        return datetime(2026, 8, 26, 17, 0, tzinfo=timezone.utc)


class FakeQueryService:
    def __init__(self, items):
        self.items = list(items)
        self.calls = 0

    def list(self):
        self.calls += 1
        return list(self.items)


class FakeNotifications:
    def __init__(self):
        self.calls = []
        self.fail = False

    def send(self, title, body="", actions=None):
        if self.fail:
            raise RuntimeError("notification transport down")
        self.calls.append((title, body, actions))


class FakeEngine:
    def __init__(self, requests=()):
        self.requests = list(requests)
        self.calls = []

    def evaluate(
        self,
        *,
        tasks,
        events,
        reminders,
        delivered_keys,
        now=None,
    ):
        self.calls.append(
            ("evaluate", tasks, events, reminders, set(delivered_keys), now)
        )
        return [
            request
            for request in self.requests
            if request.key not in delivered_keys
        ]


def make_service(requests=(), *, state=None):
    state = state or FakeState()
    engine = FakeEngine(requests)
    notifications = FakeNotifications()
    tasks = FakeQueryService(["task"])
    events = FakeQueryService(["event"])
    service = ReminderService(
        engine,
        notifications,
        FakeTemporal(),
        state,
        tasks,
        events,
    )
    return service, engine, notifications, state, tasks, events


def test_create_list_persists_explicit_reminder_and_uses_temporal_service():
    state = FakeState()
    service, _, _, _, _, _ = make_service(state=state)

    created = service.create(
        "  Submit report  ",
        "tomorrow 17:00",
        category="school",
    )

    assert isinstance(created, Reminder)
    assert created.title == "Submit report"
    assert created.when == datetime(
        2026, 8, 26, 17, 0, tzinfo=timezone.utc
    )
    assert created.metadata == {"category": "school"}

    reloaded, _, _, _, _, _ = make_service(state=state)
    assert reloaded.list() == [created]


def test_date_only_explicit_reminder_is_preserved_not_midnight():
    service, _, _, _, _, _ = make_service()

    created = service.create("All-day note", date(2026, 8, 30))

    assert created.when == date(2026, 8, 30)
    assert not isinstance(created.when, datetime)


def test_snooze_and_cancel_operate_on_persisted_explicit_reminders():
    service, _, _, _, _, _ = make_service()
    created = service.create(
        "Report",
        datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc),
    )

    snoozed = service.snooze(created.id, "tomorrow 17:00")
    assert snoozed.when == datetime(
        2026, 8, 26, 17, 0, tzinfo=timezone.utc
    )

    cancelled = service.cancel(created.id)
    assert cancelled.id == created.id
    assert service.list() == []

    with pytest.raises(NotFoundError):
        service.cancel(created.id)


def test_process_due_reads_task_event_services_and_sends_through_notification_service():
    now = datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc)
    due = Request(
        "task:1:due",
        "Report due",
        datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc),
        "Due at 09:00",
    )
    future = Request(
        "event:1:start",
        "English lesson",
        datetime(2026, 8, 25, 17, 0, tzinfo=timezone.utc),
    )
    service, engine, notifications, state, tasks, events = make_service(
        [future, due]
    )

    sent = service.process_due(now)

    assert sent == [due]
    assert notifications.calls == [
        ("Report due", "Due at 09:00", None)
    ]
    assert state.get(service._DELIVERED_KEY) == ["task:1:due"]
    assert tasks.calls >= 1
    assert events.calls >= 1
    assert engine.calls


def test_success_is_marked_only_after_notification_delivery_succeeds():
    now = datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc)
    request = Request(
        "task:1:due",
        "Report due",
        datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc),
    )
    service, _, notifications, state, _, _ = make_service([request])
    notifications.fail = True

    with pytest.raises(RuntimeError, match="transport down"):
        service.process_due(now)

    assert state.get(service._DELIVERED_KEY, []) == []


def test_already_delivered_request_is_not_sent_twice():
    now = datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc)
    request = Request(
        "task:1:due",
        "Report due",
        datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc),
    )
    service, _, notifications, _, _, _ = make_service([request])

    assert service.process_due(now) == [request]
    assert service.process_due(now) == [request][:0]
    assert len(notifications.calls) == 1


def test_next_due_returns_precise_datetime_and_ignores_date_only():
    now = datetime(2026, 8, 25, 8, 0, tzinfo=timezone.utc)
    date_only = Request("date-only", "All-day", date(2026, 8, 25))
    later = Request(
        "later",
        "Later",
        datetime(2026, 8, 25, 11, 0, tzinfo=timezone.utc),
    )
    sooner = Request(
        "sooner",
        "Sooner",
        datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc),
    )
    service, _, _, _, _, _ = make_service([later, date_only, sooner])

    assert service.next_due(now) == datetime(
        2026, 8, 25, 9, 0, tzinfo=timezone.utc
    )


def test_floating_datetime_is_not_compared_to_aware_clock_by_guessing_timezone():
    now = datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc)
    request = Request(
        "floating",
        "Floating",
        datetime(2026, 8, 25, 9, 0),
    )
    service, _, notifications, _, _, _ = make_service([request])

    assert service.process_due(now) == []
    assert notifications.calls == []
