from io import StringIO

from caldav_assistant.internal.clients.terminal import (
    StdConsoleIO,
    TerminalBellProfile,
)


class StrictAsciiStream(StringIO):
    @property
    def encoding(self):
        return "ascii"

    def write(self, value):
        str(value).encode(self.encoding)
        return super().write(value)


def test_console_output_degrades_unencodable_presentation_glyphs_without_failing():
    output = StrictAsciiStream()
    errors = StrictAsciiStream()
    console = StdConsoleIO(stdout=output, stderr=errors)

    console.write("→ starting ✓")
    console.error("✗ failed — details")

    assert output.getvalue() == "? starting ?\n"
    assert errors.getvalue() == "? failed ? details\n"


def test_bell_messages_also_degrade_safely_on_legacy_encoding():
    output = StrictAsciiStream()
    profile = TerminalBellProfile(
        enabled=lambda: True,
        repeat_count=lambda: 1,
        interval_ms=lambda: 100,
    )
    console = StdConsoleIO(
        stdout=output,
        terminal_bell_profile=profile,
        sleep_fn=lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    console.stdout.write("\a")

    text = output.getvalue()
    assert text.count("\a") == 1
    assert "Reminder alarm" in text
    assert "Task/Event state was not changed" in text


def test_one_logical_bell_repeats_bursts_until_ctrl_c():
    output = StringIO()
    sleep_calls = []

    def interrupt_after_four_sleeps(seconds):
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 4:
            raise KeyboardInterrupt

    profile = TerminalBellProfile(
        enabled=lambda: True,
        repeat_count=lambda: 3,
        interval_ms=lambda: 400,
    )
    console = StdConsoleIO(
        stdout=output,
        terminal_bell_profile=profile,
        sleep_fn=interrupt_after_four_sleeps,
    )

    console.stdout.write("\a")

    text = output.getvalue()
    assert text.count("\a") == 4
    assert "Reminder alarm — press Ctrl-C to stop" in text
    assert "Reminder alarm stopped" in text
    assert sleep_calls == [0.4, 0.4, 0.8, 0.4]


def test_ctrl_c_acknowledges_alarm_without_escaping_to_task_control():
    output = StringIO()
    profile = TerminalBellProfile(
        enabled=lambda: True,
        repeat_count=lambda: 3,
        interval_ms=lambda: 400,
    )
    console = StdConsoleIO(
        stdout=output,
        terminal_bell_profile=profile,
        sleep_fn=lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    # No KeyboardInterrupt should escape: the first Ctrl-C belongs to the alarm.
    console.stdout.write("\a")
    console.stdout.write("after-alarm")

    assert output.getvalue().count("\a") == 1
    assert "Task/Event state was not changed" in output.getvalue()
    assert output.getvalue().endswith("after-alarm")


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
    sleep_calls = []

    def interrupt_on_burst_pause(seconds):
        sleep_calls.append(seconds)
        if seconds >= 0.8:
            raise KeyboardInterrupt

    profile = TerminalBellProfile(
        enabled=lambda: settings["enabled"],
        repeat_count=lambda: settings["repeat_count"],
        interval_ms=lambda: settings["interval_ms"],
    )
    console = StdConsoleIO(
        stdout=output,
        terminal_bell_profile=profile,
        sleep_fn=interrupt_on_burst_pause,
    )

    console.stdout.write("\a")
    settings["repeat_count"] = 4
    console.stdout.write("\a")

    assert output.getvalue().count("\a") == 6


def test_terminal_bell_setting_failure_uses_safe_persistent_defaults():
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
        sleep_fn=lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    console.stdout.write("\a")

    assert output.getvalue().count("\a") == 1
    assert "Reminder alarm stopped" in output.getvalue()