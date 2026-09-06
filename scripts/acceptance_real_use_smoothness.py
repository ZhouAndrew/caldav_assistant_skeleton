#!/usr/bin/env python3
"""Drive the installed CLI like a user and print interaction latency."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
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

HISTORY_EVENTS = 250


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


def _elapsed(started: float) -> float:
    return time.monotonic() - started


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
            print(f"REAL-USE: seeded {HISTORY_EVENTS} historical Events + 1 upcoming Event + 1 Task")

            started = time.monotonic()
            child = pexpect.spawn(
                executable,
                cwd=str(root),
                env=env,
                encoding="utf-8",
                codec_errors="replace",
                timeout=30,
            )
            child.expect("Console ready")
            print(f"REAL-USE: startup_to_console={_elapsed(started):.3f}s")

            started = time.monotonic()
            child.sendline("")
            child.expect(r"What do you want to do\?")
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
            child.sendline("1")
            child.expect(r"How long do you want to work")
            print(f"REAL-USE: choose_start_to_duration={_elapsed(started):.3f}s")

            child.sendline("0")
            child.expect(r"What do you want to do\?")
            child.sendline("10")
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
