from __future__ import annotations

import pytest

from caldav_assistant.api.v1.errors import ValidationError
from caldav_assistant.internal.notifications import NotificationService


class FakeNotificationAdapter:
    def __init__(self):
        self.calls = []

    def notify(self, title, body="", actions=None):
        self.calls.append((title, body, actions))


def test_send_validates_and_delegates_to_adapter():
    adapter = FakeNotificationAdapter()
    service = NotificationService(adapter)

    result = service.send(
        "  Report due  ",
        "Due at 17:00",
        [("snooze", "Snooze")],
    )

    assert result is None
    assert adapter.calls == [
        (
            "Report due",
            "Due at 17:00",
            [("snooze", "Snooze")],
        )
    ]


def test_send_accepts_empty_body_and_none_actions():
    adapter = FakeNotificationAdapter()
    service = NotificationService(adapter)

    service.send("Reminder")

    assert adapter.calls == [("Reminder", "", None)]


@pytest.mark.parametrize("title", ["", "   ", None, 123])
def test_send_rejects_invalid_title(title):
    service = NotificationService(FakeNotificationAdapter())

    with pytest.raises(ValidationError):
        service.send(title)


def test_send_rejects_non_text_body():
    service = NotificationService(FakeNotificationAdapter())

    with pytest.raises(ValidationError):
        service.send("Reminder", body=123)


def test_send_rejects_unstructured_actions_container():
    service = NotificationService(FakeNotificationAdapter())

    with pytest.raises(ValidationError):
        service.send("Reminder", actions={"done": "Done"})


def test_master_gate_blocks_adapter_and_can_change_live():
    adapter = FakeNotificationAdapter()
    state = {"enabled": False}
    service = NotificationService(
        adapter,
        enabled=lambda: state["enabled"],
    )

    service.send("Blocked", "must not reach adapter")
    assert service.is_enabled() is False
    assert adapter.calls == []

    state["enabled"] = True
    service.send("Allowed", "now enabled")
    assert service.is_enabled() is True
    assert adapter.calls == [("Allowed", "now enabled", None)]

    state["enabled"] = False
    service.send("Blocked again")
    assert adapter.calls == [("Allowed", "now enabled", None)]


def test_disabled_master_gate_still_validates_public_inputs():
    service = NotificationService(
        FakeNotificationAdapter(),
        enabled=False,
    )

    with pytest.raises(ValidationError):
        service.send("")
