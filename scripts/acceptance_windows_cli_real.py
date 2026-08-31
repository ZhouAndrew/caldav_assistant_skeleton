#!/usr/bin/env python3
"""Real installed-CLI acceptance intended to run on Windows runners.

Unlike pytest-only Windows coverage, this harness launches a real local Radicale
server, writes production Assistant settings, invokes the installed
``caldav-assistant`` executable as a normal user would, and verifies authoritative
CalDAV facts after lifecycle operations.

The flow is deliberately one-shot rather than PTY based so it works on Windows:
background auto-start -> today/tasks/events -> start -> current -> pause -> current
-> resume -> done -> background status/stop.
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

from caldav.davclient import DAVClient

from caldav_assistant.internal.settings.keys import (
    AGENDA_UPCOMING_HOURS,
    CALDAV_BASE_URL,
    CALDAV_CREDENTIALS,
    CALDAV_EVENT_COLLECTION_URL,
    CALDAV_TASK_COLLECTION_URL,
    CALDAV_WORKLOG_COLLECTION_URL,
    EXTENSIONS_ENABLED,
    NOTIFICATIONS_ENABLED,
    WORDPRESS_ENABLED,
)
from caldav_assistant.internal.settings.service import SettingsService
from caldav_assistant.internal.storage.sqlite import SQLiteKeyValueRepository, SQLiteStore


TASK_UID = "accept-windows-human-task"
EVENT_UID = "accept-windows-human-event"
TASK_SUMMARY = "Windows human path task"
EVENT_SUMMARY = "Windows human path event"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_http(url: str, timeout: float = 12.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status < 500:
                    return
        except Exception as exc:  # pragma: no cover - only for diagnostic text
            last_error = exc
        time.sleep(0.1)
    raise RuntimeError(f"Radicale did not become ready: {last_error}")


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _todo_ics(now: datetime) -> str:
    start = now + timedelta(minutes=5)
    due = now + timedelta(minutes=45)
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//CalDAV Assistant Windows Acceptance//EN",
            "BEGIN:VTODO",
            f"UID:{TASK_UID}",
            f"DTSTAMP:{_stamp(now)}",
            f"DTSTART:{_stamp(start)}",
            f"DUE:{_stamp(due)}",
            f"SUMMARY:{TASK_SUMMARY}",
            "STATUS:NEEDS-ACTION",
            "PRIORITY:1",
            "END:VTODO",
            "END:VCALENDAR",
            "",
        ]
    )


def _event_ics(now: datetime) -> str:
    start = now + timedelta(minutes=20)
    end = start + timedelta(minutes=15)
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//CalDAV Assistant Windows Acceptance//EN",
            "BEGIN:VEVENT",
            f"UID:{EVENT_UID}",
            f"DTSTAMP:{_stamp(now)}",
            f"DTSTART:{_stamp(start)}",
            f"DTEND:{_stamp(end)}",
            f"SUMMARY:{EVENT_SUMMARY}",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )


def _configure(home: Path, base_url: str, calendar_url: str) -> None:
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
    settings.set(CALDAV_WORKLOG_COLLECTION_URL, calendar_url)
    settings.set(AGENDA_UPCOMING_HOURS, 24)
    settings.set(NOTIFICATIONS_ENABLED, False)
    settings.set(WORDPRESS_ENABLED, False)
    settings.set(
        EXTENSIONS_ENABLED,
        {"software_intro": False, "wordpress_work_session_log": False},
    )


def _todo(calendar):
    matches = []
    for resource in calendar.todos(include_completed=True):
        component = resource.get_icalendar_component()
        if str(component.get("UID", "")) == TASK_UID:
            matches.append(component)
    if len(matches) != 1:
        raise AssertionError(f"Expected one {TASK_UID} VTODO, got {len(matches)}")
    return matches[0]


def _assert_status(calendar, expected: str) -> None:
    actual = str(_todo(calendar).get("STATUS", ""))
    if actual != expected:
        raise AssertionError(f"Expected VTODO STATUS {expected}, got {actual}")
    print(f"PASS: real CalDAV VTODO STATUS = {expected}")


def _assert_completed(calendar) -> None:
    todo = _todo(calendar)
    if str(todo.get("STATUS", "")) != "COMPLETED":
        raise AssertionError(f"Task not completed: {todo.get('STATUS')}")
    if int(todo.get("PERCENT-COMPLETE", 0) or 0) != 100:
        raise AssertionError("Completed VTODO did not get PERCENT-COMPLETE:100")
    if todo.get("COMPLETED") is None:
        raise AssertionError("Completed VTODO did not get COMPLETED timestamp")
    event_uids = {
        str(resource.get_icalendar_component().get("UID", ""))
        for resource in calendar.events()
    }
    if EVENT_UID not in event_uids:
        raise AssertionError("Ordinary VEVENT disappeared during Task lifecycle")
    print("PASS: real CalDAV confirms completion fields and ordinary Event preservation")


def _run(executable: str, root: Path, env: dict[str, str], *args: str) -> str:
    command = [executable, *args]
    completed = subprocess.run(
        command,
        cwd=root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
    )
    output = completed.stdout or ""
    print("$ " + " ".join(["caldav-assistant", *args]))
    print(output.rstrip())
    if completed.returncode != 0:
        raise AssertionError(
            f"Command returned {completed.returncode}: {' '.join(args)}\n{output}"
        )
    forbidden = ("Traceback (most recent call last)", "IPC method is not allowed")
    for marker in forbidden:
        if marker in output:
            raise AssertionError(f"Unexpected user-visible failure marker: {marker}")
    return output


def _require(output: str, marker: str, label: str) -> None:
    if marker.casefold() not in output.casefold():
        raise AssertionError(f"Missing {marker!r} while checking {label}:\n{output}")
    print(f"PASS: {label}")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    executable = shutil.which("caldav-assistant")
    if not executable:
        raise RuntimeError("Installed caldav-assistant executable is not on PATH")

    with tempfile.TemporaryDirectory(prefix="caldav-assistant-win-real-") as raw_tmp:
        tmp = Path(raw_tmp)
        home = tmp / "home"
        home.mkdir()
        storage = tmp / "radicale"
        storage.mkdir()
        port = _free_port()
        base_url = f"http://127.0.0.1:{port}/"
        radicale_log_path = tmp / "radicale.log"
        radicale_log = radicale_log_path.open("w", encoding="utf-8")
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

        env = os.environ.copy()
        # pathlib.Path.home() follows USERPROFILE on Windows and HOME on POSIX.
        # Set both so the foreground client and spawned background service share the
        # same disposable production SQLite state.
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
        env["PYTHONUNBUFFERED"] = "1"

        try:
            _wait_http(base_url)
            client = DAVClient(
                url=base_url,
                username="acceptance",
                password="acceptance",
            )
            principal = client.principal()
            calendar = principal.make_calendar(name="WindowsAcceptance")
            now = datetime.now(timezone.utc)
            calendar.save_todo(_todo_ics(now))
            calendar.save_event(_event_ics(now))
            calendar_url = str(calendar.url)
            _configure(home, base_url, calendar_url)
            print(f"PASS: real Radicale ready at {base_url}")
            print(f"PASS: production settings written under {home}")

            today = _run(executable, root, env, "today")
            _require(today, "Command result", "installed one-shot today completed")

            tasks = _run(executable, root, env, "tasks")
            _require(tasks, TASK_SUMMARY, "real Task visible through installed CLI")
            events = _run(executable, root, env, "events")
            _require(events, EVENT_SUMMARY, "real Event visible through installed CLI")

            started = _run(executable, root, env, "start", TASK_SUMMARY)
            _require(started, "Started work", "start completed through real Core/IPC path")
            _assert_status(calendar, "IN-PROCESS")

            current = _run(executable, root, env, "current")
            _require(current, TASK_SUMMARY, "current reports active human work")

            paused = _run(executable, root, env, "pause")
            _require(paused, "Paused work", "pause completed through real Core/IPC path")
            _assert_status(calendar, "IN-PROCESS")
            current_after_pause = _run(executable, root, env, "current")
            _require(
                current_after_pause,
                "paused work",
                "paused IN-PROCESS Task is not misreported as current",
            )

            resumed = _run(executable, root, env, "resume")
            _require(resumed, "Resumed work", "resume completed through real Core/IPC path")
            _assert_status(calendar, "IN-PROCESS")

            completed = _run(executable, root, env, "done")
            _require(completed, "Completed", "done completed through real Core/IPC path")
            _assert_completed(calendar)

            status = _run(executable, root, env, "background", "status")
            _require(status, "running", "background service is actually running")
            _run(executable, root, env, "background", "stop")
            print("PASS: real background Assistant stopped cleanly")
            print("REAL WINDOWS INSTALLED CLI ACCEPTANCE: PASS")
            return 0
        finally:
            try:
                subprocess.run(
                    [executable, "background", "stop"],
                    cwd=root,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=8,
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
