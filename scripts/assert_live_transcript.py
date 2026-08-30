#!/usr/bin/env python3
"""Strict ordering audit for the real installed-CLI acceptance transcript."""
from __future__ import annotations

from pathlib import Path
import sys


def ordered(text: str, start: str, *markers: str) -> None:
    position = text.find(start)
    if position < 0:
        raise AssertionError(f"Missing transcript start marker: {start!r}")
    for marker in markers:
        found = text.find(marker, position + 1)
        if found < 0:
            raise AssertionError(
                f"Missing ordered marker after {start!r}: {marker!r}"
            )
        position = found


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: assert_live_transcript.py TRANSCRIPT")
    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8", errors="replace")

    if "Primary access path:" in text:
        raise AssertionError("Hard-coded Primary access path leaked into user output")

    ordered(
        text,
        "Working: pause",
        "→ Closing current CalDAV Work interval",
        "✓ CalDAV Work interval closed",
        "→ Recording Activity Journal: task_paused",
        "✓ Activity Journal recorded: task_paused",
        "→ Running task.paused extensions",
        "✓ task.paused extensions finished",
        "→ Cleaning up the current work-period reminder",
        "✓ Work-period cleanup finished",
        "✓ Paused work:",
        "What changed:",
        "✓ Operation finished",
        "Console ready",
        "Working: current",
        "No task is active right now. You have paused work",
    )

    ordered(
        text,
        "Working: resume 15m",
        "→ Opening CalDAV Work interval",
        "✓ CalDAV Work interval opened",
        "→ Recording Activity Journal: task_resumed",
        "✓ Activity Journal recorded: task_resumed",
        "→ Running task.resumed extensions",
        "✓ task.resumed extensions finished",
        "✓ Resumed work:",
        "What changed:",
        "→ Setting the work-period reminder",
        "✓ Work period is active",
        "✓ Operation finished",
        "Waiting Mode",
    )

    ordered(
        text,
        "Working: done",
        "→ Closing current CalDAV Work interval",
        "✓ CalDAV Work interval closed",
        "→ Recording Activity Journal: task_completed",
        "✓ Activity Journal recorded: task_completed",
        "→ Cleaning up the current work-period reminder",
        "✓ Work-period cleanup finished",
        "✓ Completed task:",
        "What changed:",
        "✓ Operation finished",
        "Console ready",
    )

    print("PASS: live lifecycle milestones precede final result rendering")
    print("PASS: pause -> current remains semantically correct")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
