#!/usr/bin/env python3
"""Real user-path acceptance for the installed CalDAV Assistant CLI.

This is intentionally not a unit test. It starts a real local Radicale server,
creates real VTODO/VEVENT resources through python-caldav, writes production Settings
storage, launches the installed ``caldav-assistant`` executable in a PTY, follows the
zero-learning human path, and verifies both intermediate and final CalDAV facts.

The acceptance specifically guards the human contract for lifecycle transparency:
progress must be visible while pause/resume/done are executing, not reconstructed only
afterward, and a paused IN-PROCESS Task must not be reported as ``current``.

Dependencies used only by this acceptance harness: radicale, pexpect.
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
    EXTENSIONS_ENABLED,
    NOTIFICATIONS_ENABLED,
    WORDPRESS_ENABLED,
)
from caldav_assistant.internal.settings.service import SettingsService
from caldav_assistant.internal.storage.sqlite import SQLiteKeyValueRepository, SQLiteStore


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


def _ical_stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _todo_ics(now: datetime) -> str:
    start = now + timedelta(minutes=2)
    due = now + timedelta(hours=2)
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//CalDAV Assistant Acceptance//EN",
            "BEGIN:VTODO",
            "UID:accept-task-english-writing",
            f"DTSTAMP:{_ical_stamp(now)}",
            f"DTSTART:{_ical_stamp(start)}",
            f"DUE:{_ical_stamp(due)}",
            "SUMMARY:English writing acceptance",
            "STATUS:NEEDS-ACTION",
            "PRIORITY:1",
            "END:VTODO",
            "END:VCALENDAR",
            "",
        ]
    )


def _event_ics(now: datetime) -> str:
    start = now + timedelta(hours=3)
    end = start + timedelta(minutes=45)
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//CalDAV Assistant Acceptance//EN",
            "BEGIN:VEVENT",
            "UID:accept-event-english-class",
            f"DTSTAMP:{_ical_stamp(now)}",
            f"DTSTART:{_ical_stamp(start)}",
            f"DTEND:{_ical_stamp(end)}",
            "SUMMARY:English class acceptance",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )


def _configure_assistant(home: Path, base_url: str, calendar_url: str) -> None:
    state_dir = home / ".caldav-assistant"
    state_dir.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(state_dir / "assistant.sqlite3")
    store.migrate()
    settings = SettingsService(SQLiteKeyValueRepository(store, "settings"))
    settings.set(CALDAV_BASE_URL, base_url)
    settings.set(
        CALDAV_CREDENTIALS,
        {"username": "acceptance", "password": "acceptance"},
    )
    settings.set(CALDAV_TASK_COLLECTION_URL, calendar_url)
    settings.set(CALDAV_EVENT_COLLECTION_URL, calendar_url)
    settings.set(AGENDA_UPCOMING_HOURS, 24)
    settings.set(NOTIFICATIONS_ENABLED, False)
    settings.set(WORDPRESS_ENABLED, False)
    settings.set(
        EXTENSIONS_ENABLED,
        {"software_intro": False, "wordpress_work_session_log": False},
    )


def _expect(child: pexpect.spawn, pattern: str, *, label: str) -> None:
    child.expect(pattern)
    print(f"PASS: {label}")


def _todo_by_uid(calendar, uid: str):
    matches = []
    for resource in calendar.todos(include_completed=True):
        component = resource.get_icalendar_component()
        if str(component.get("UID", "")) == uid:
            matches.append(component)
    if len(matches) != 1:
        raise AssertionError(f"Expected exactly one VTODO {uid}, got {len(matches)}")
    return matches[0]


def _verify_paused_server(calendar) -> None:
    todo = _todo_by_uid(calendar, "accept-task-english-writing")
    if str(todo.get("STATUS", "")) != "IN-PROCESS":
        raise AssertionError(
            f"Paused VTODO must remain IN-PROCESS, got {todo.get('STATUS')}"
        )

    work_events = []
    for resource in calendar.events():
        component = resource.get_icalendar_component()
        categories = component.get("CATEGORIES")
        category_text = str(categories or "")
        description = str(component.get("DESCRIPTION", "") or "")
        if (
            "caldav-assistant-work" in category_text
            and "Task-UID: accept-task-english-writing" in description
        ):
            work_events.append(component)
    if not work_events:
        raise AssertionError("Pause did not leave a real CalDAV Work VEVENT")
    latest = work_events[-1]
    if latest.get("DTEND") is None:
        raise AssertionError("Paused CalDAV Work VEVENT has no DTEND")
    if "caldav-assistant-work-open" in str(latest.get("CATEGORIES", "") or ""):
        raise AssertionError("Paused CalDAV Work VEVENT still has the open marker")
    print("PASS: real CalDAV confirms paused Task is IN-PROCESS with a closed Work VEVENT")


def _verify_server(calendar) -> None:
    todo = _todo_by_uid(calendar, "accept-task-english-writing")
    if str(todo.get("STATUS", "")) != "COMPLETED":
        raise AssertionError(f"VTODO was not completed in real CalDAV: {todo.get('STATUS')}")
    if int(todo.get("PERCENT-COMPLETE", 0) or 0) != 100:
        raise AssertionError("VTODO PERCENT-COMPLETE is not 100")
    if todo.get("COMPLETED") is None:
        raise AssertionError("VTODO COMPLETED timestamp was not written")

    events = list(calendar.events())
    event_uids = {
        str(resource.get_icalendar_component().get("UID", "")) for resource in events
    }
    if "accept-event-english-class" not in event_uids:
        raise AssertionError("Acceptance VEVENT disappeared during Task lifecycle")
    print("PASS: CalDAV server confirms Task COMPLETED and Event still exists")


def _assert_order(text: str, start_marker: str, *markers: str) -> None:
    start = text.find(start_marker)
    if start < 0:
        raise AssertionError(f"Transcript missing start marker: {start_marker}")
    position = start
    for marker in markers:
        found = text.find(marker, position + 1)
        if found < 0:
            raise AssertionError(
                f"Transcript missing ordered marker after {start_marker!r}: {marker!r}"
            )
        position = found


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    executable = shutil.which("caldav-assistant")
    if not executable:
        raise RuntimeError("Installed caldav-assistant executable is not on PATH")

    with tempfile.TemporaryDirectory(prefix="caldav-assistant-real-accept-") as raw_tmp:
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
            client = DAVClient(
                url=base_url,
                username="acceptance",
                password="acceptance",
            )
            principal = client.principal()
            calendar = principal.make_calendar(name="Acceptance")
            calendar.save_todo(_todo_ics(datetime.now(timezone.utc)))
            calendar.save_event(_event_ics(datetime.now(timezone.utc)))
            calendar_url = str(calendar.url)
            _configure_assistant(home, base_url, calendar_url)
            print(f"PASS: real Radicale ready at {base_url}")
            print(f"PASS: real CalDAV collection seeded at {calendar_url}")

            transcript_raw = os.environ.get("CALDAV_ASSISTANT_ACCEPTANCE_TRANSCRIPT")
            transcript_path = (
                Path(transcript_raw) if transcript_raw else tmp / "conversation.txt"
            )
            if not transcript_path.is_absolute():
                transcript_path = root / transcript_path
            transcript_path.parent.mkdir(parents=True, exist_ok=True)
            transcript = transcript_path.open("w", encoding="utf-8")
            child = pexpect.spawn(
                executable,
                cwd=str(root),
                env=env,
                encoding="utf-8",
                codec_errors="replace",
                timeout=30,
            )
            child.logfile = transcript

            _expect(child, "CalDAV Assistant", label="installed executable launched")
            _expect(
                child,
                "Reading current work, Tasks and Events",
                label="startup reports real work",
            )
            _expect(child, "Upcoming · next 24h", label="Upcoming window shown")
            _expect(child, "English writing acceptance", label="Upcoming Task shown")
            _expect(child, "English class acceptance", label="Upcoming Event shown")
            _expect(child, "Recommended", label="recommendation section shown")
            _expect(child, "Console ready", label="unified console entered")

            # Zero-learning path: Enter -> recommended Task -> 15 minutes -> confirm.
            child.sendline("")
            _expect(child, "What do you want to do", label="Enter opens guided menu")
            child.sendline("1")
            _expect(child, "How long do you want to work", label="duration menu shown")
            child.sendline("1")
            _expect(child, "Ready to start", label="start/end plan preview shown")
            _expect(child, "Start now", label="start confirmation shown")
            child.sendline("")
            _expect(
                child,
                "Opening CalDAV Work interval",
                label="start reports real CalDAV Work write before completion",
            )
            _expect(child, "CalDAV Work interval opened", label="start Work write confirmed")
            _expect(child, "Work period is active", label="background work period allocated")
            _expect(
                child,
                "Task DUE/DTSTART were not changed",
                label="timing semantics are explicit",
            )
            _expect(child, "Waiting Mode", label="Waiting Mode entered")
            _expect(child, r"start .* end .* remaining", label="start/end/remaining shown live")

            child.sendline("p")
            _expect(child, "Working: pause", label="pause accepted from Waiting Mode")
            _expect(
                child,
                "Closing current CalDAV Work interval",
                label="pause reports Work VEVENT close before it finishes",
            )
            _expect(
                child,
                "CalDAV Work interval closed",
                label="pause confirms DTEND/open-marker write immediately",
            )
            _expect(
                child,
                "Recording Activity Journal: task_paused",
                label="pause reports Activity persist start",
            )
            _expect(
                child,
                "Activity Journal recorded: task_paused",
                label="pause reports Activity persist completion",
            )
            _expect(
                child,
                "Running task.paused extensions",
                label="pause reports hook phase after Activity",
            )
            _expect(
                child,
                "task.paused extensions finished",
                label="pause reports hook completion",
            )
            _expect(
                child,
                "Cleaning up the current work-period reminder",
                label="pause reports work-period cleanup start",
            )
            _expect(
                child,
                "Work-period cleanup finished",
                label="pause reports work-period cleanup completion",
            )
            _expect(child, "Operation finished", label="pause final summary follows live milestones")
            _expect(child, "Console ready", label="pause returns to console")

            _verify_paused_server(calendar)

            # `current` must mean actual active human work, not merely VTODO
            # STATUS:IN-PROCESS.  The paused task stays IN-PROCESS in CalDAV but is
            # explicitly not current.
            child.sendline("current")
            _expect(child, "Working: current", label="current query accepted after pause")
            _expect(
                child,
                "No task is active right now. You have paused work",
                label="paused IN-PROCESS Task is not reported as current",
            )
            _expect(child, "Operation finished", label="current query completed")

            # Resume through the same Core lifecycle and restore Waiting Mode.
            child.sendline("resume 15m")
            _expect(child, "Working: resume 15m", label="resume shortcut accepted")
            _expect(
                child,
                "Opening CalDAV Work interval",
                label="resume reports real CalDAV Work write",
            )
            _expect(child, "CalDAV Work interval opened", label="resume Work write confirmed")
            _expect(child, "Work period is active", label="resume allocates new period")
            _expect(child, "Waiting Mode", label="resume returns to Waiting Mode")
            _expect(child, r"start .* end .* remaining", label="resumed timing is visible")

            child.sendline("d")
            _expect(child, "Working: done", label="done accepted from Waiting Mode")
            _expect(
                child,
                "Closing current CalDAV Work interval",
                label="done reports closing active Work interval",
            )
            _expect(child, "CalDAV Work interval closed", label="done Work close confirmed")
            _expect(
                child,
                "Recording Activity Journal: task_completed",
                label="done reports Activity persist",
            )
            _expect(
                child,
                "Work-period cleanup finished",
                label="done reports work-period cleanup",
            )
            _expect(child, "Operation finished", label="done final summary follows milestones")
            _expect(child, "Console ready", label="completion returns to console")
            child.sendline("exit")
            child.expect(pexpect.EOF)
            if child.exitstatus not in (None, 0):
                raise AssertionError(f"caldav-assistant exited with {child.exitstatus}")
            transcript.flush()

            text = transcript_path.read_text(encoding="utf-8", errors="replace")
            forbidden = (
                "Traceback (most recent call last)",
                "IPC method is not allowed",
                "Unknown command",
                "Primary access path:",
            )
            for marker in forbidden:
                if marker in text:
                    raise AssertionError(f"Unexpected user-visible failure marker: {marker}")

            _assert_order(
                text,
                "Working: pause",
                "Closing current CalDAV Work interval",
                "CalDAV Work interval closed",
                "Recording Activity Journal: task_paused",
                "Activity Journal recorded: task_paused",
                "Running task.paused extensions",
                "task.paused extensions finished",
                "Cleaning up the current work-period reminder",
                "Work-period cleanup finished",
                "Operation finished",
                "Console ready",
                "Working: current",
                "No task is active right now. You have paused work",
            )
            print("PASS: transcript proves live pause milestones occur before final result")
            print("PASS: transcript proves pause -> current semantics")

            _verify_server(calendar)

            stopped = subprocess.run(
                [executable, "background", "stop"],
                cwd=root,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=15,
            )
            if stopped.returncode != 0:
                raise AssertionError(f"background stop failed:\n{stopped.stdout}")
            print("PASS: real background Assistant stopped cleanly")
            print(f"PASS: full PTY transcript saved to {transcript_path}")
            print("REAL CONVERSATION ACCEPTANCE: PASS")
            return 0
        finally:
            if child is not None and child.isalive():
                child.close(force=True)
            if transcript is not None and not transcript.closed:
                transcript.flush()
                transcript.close()
            try:
                subprocess.run(
                    [executable, "background", "stop"],
                    cwd=root,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
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
