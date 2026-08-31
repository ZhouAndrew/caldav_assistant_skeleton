from __future__ import annotations

from types import SimpleNamespace

import pytest

from caldav_assistant.api.v1.errors import UnavailableError
from caldav_assistant.internal.notifications.platform_adapters import (
    LinuxNotificationAdapter,
    MacOSNotificationAdapter,
    WindowsNotificationAdapter,
)


class Runner:
    def __init__(self, *, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=self.returncode,
            stderr=self.stderr,
            stdout="",
        )


def fake_which(mapping):
    return lambda name: mapping.get(name)


def test_linux_uses_notify_send_without_shell_and_requests_reminder_sound():
    runner = Runner()
    adapter = LinuxNotificationAdapter(
        runner=runner,
        which=fake_which({"notify-send": "/usr/bin/notify-send"}),
    )

    adapter.notify("Report due", "Due at 17:00")

    command, kwargs = runner.calls[0]
    assert command == [
        "/usr/bin/notify-send",
        "--app-name=CalDAV Assistant",
        "--hint=string:sound-name:alarm-clock-elapsed",
        "Report due",
        "Due at 17:00",
    ]
    assert "shell" not in kwargs
    assert kwargs["check"] is False


def test_linux_sound_setting_can_suppress_desktop_notification_sound():
    runner = Runner()
    adapter = LinuxNotificationAdapter(
        runner=runner,
        which=fake_which({"notify-send": "/usr/bin/notify-send"}),
        sound_enabled=False,
    )

    adapter.notify("Quiet reminder")

    command, _ = runner.calls[0]
    assert "--hint=boolean:suppress-sound:true" in command
    assert "--hint=string:sound-name:alarm-clock-elapsed" not in command


def test_sound_setting_provider_is_read_at_delivery_time():
    runner = Runner()
    state = {"enabled": True}
    adapter = LinuxNotificationAdapter(
        runner=runner,
        which=fake_which({"notify-send": "/usr/bin/notify-send"}),
        sound_enabled=lambda: state["enabled"],
    )

    adapter.notify("First")
    state["enabled"] = False
    adapter.notify("Second")

    first_command, _ = runner.calls[0]
    second_command, _ = runner.calls[1]
    assert "--hint=string:sound-name:alarm-clock-elapsed" in first_command
    assert "--hint=boolean:suppress-sound:true" in second_command


def test_missing_platform_command_is_unavailable():
    adapter = LinuxNotificationAdapter(
        runner=Runner(),
        which=lambda name: None,
    )

    with pytest.raises(UnavailableError):
        adapter.notify("Reminder")


def test_command_failure_is_mapped_to_stable_unavailable_error():
    adapter = LinuxNotificationAdapter(
        runner=Runner(returncode=1, stderr="DBus unavailable"),
        which=fake_which({"notify-send": "/usr/bin/notify-send"}),
    )

    with pytest.raises(UnavailableError, match="DBus unavailable"):
        adapter.notify("Reminder")


@pytest.mark.parametrize(
    "adapter_cls,mapping",
    [
        (LinuxNotificationAdapter, {"notify-send": "/usr/bin/notify-send"}),
        (MacOSNotificationAdapter, {"osascript": "/usr/bin/osascript"}),
        (WindowsNotificationAdapter, {"powershell.exe": r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"}),
    ],
)
def test_interactive_actions_are_not_silently_dropped(adapter_cls, mapping):
    runner = Runner()
    adapter = adapter_cls(
        runner=runner,
        which=fake_which(mapping),
    )

    with pytest.raises(UnavailableError, match="actions"):
        adapter.notify("Reminder", actions=[("done", "Done")])

    assert runner.calls == []


def test_macos_passes_title_and_body_as_arguments_not_embedded_user_code():
    runner = Runner()
    adapter = MacOSNotificationAdapter(
        runner=runner,
        which=fake_which({"osascript": "/usr/bin/osascript"}),
    )

    adapter.notify('Title "quoted"', 'Body; do shell script "bad"')

    command, _ = runner.calls[0]
    assert command[-2:] == ['Title "quoted"', 'Body; do shell script "bad"']
    assert 'Body; do shell script "bad"' not in command[2]
    assert 'sound name "Glass"' in command[2]


def test_macos_sound_can_be_disabled_without_changing_argument_safety():
    runner = Runner()
    adapter = MacOSNotificationAdapter(
        runner=runner,
        which=fake_which({"osascript": "/usr/bin/osascript"}),
        sound_enabled=False,
    )

    adapter.notify("Quiet", "Body")

    command, _ = runner.calls[0]
    assert 'sound name "Glass"' not in command[2]
    assert command[-2:] == ["Quiet", "Body"]


def test_windows_builds_winrt_toast_command_and_keeps_text_as_arguments():
    runner = Runner()
    exe = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    adapter = WindowsNotificationAdapter(
        runner=runner,
        which=fake_which({"powershell.exe": exe}),
    )

    adapter.notify("Report due", "Due at 17:00")

    command, _ = runner.calls[0]
    assert command[0] == exe
    assert "ToastNotificationManager" in command[-3]
    assert "ms-winsoundevent:Notification.Reminder" in command[-3]
    assert command[-2:] == ["Report due", "Due at 17:00"]


def test_windows_sound_can_be_explicitly_suppressed():
    runner = Runner()
    exe = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    adapter = WindowsNotificationAdapter(
        runner=runner,
        which=fake_which({"powershell.exe": exe}),
        sound_enabled=False,
    )

    adapter.notify("Quiet reminder")

    command, _ = runner.calls[0]
    assert "<audio silent='true'/>" in command[-3]
    assert "ms-winsoundevent:Notification.Reminder" not in command[-3]
