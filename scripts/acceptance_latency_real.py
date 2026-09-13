#!/usr/bin/env python3
"""Real installed-CLI latency acceptance against real local Radicale.

This is deliberately a human-path acceptance, not a mocked benchmark. It creates
separate Task/Event/Work collections plus decoy collections, writes production
Settings, restarts the background service and immediately launches the installed
executable in a PTY.  It measures startup, enters the exact ``Enter -> 1`` Task path,
exercises guided Upcoming, then proves human think-time is not reported as work.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import pexpect
from caldav.davclient import DAVClient

from caldav_assistant.internal.settings.keys import (
    AGENDA_UPCOMING_HOURS,
    CALDAV_BASE_URL,
    CALDAV_CREDENTIALS,
    CALDAV_EVENT_COLLECTION_URL,
    CALDAV_TASK_COLLECTION_URL,
    CALDAV_WORKLOG_COLLECTION_URL,
    EXPERIMENTAL_FAST_QUERY_CACHE,
    EXTENSIONS_ENABLED,
    NOTIFICATIONS_ENABLED,
    WORDPRESS_ENABLED,
)
from caldav_assistant.internal.settings.service import SettingsService
from caldav_assistant.internal.storage.sqlite import SQLiteKeyValueRepository, SQLiteStore


STARTUP_BUDGET_SECONDS = 4.5
HUMAN_THINK_SECONDS = 4.0
WORK_HISTORY_EVENTS = 250


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_http(url: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status < 500:
                    return
        except Exception as exc:
            error = exc
        time.sleep(0.1)
    raise RuntimeError(f"Radicale did not become ready: {error}")


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _todo_ics(now: datetime, *, status: str = "NEEDS-ACTION") -> str:
    due = now + timedelta(hours=2)
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//CalDAV Assistant Latency Acceptance//EN",
            "BEGIN:VTODO",
            "UID:latency-task",
            f"DTSTAMP:{_stamp(now)}",
            f"DUE:{_stamp(due)}",
            "SUMMARY:Latency acceptance Task",
            f"STATUS:{status}",
            "PRIORITY:1",
            "END:VTODO",
            "END:VCALENDAR",
            "",
        ]
    )


def _event_ics(now: datetime) -> str:
    start = now + timedelta(hours=3)
    end = start + timedelta(minutes=30)
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//CalDAV Assistant Latency Acceptance//EN",
            "BEGIN:VEVENT",
            "UID:latency-event",
            f"DTSTAMP:{_stamp(now)}",
            f"DTSTART:{_stamp(start)}",
            f"DTEND:{_stamp(end)}",
            "SUMMARY:Latency acceptance Event",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )


def _closed_work_ics(index: int, now: datetime) -> str:
    start = now - timedelta(days=index + 1)
    end = start + timedelta(minutes=25)
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//CalDAV Assistant Latency Acceptance//EN",
            "BEGIN:VEVENT",
            f"UID:latency-closed-work-{index}",
            f"DTSTAMP:{_stamp(now)}",
            f"DTSTART:{_stamp(start)}",
            f"DTEND:{_stamp(end)}",
            f"SUMMARY:Closed work interval {index}",
            "CATEGORIES:caldav-assistant-work",
            f"DESCRIPTION:CALDAV-ASSISTANT-TASK-ID:historical-{index}",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )


def _configure(
    home: Path,
    *,
    base_url: str,
    task_url: str,
    event_url: str,
    work_url: str,
) -> None:
    state_dir = home / ".caldav-assistant"
    state_dir.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(state_dir / "assistant.sqlite3")
    store.migrate()
    settings = SettingsService(SQLiteKeyValueRepository(store, "settings"))
    settings.set(CALDAV_BASE_URL, base_url)
    settings.set(
        CALDAV_CREDENTIALS,
        {"username": "latency", "password": "latency"},
    )
    settings.set(CALDAV_TASK_COLLECTION_URL, task_url)
    settings.set(CALDAV_EVENT_COLLECTION_URL, event_url)
    settings.set(CALDAV_WORKLOG_COLLECTION_URL, work_url)
    settings.set(AGENDA_UPCOMING_HOURS, 24)
    settings.set(EXPERIMENTAL_FAST_QUERY_CACHE, False)
    settings.set(NOTIFICATIONS_ENABLED, False)
    settings.set(WORDPRESS_ENABLED, False)
    settings.set(
        EXTENSIONS_ENABLED,
        {"software_intro": False, "wordpress_work_session_log": False},
    )


def _expect(child: pexpect.spawn, pattern: str, label: str) -> None:
    child.expect(pattern)
    print(f"PASS: {label}")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    executable = shutil.which("caldav-assistant")
    if not executable:
        raise RuntimeError("Installed caldav-assistant executable is not on PATH")

    with tempfile.TemporaryDirectory(prefix="caldav-assistant-latency-") as raw_tmp:
        tmp = Path(raw_tmp)
        home = tmp / "home"
        home.mkdir()
        storage = tmp / "radicale"
        storage.mkdir()
        port = _free_port()
        base_url = f"http://127.0.0.1:{port}/"
        radicale_log = (tmp / "radicale.log").open("w", encoding="utf-8")
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
            stdout=radicale_log,
            stderr=subprocess.STDOUT,
        )

        child: pexpect.spawn | None = None
        transcript = None
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PYTHONUNBUFFERED"] = "1"
        try:
            _wait_http(base_url)
            client = DAVClient(url=base_url, username="latency", password="latency")
            principal = client.principal()
            task_calendar = principal.make_calendar(name="Tasks")
            event_calendar = principal.make_calendar(name="Events")
            work_calendar = principal.make_calendar(name="Assistant Work")
            # Decoys deliberately exercise collection discovery. Role-aware reads
            # must discover them once but must not traverse their resources.
            for index in range(5):
                principal.make_calendar(name=f"Decoy {index + 1}")

            now = datetime.now(timezone.utc)
            # IN-PROCESS without an open Work interval is intentionally excluded
            # from recommendation, making "Choose a Task and start" item 1 exactly
            # as in the reported degraded-startup transcript.
            task_calendar.save_todo(_todo_ics(now, status="IN-PROCESS"))
            event_calendar.save_event(_event_ics(now))
            for index in range(WORK_HISTORY_EVENTS):
                work_calendar.save_event(_closed_work_ics(index, now))
            _configure(
                home,
                base_url=base_url,
                task_url=str(task_calendar.url),
                event_url=str(event_calendar.url),
                work_url=str(work_calendar.url),
            )
            print(
                "PASS: real Radicale seeded with 3 role collections + 5 decoys + "
                f"{WORK_HISTORY_EVENTS} closed Work intervals"
            )

            transcript_raw = os.environ.get("CALDAV_ASSISTANT_LATENCY_TRANSCRIPT")
            transcript_path = Path(transcript_raw) if transcript_raw else tmp / "latency.txt"
            if not transcript_path.is_absolute():
                transcript_path = root / transcript_path
            transcript_path.parent.mkdir(parents=True, exist_ok=True)
            transcript = transcript_path.open("w", encoding="utf-8")

            restarted = subprocess.run(
                [executable, "background", "restart"],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
            if restarted.returncode != 0:
                raise AssertionError(
                    "Background restart failed before latency path: "
                    f"{restarted.stdout}{restarted.stderr}"
                )
            print("PASS: background restarted immediately before foreground CLI")

            started = time.monotonic()
            child = pexpect.spawn(
                executable,
                cwd=str(root),
                env=env,
                encoding="utf-8",
                codec_errors="replace",
                timeout=15,
            )
            child.logfile = transcript
            _expect(child, "Console ready", "installed CLI reached usable console")
            startup_elapsed = time.monotonic() - started
            if startup_elapsed > STARTUP_BUDGET_SECONDS:
                raise AssertionError(
                    f"Healthy local startup took {startup_elapsed:.2f}s; "
                    f"budget is {STARTUP_BUDGET_SECONDS:.1f}s"
                )
            print(
                f"PASS: healthy real startup {startup_elapsed:.2f}s "
                f"<= {STARTUP_BUDGET_SECONDS:.1f}s"
            )

            # Reproduce the reported field path exactly.  The menu action must reuse
            # the welcome snapshot and reach Task selection instead of becoming
            # permanently disabled after a startup deadline.
            child.sendline("")
            _expect(child, r"What do you want to do\?", "first guided menu opened")
            child.sendline("1")
            _expect(
                child,
                "Choose a Task to work on",
                "Enter -> 1 reached Task selection without another live Task read",
            )
            # ``0`` in the nested Task chooser means Back, so it returns to the
            # already-open guided menu.  Exit that parent menu explicitly before
            # opening a second visit; otherwise an empty line is merely another menu
            # answer and no fresh snapshot should be expected.
            child.sendline("0")
            _expect(
                child,
                r"What do you want to do\?",
                "Task chooser Back returned to the guided menu",
            )
            child.sendline("0")
            child.expect(r"> ")

            # The next menu performs a fresh read. Selecting Upcoming must reuse it
            # and remain in numbered-menu mode instead of switching to commands.
            child.sendline("")
            _expect(
                child,
                "Refreshing current work, Tasks and Events",
                "second guided menu performed one visible live read",
            )
            _expect(child, r"What do you want to do\?", "second guided menu opened")
            child.sendline("Upcoming — next 24h")
            _expect(child, "Upcoming · next 24h", "guided Upcoming displayed")
            _expect(
                child,
                r"What do you want to do\?",
                "guided menu stayed active after Upcoming",
            )
            child.sendline("0")
            child.expect(r"> ")
            print(
                "PASS: guided Upcoming reused one live snapshot and stayed in numbered-menu mode"
            )

            child.sendline("history")
            _expect(child, "Working: history", "History command entered")
            _expect(child, "History", "History menu displayed")
            # Deliberately behave like a human reading the choices. The old bug
            # printed one fake heartbeat every 3 seconds forever during this pause.
            time.sleep(HUMAN_THINK_SECONDS)
            child.sendline("0")
            _expect(child, "Menu/selection finished", "History menu returned normally")
            child.expect(r"> ")
            child.sendline("exit")
            child.expect(pexpect.EOF)
            child.close()
            child = None

            transcript.flush()
            transcript.close()
            transcript = None
            text = transcript_path.read_text(encoding="utf-8", errors="replace")
            startup_text, _, after_console = text.partition("Console ready")
            if "Live agenda is unavailable" in startup_text or "startup_snapshot" in startup_text and "failed" in startup_text:
                raise AssertionError("Healthy startup fell back to unavailable live data")
            if "Cached Task/Event data" in startup_text:
                raise AssertionError("Healthy local startup unexpectedly used stale cache")
            if "Latency acceptance Task" not in startup_text:
                raise AssertionError("Role-selected Task was not shown during startup")
            if "Latency acceptance Event" not in startup_text:
                raise AssertionError("Role-selected Event was not shown during startup")

            second_menu_marker = "Refreshing current work, Tasks and Events"
            upcoming_marker = "Upcoming · next 24h"
            if second_menu_marker not in after_console or upcoming_marker not in after_console:
                raise AssertionError("Guided Upcoming interaction markers missing from transcript")
            guided_section = after_console.split(second_menu_marker, 1)[1].split(upcoming_marker, 1)[0]
            if "Refreshing Upcoming" in guided_section:
                raise AssertionError(
                    "Selecting Upcoming performed the duplicate live refresh that caused the field timeout"
                )
            if "Unsupported command: 1" in after_console or "Unsupported command: 2" in after_console:
                raise AssertionError(
                    "A guided-menu number leaked into command mode during the human path"
                )
            if "Traceback (most recent call last)" in after_console:
                raise AssertionError("Interactive CLI leaked a traceback during the human path")
            if "Current Task state is unavailable" in after_console:
                raise AssertionError("Enter -> 1 remained disabled after healthy startup")

            marker = "Working: history"
            end_marker = "Menu/selection finished"
            if marker not in after_console or end_marker not in after_console:
                raise AssertionError("History interaction markers missing from transcript")
            history_section = after_console.split(marker, 1)[1].split(end_marker, 1)[0]
            if "Still working" in history_section:
                raise AssertionError(
                    "Human think-time in History was falsely reported as Still working"
                )
            print(
                f"PASS: {HUMAN_THINK_SECONDS:.1f}s human pause in History produced no fake progress heartbeat"
            )
            print(f"PASS: latency transcript written to {transcript_path}")
            return 0
        finally:
            if child is not None:
                try:
                    child.close(force=True)
                except Exception:
                    pass
            if transcript is not None:
                try:
                    transcript.close()
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
            radicale_log.close()


if __name__ == "__main__":
    raise SystemExit(main())
