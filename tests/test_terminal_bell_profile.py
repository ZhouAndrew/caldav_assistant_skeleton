from io import StringIO

from caldav_assistant.internal.clients.terminal import (
    StdConsoleIO,
    TerminalBellProfile,
)


def test_one_logical_bell_becomes_three_spaced_terminal_rings():
    output = StringIO()
    sleep_calls = []
    profile = TerminalBellProfile(
        enabled=lambda: True,
        repeat_count=lambda: 3,
        interval_ms=lambda: 400,
    )
    console = StdConsoleIO(
        stdout=output,
        terminal_bell_profile=profile,
        sleep_fn=sleep_calls.append,
    )

    console.stdout.write("\a")

    assert output.getvalue() == "\a\a\a"
    assert sleep_calls == [0.4, 0.4]


def test_terminal_bell_can_be_disabled_without_hiding_other_output():
    output = StringIO()
    profile = TerminalBellProfile(
        enabled=lambda: False,
        repeat_count=lambda: 3,
        interval_ms=lambda: 400,
    )
    console = StdConsoleIO(
        stdout=output,
        terminal_bell_profile=profile,
        sleep_fn=lambda seconds: None,
    )

    console.stdout.write("before\aafter")

    assert output.getvalue() == "beforeafter"


def test_terminal_bell_profile_is_read_live_for_each_reminder():
    output = StringIO()
    settings = {
        "enabled": True,
        "repeat_count": 2,
        "interval_ms": 100,
    }
    profile = TerminalBellProfile(
        enabled=lambda: settings["enabled"],
        repeat_count=lambda: settings["repeat_count"],
        interval_ms=lambda: settings["interval_ms"],
    )
    console = StdConsoleIO(
        stdout=output,
        terminal_bell_profile=profile,
        sleep_fn=lambda seconds: None,
    )

    console.stdout.write("\a")
    settings["repeat_count"] = 4
    console.stdout.write("\a")

    assert output.getvalue() == "\a" * 6


def test_terminal_bell_setting_failure_falls_back_to_one_ring():
    output = StringIO()

    def broken_setting():
        raise RuntimeError("settings unavailable")

    profile = TerminalBellProfile(
        enabled=broken_setting,
        repeat_count=broken_setting,
        interval_ms=broken_setting,
    )
    console = StdConsoleIO(
        stdout=output,
        terminal_bell_profile=profile,
        sleep_fn=lambda seconds: None,
    )

    console.stdout.write("\a")

    assert output.getvalue() == "\a"
