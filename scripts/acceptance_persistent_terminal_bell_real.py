#!/usr/bin/env python3
"""Real PTY acceptance for the persistent terminal reminder alarm.

This is intentionally not a unit test. It launches a fresh Python process using the
installed CalDAV Assistant package, lets a real terminal BEL alarm repeat across more
than one burst, sends a real Ctrl-C through the pseudo-terminal, and verifies that the
alarm consumes that interrupt and the process continues normally afterward.
"""
from __future__ import annotations

import sys

import pexpect


CHILD_PROGRAM = r'''
from caldav_assistant.internal.clients.terminal import StdConsoleIO, TerminalBellProfile

profile = TerminalBellProfile(
    enabled=lambda: True,
    repeat_count=lambda: 3,
    interval_ms=lambda: 100,
)
console = StdConsoleIO(terminal_bell_profile=profile)
console.stdout.write("\a")
print("PROCESS CONTINUED AFTER ALARM ACKNOWLEDGEMENT", flush=True)
'''


def main() -> int:
    child = pexpect.spawn(
        sys.executable,
        ["-c", CHILD_PROGRAM],
        encoding="utf-8",
        codec_errors="replace",
        timeout=8,
    )
    try:
        child.expect("Reminder alarm — press Ctrl-C to stop the ringing")
        print("PASS: persistent reminder alarm announced its Ctrl-C acknowledgement")

        # Three BEL bytes are the first configured burst. Requiring a fourth proves
        # the alarm did not stop after the old fixed three-ring behavior.
        for bell_number in range(4):
            child.expect("\a")
            print(f"PASS: observed terminal BEL #{bell_number + 1}")

        child.sendcontrol("c")
        child.expect("Reminder alarm stopped")
        print("PASS: real Ctrl-C stopped the persistent alarm")

        child.expect("Task/Event state was not changed")
        child.expect("PROCESS CONTINUED AFTER ALARM ACKNOWLEDGEMENT")
        print("PASS: Ctrl-C acknowledgement did not escape into task control or terminate the process")

        child.expect(pexpect.EOF)
        child.close()
        if child.exitstatus not in (None, 0):
            raise AssertionError(f"persistent bell child exited with {child.exitstatus}")
        print("REAL PERSISTENT TERMINAL BELL ACCEPTANCE: PASS")
        return 0
    finally:
        if child.isalive():
            child.close(force=True)


if __name__ == "__main__":
    raise SystemExit(main())
