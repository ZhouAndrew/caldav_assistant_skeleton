from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from caldav_assistant.api import Event, Reminder, Task
from caldav_assistant.internal.reminders import (
    NotificationRequest,
    ReminderEngine,
)


NOW = datetime(
    2026,
    8,
    25,
    9,
    0,
    tzinfo=timezone.utc,
)


def test_due_task_and_event_start_become_requests_in_temporal_order():
    engine = ReminderEngine()

    task = Task(
        id="task-1",
        summary="Submit report",
        due=datetime(
            2026,
            8,
            25,
            11,
            0,
            tzinfo=timezone.utc,
        ),
    )
    event = Event(
        id="event-1",
        summary="English lesson",
        start=datetime(
            2026,
            8,
            25,
            10,
            0,
            tzinfo=timezone.utc,
        ),
    )

    requests = engine.evaluate(
        [task],
        [event],
        now=NOW,
    )

    assert [request.source for request in requests] == [
        "event_start",
        "task_due",
    ]
    assert requests[0].object_id == "event-1"
    assert requests[1].object_id == "task-1"


def test_completed_and_cancelled_tasks_do_not_generate_reminders():
    engine = ReminderEngine()
    due = datetime(
        2026,
        8,
        25,
        10,
        0,
        tzinfo=timezone.utc,
    )

    completed = Task(
        id="done",
        summary="Done",
        due=due,
        status="COMPLETED",
        completed=True,
    )
    cancelled = Task(
        id="cancelled",
        summary="Cancelled",
        due=due,
        status="CANCELLED",
    )

    assert engine.evaluate(
        [completed, cancelled],
        now=NOW,
    ) == []


def test_date_only_values_are_not_silently_converted_to_midnight():
    engine = ReminderEngine()

    task = Task(
        id="task-date",
        summary="Date-only task",
        due=date(2026, 8, 25),
    )
    event = Event(
        id="event-date",
        summary="All-day event",
        start=date(2026, 8, 25),
        end=date(2026, 8, 26),
    )

    assert engine.evaluate(
        [task],
        [event],
        now=NOW,
    ) == []


def test_explicit_reminder_and_snooze_are_supported():
    engine = ReminderEngine()

    ordinary = Reminder(
        id="r1",
        title="Take notes",
        when=datetime(
            2026,
            8,
            25,
            9,
            30,
            tzinfo=timezone.utc,
        ),
    )
    snoozed = Reminder(
        id="r2",
        title="Continue work",
        when=datetime(
            2026,
            8,
            25,
            10,
            30,
            tzinfo=timezone.utc,
        ),
        metadata={
            "snoozed": True,
            "body": "Snoozed earlier",
        },
    )

    requests = engine.evaluate(
        reminders=[snoozed, ordinary],
        now=NOW,
    )

    assert requests[0].source == "reminder"
    assert requests[0].object_id == "r1"
    assert requests[1].source == "snooze"
    assert requests[1].body == "Snoozed earlier"


def test_relative_valarm_uses_event_start():
    engine = ReminderEngine()

    event = Event(
        id="lesson",
        summary="English lesson",
        start=datetime(
            2026,
            8,
            25,
            17,
            0,
            tzinfo=timezone.utc,
        ),
        raw={
            "alarms": [
                {
                    "ACTION": "DISPLAY",
                    "TRIGGER": timedelta(minutes=-15),
                    "DESCRIPTION": "Lesson in 15 minutes",
                }
            ]
        },
    )

    requests = engine.evaluate(
        events=[event],
        now=NOW,
    )

    assert requests[0].source == "valarm"
    assert requests[0].when == datetime(
        2026,
        8,
        25,
        16,
        45,
        tzinfo=timezone.utc,
    )
    assert requests[0].body == "Lesson in 15 minutes"

    # The ordinary event-start request still exists because the VALARM is at
    # a different instant.
    assert requests[1].source == "event_start"


def test_related_end_valarm_uses_event_end_and_task_due():
    engine = ReminderEngine()

    event = Event(
        id="meeting",
        summary="Meeting",
        start=datetime(
            2026,
            8,
            25,
            10,
            0,
            tzinfo=timezone.utc,
        ),
        end=datetime(
            2026,
            8,
            25,
            11,
            0,
            tzinfo=timezone.utc,
        ),
        raw={
            "alarms": [
                {
                    "ACTION": "DISPLAY",
                    "TRIGGER": timedelta(minutes=-5),
                    "RELATED": "END",
                }
            ]
        },
    )

    task = Task(
        id="report",
        summary="Report",
        due=datetime(
            2026,
            8,
            25,
            12,
            0,
            tzinfo=timezone.utc,
        ),
        raw={
            "alarms": [
                {
                    "ACTION": "DISPLAY",
                    "TRIGGER": timedelta(minutes=-10),
                    "RELATED": "END",
                }
            ]
        },
    )

    requests = engine.evaluate(
        [task],
        [event],
        now=NOW,
    )

    alarm_times = {
        request.object_id: request.when
        for request in requests
        if request.source == "valarm"
    }

    assert alarm_times["meeting"] == datetime(
        2026,
        8,
        25,
        10,
        55,
        tzinfo=timezone.utc,
    )
    assert alarm_times["report"] == datetime(
        2026,
        8,
        25,
        11,
        50,
        tzinfo=timezone.utc,
    )


def test_absolute_valarm_at_due_time_does_not_duplicate_default_due():
    engine = ReminderEngine()

    due = datetime(
        2026,
        8,
        25,
        12,
        0,
        tzinfo=timezone.utc,
    )

    task = Task(
        id="report",
        summary="Report",
        due=due,
        raw={
            "alarms": [
                {
                    "ACTION": "DISPLAY",
                    "TRIGGER": due,
                }
            ]
        },
    )

    requests = engine.evaluate(
        [task],
        now=NOW,
    )

    assert len(requests) == 1
    assert requests[0].source == "valarm"
    assert requests[0].when == due


def test_non_display_valarm_is_not_reinterpreted_as_system_notification():
    engine = ReminderEngine()

    event = Event(
        id="audio",
        summary="Audio alarm",
        start=datetime(
            2026,
            8,
            25,
            12,
            0,
            tzinfo=timezone.utc,
        ),
        raw={
            "alarms": [
                {
                    "ACTION": "AUDIO",
                    "TRIGGER": timedelta(minutes=-5),
                }
            ]
        },
    )

    requests = engine.evaluate(
        events=[event],
        now=NOW,
    )

    assert len(requests) == 1
    assert requests[0].source == "event_start"


def test_valarm_repeat_and_duration_are_expanded():
    engine = ReminderEngine()

    event = Event(
        id="repeat",
        summary="Repeated alarm",
        start=datetime(
            2026,
            8,
            25,
            10,
            0,
            tzinfo=timezone.utc,
        ),
        raw={
            "alarms": [
                {
                    "ACTION": "DISPLAY",
                    "TRIGGER": timedelta(minutes=-30),
                    "REPEAT": 2,
                    "DURATION": timedelta(minutes=10),
                }
            ]
        },
    )

    requests = engine.evaluate(
        events=[event],
        now=NOW,
    )

    alarm_times = [
        request.when
        for request in requests
        if request.source == "valarm"
    ]

    assert alarm_times == [
        datetime(
            2026,
            8,
            25,
            9,
            30,
            tzinfo=timezone.utc,
        ),
        datetime(
            2026,
            8,
            25,
            9,
            40,
            tzinfo=timezone.utc,
        ),
        datetime(
            2026,
            8,
            25,
            9,
            50,
            tzinfo=timezone.utc,
        ),
    ]


def test_user_rule_can_add_notification_request():
    engine = ReminderEngine()

    task = Task(
        id="priority",
        summary="Priority task",
    )

    def rule(item, now):
        if not isinstance(item, Task):
            return None

        return NotificationRequest(
            key="",
            when=now + timedelta(minutes=20),
            title=item.summary,
            body="Custom rule",
        )

    requests = engine.evaluate(
        [task],
        now=NOW,
        rules=[rule],
    )

    assert len(requests) == 1
    assert requests[0].source == "rule"
    assert requests[0].object_id == "priority"
    assert requests[0].body == "Custom rule"
    assert requests[0].key


def test_due_and_next_due_respect_delivered_keys():
    engine = ReminderEngine()

    past = NotificationRequest(
        key="past",
        when=NOW - timedelta(minutes=5),
        title="Past",
    )
    future = NotificationRequest(
        key="future",
        when=NOW + timedelta(minutes=15),
        title="Future",
    )

    requests = [future, past]

    assert engine.due(
        requests,
        now=NOW,
    ) == [past]

    assert engine.due(
        requests,
        now=NOW,
        delivered={"past"},
    ) == []

    assert engine.next_due(
        requests,
        now=NOW,
    ) == past.when

    assert engine.next_due(
        requests,
        now=NOW,
        delivered={"past"},
    ) == future.when

    assert engine.next_due(
        requests,
        now=NOW,
        delivered={"past", "future"},
    ) is None
