#!/usr/bin/env python3
"""Drive the installed CLI like a user and print interaction latency."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

import pexpect
from caldav.davclient import DAVClient

from acceptance_latency_real import (
    _configure,
    _event_ics,
    _free_port,
    _stamp,
    _todo_ics,
    _wait_http,
)

HISTORY_EVENTS = max(0, int(os.environ.get("CALDAV_ASSISTANT_REAL_USE_HISTORY_EVENTS", "250")))


def _historical_event_ics(index: int, now: datetime) -> str:
    start = now - timedelta(days=365 + index)
    end = start + timedelta(minutes=30)
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//CalDAV Assistant Real Use//EN",
            "BEGIN:VEVENT",
            f"UID:history-{index}",
            f"DTSTAMP:{_stamp(now)}",
            f"DTSTART:{_stamp(start)}",
            f"DTEND:{_stamp(end)}",
            f"SUMMARY:Historical event {index}",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )


def _paging_todo_ics(index: int, now: datetime) -> str:
    due = now + timedelta(hours=4, minutes=index)
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//CalDAV Assistant Real Use//EN",
            "BEGIN:VTODO",
            f"UID:paging-task-{index:02d}",
            f"DTSTAMP:{_stamp(now)}",
            f"DUE:{_stamp(due)}",
            f"SUMMARY:Paging acceptance Task {index:02d}",
            "STATUS:NEEDS-ACTION",
            "PRIORITY:5",
            "END:VTODO",
            "END:VCALENDAR",
            "",
        ]
    )


def _elapsed(started: float) -> float:
    return time.monotonic() - started


def _assert_column_major_menu(text: str) -> None:
    """Verify displayed numbering reads downward first, then across columns."""
    rows: list[list[int]] = []
    for raw_line in text.splitlines():
        numbers = [
            int(value)
            for value in re.findall(r"(?:^|\s)(\d+)\.\s", raw_line)
            if int(value) != 0
        ]
        if numbers:
            rows.append(numbers)

    if not rows or max(len(row) for row in rows) < 2:
        raise AssertionError(f"menu did not render a horizontal grid:\n{text}")

    read_order: list[int] = []
    for column in range(max(len(row) for row in rows)):
        for row in rows:
            if column < len(row):
                read_order.append(row[column])

    expected = list(range(1, max(read_order) + 1))
    if read_order != expected:
        raise AssertionError(
            "menu numbering is not top-to-bottom then left-to-right: "
            f"{read_order!r} != {expected!r}\n{text}"
        )


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    executable = shutil.which("caldav-assistant")
    if not executable:
        raise RuntimeError("Installed caldav-assistant executable is not on PATH")

    with tempfile.TemporaryDirectory(prefix="caldav-assistant-real-use-") as raw_tmp:
        tmp = Path(raw_tmp)
        home = tmp / "home"
        home.mkdir()
        storage = tmp / "radicale"
        storage.mkdir()
        port = _free_port()
        base_url = f"http://127.0.0.1:{port}/"
        log = (tmp / "radicale.log").open("w", encoding="utf-8")
        radicale = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "radicale",
                "--config",
                "",
                "--server-hosts",
                f"127.0.0.1:{port}",
                "--storage-filesystem-folder",
                str(storage),
                "--auth-type",
                "none",
                "--logging-level",
                "warning",
            ],
            cwd=root,
            stdout=log,
            stderr=subprocess.STDOUT,
        )

        child = None
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PYTHONUNBUFFERED"] = "1"
        try:
            _wait_http(base_url)
            # Match the credentials written by _configure so the configured
            # collection URLs belong to the same Radicale principal the app reads.
            client = DAVClient(url=base_url, username="latency", password="latency")
            principal = client.principal()
            tasks = principal.make_calendar(name="Tasks")
            events = principal.make_calendar(name="Events")
            work = principal.make_calendar(name="Assistant Work")
            for index in range(3):
                principal.make_calendar(name=f"Decoy {index + 1}")

            now = datetime.now(timezone.utc)
            tasks.save_todo(_todo_ics(now))
            for index in range(1, 13):
                tasks.save_todo(_paging_todo_ics(index, now))
            events.save_event(_event_ics(now))
            for index in range(HISTORY_EVENTS):
                events.save_event(_historical_event_ics(index, now))

            _configure(
                home,
                base_url=base_url,
                task_url=str(tasks.url),
                event_url=str(events.url),
                work_url=str(work.url),
            )
            print(
                f"REAL-USE: seeded {HISTORY_EVENTS} historical Events + "
                "1 upcoming Event + 13 Tasks"
            )

            started = time.monotonic()
            child = pexpect.spawn(
                executable,
                cwd=str(root),
                env=env,
                encoding="utf-8",
                codec_errors="replace",
                timeout=30,
            )
            # Make terminal width deterministic so the human-path acceptance also
            # verifies that a real TTY menu expands horizontally when space allows.
            child.setwinsize(40, 120)
            child.expect("Console ready")
            print(f"REAL-USE: startup_to_console={_elapsed(started):.3f}s")

            started = time.monotonic()
            child.sendline("")
            child.expect(r"What do you want to do\?")
            child.expect(r"> ")
            _assert_column_major_menu(child.before)
            print(
                "PASS: real terminal menu orders top-to-bottom before "
                "left-to-right at 120 columns"
            )
            print(f"REAL-USE: first_menu_open={_elapsed(started):.3f}s")
            child.sendline("0")
            child.expect(r"> ")

            started = time.monotonic()
            child.sendline("")
            child.expect(r"What do you want to do\?")
            print(f"REAL-USE: second_menu_live_refresh={_elapsed(started):.3f}s")

            started = time.monotonic()
            child.sendline("2")
            child.expect(r"Upcoming · next 24h")
            child.expect(r"What do you want to do\?")
            print(f"REAL-USE: upcoming_then_menu={_elapsed(started):.3f}s")

            started = time.monotonic()
            verify_deadline = time.monotonic() + 20.0
            verification_retries = 0
            while True:
                child.sendline("1")
                child.timeout = min(
                    30,
                    max(0.1, verify_deadline - time.monotonic()),
                )
                entered = child.expect(
                    [
                        r"Task Picker: .*i input date|Choose a Task to work on",
                        r"What do you want to do\?",
                    ]
                )
                if entered == 1:
                    verification_retries += 1
                    if time.monotonic() >= verify_deadline:
                        raise AssertionError(
                            "current-work verification did not become ready within 20s"
                        )
                    continue

                # Alternate-screen redraw can replace the title before pexpect
                # consumes it. The date-filtered Task count is the stable state
                # marker that proves the composite picker is actually active.
                today = datetime.now().astimezone().date()
                child.expect(rf"Tasks · {today.isoformat()} · \d+")
                print("PASS: Task Picker defaults to today's date")

                child.send("\x1b[C")
                tomorrow = today + timedelta(days=1)
                child.expect(rf"Tasks · {tomorrow.isoformat()} · \d+")
                child.send("\x1b[D")
                child.expect(rf"Tasks · {today.isoformat()} · \d+")
                print("PASS: Task Picker changes date with left/right arrow keys")

                target_date = (now + timedelta(hours=4, minutes=1)).date()
                child.send("i")
                child.expect(r"Task date \[[0-9-]+\]:")
                child.sendline(target_date.isoformat())
                child.expect(rf"Tasks · {target_date.isoformat()} · \d+")
                child.expect(r"Paging acceptance Task 01")

                child.send("\x1b[B")
                child.expect(r">\s+2\.")
                child.send("\r")

                index = child.expect(
                    [
                        r"How long do you want to work",
                        r"What do you want to do\?",
                    ]
                )
                if index == 0:
                    child.timeout = 30
                    break
                verification_retries += 1
                if time.monotonic() >= verify_deadline:
                    raise AssertionError(
                        "current-work verification did not become ready within 20s"
                    )

            print(
                "PASS: real Task Picker accepted date navigation, typed date, "
                "arrow scrolling and Enter selection"
            )
            print(
                f"REAL-USE: choose_start_to_duration={_elapsed(started):.3f}s "
                f"(verification_retries={verification_retries})"
            )

            # `0 Back` is deliberately the only numeric exit assumption here. It is
            # stable across all Menu instances and therefore cannot drift when home
            # menu options are added/reordered.
            child.sendline("0")
            child.expect(r"What do you want to do\?")
            child.sendline("0")
            child.expect(r"> ")
            child.sendline("exit")
            child.expect(pexpect.EOF)
            print("PASS: exact numbered human path completed against real Radicale")
            return 0
        finally:
            if child is not None:
                try:
                    child.close(force=True)
                except Exception:
                    pass
            try:
                subprocess.run(
                    [executable, "background", "stop"],
                    cwd=root,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                )
            except Exception:
                pass
            radicale.terminate()
            try:
                radicale.wait(timeout=5)
            except subprocess.TimeoutExpired:
                radicale.kill()
                radicale.wait(timeout=5)
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
