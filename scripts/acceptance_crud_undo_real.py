#!/usr/bin/env python3
"""Real PTY acceptance for Task/Event CRUD, PromptKit recovery and Undo.

This deliberately exercises the installed executable against a disposable real
Radicale server. Visible CLI success is never sufficient: after each mutation the
harness reads the authoritative VTODO/VEVENT back from CalDAV.

Covered human paths:
- empty Task/Event lists;
- guided Task creation with the frozen ``August5`` syntax;
- future-bias + date-only preservation for scheduling fields;
- invalid date input recovery inside the same prompt;
- numbered list references;
- edit title / due / priority;
- menu help and Back without mutation;
- delete cancellation, confirmed delete, and persistent Undo restore;
- guided all-day Event creation/edit/delete/Undo.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
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


TASK_TITLE = "CRUD future date acceptance"
TASK_EDITED = "CRUD future date acceptance edited"
EVENT_TITLE = "CRUD all-day event acceptance"
EVENT_LOCATION = "Room 101"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_http(url: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status < 500:
                    return
        except Exception as exc:  # pragma: no cover - diagnostic only
            last_error = exc
        time.sleep(0.1)
    raise RuntimeError(f"Radicale did not become ready: {last_error}")


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
    settings.set(AGENDA_UPCOMING_HOURS, 24)
    settings.set(NOTIFICATIONS_ENABLED, False)
    settings.set(WORDPRESS_ENABLED, False)
    settings.set(
        EXTENSIONS_ENABLED,
        {"software_intro": False, "wordpress_work_session_log": False},
    )


def _expect(child: pexpect.spawn, pattern: str, label: str) -> None:
    child.expect(pattern)
    print(f"PASS: {label}")


def _future_august5(today: date) -> date:
    candidate = date(today.year, 8, 5)
    if candidate < today:
        candidate = date(today.year + 1, 8, 5)
    return candidate


def _ordinary_events(calendar):
    values = []
    for resource in calendar.events():
        component = resource.get_icalendar_component()
        categories = str(component.get("CATEGORIES", "") or "")
        if "caldav-assistant-work" not in categories:
            values.append(component)
    return values


def _task_by_summary(calendar, summary: str):
    matches = []
    for resource in calendar.todos(include_completed=True):
        component = resource.get_icalendar_component()
        if str(component.get("SUMMARY", "")) == summary:
            matches.append(component)
    if len(matches) != 1:
        raise AssertionError(f"Expected one Task {summary!r}, got {len(matches)}")
    return matches[0]


def _event_by_summary(calendar, summary: str):
    matches = [
        component
        for component in _ordinary_events(calendar)
        if str(component.get("SUMMARY", "")) == summary
    ]
    if len(matches) != 1:
        raise AssertionError(f"Expected one Event {summary!r}, got {len(matches)}")
    return matches[0]


def _assert_absent_task(calendar, summary: str) -> None:
    summaries = {
        str(resource.get_icalendar_component().get("SUMMARY", ""))
        for resource in calendar.todos(include_completed=True)
    }
    if summary in summaries:
        raise AssertionError(f"Task {summary!r} still exists in real CalDAV")
    print(f"PASS: real CalDAV confirms Task absent: {summary}")


def _assert_absent_event(calendar, summary: str) -> None:
    summaries = {str(component.get("SUMMARY", "")) for component in _ordinary_events(calendar)}
    if summary in summaries:
        raise AssertionError(f"Event {summary!r} still exists in real CalDAV")
    print(f"PASS: real CalDAV confirms Event absent: {summary}")


def _assert_date_only(component, field: str, expected: date) -> None:
    property_value = component.get(field)
    if property_value is None:
        raise AssertionError(f"{field} is missing")
    actual = getattr(property_value, "dt", property_value)
    if type(actual) is not date:
        raise AssertionError(
            f"{field} must stay DATE-only, got {type(actual).__name__}: {actual!r}"
        )
    if actual != expected:
        raise AssertionError(f"Expected {field} {expected}, got {actual}")
    print(f"PASS: real CalDAV {field} is date-only {expected}")


def _console(child: pexpect.spawn, label: str) -> None:
    _expect(child, "Console ready", label)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    executable = shutil.which("caldav-assistant")
    if not executable:
        raise RuntimeError("Installed caldav-assistant executable is not on PATH")

    with tempfile.TemporaryDirectory(prefix="caldav-assistant-crud-real-") as raw_tmp:
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
            calendar = principal.make_calendar(name="CrudAcceptance")
            calendar_url = str(calendar.url)
            _configure(home, base_url, calendar_url)
            expected_aug5 = _future_august5(datetime.now().astimezone().date())
            print(f"PASS: real Radicale ready at {base_url}")
            print(f"PASS: expected future August5 = {expected_aug5}")

            transcript_path = tmp / "crud-undo-transcript.log"
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
            _expect(child, "CalDAV Assistant", "installed executable launched")
            _console(child, "empty real calendar reached usable console")

            # Empty-state human paths.
            child.sendline("tasks")
            _expect(child, r"Tasks · 0", "empty Task list is explicit")
            _expect(child, r"\(none\)", "empty Task list does not pretend an item exists")
            _console(child, "empty Task list returns to console")
            child.sendline("events")
            _expect(child, r"Events · 0", "empty Event list is explicit")
            _expect(child, r"\(none\)", "empty Event list does not pretend an item exists")
            _console(child, "empty Event list returns to console")

            # Create Task through the real PromptKit/Menu path. On Aug 31, typing
            # August5 must mean the next August 5 and must remain a DATE, not midnight.
            child.sendline(f"add task {TASK_TITLE}")
            _expect(child, "Task timing", "Task timing menu shown")
            child.sendline("2")
            _expect(child, "Due date", "Task due-date prompt shown")
            child.sendline("August5")
            _expect(child, "Optional Task fields", "Task optional-field menu shown")
            child.sendline("4")
            _console(child, "Task creation returns to console")
            created_task = _task_by_summary(calendar, TASK_TITLE)
            _assert_date_only(created_task, "DUE", expected_aug5)

            # Numbered reference is actionable, not decorative.
            child.sendline("tasks")
            _expect(child, TASK_TITLE, "created Task appears in numbered list")
            _expect(child, "Numbers are active references", "numbered-reference contract is visible")
            _console(child, "Task list returns to console")

            child.sendline("edit 1")
            _expect(child, "Modify what", "Task edit field menu shown")
            child.sendline("2")
            _expect(child, "New title", "Task title prompt shown")
            child.sendline(TASK_EDITED)
            _console(child, "Task title edit returns to console")
            _task_by_summary(calendar, TASK_EDITED)
            _assert_absent_task(calendar, TASK_TITLE)

            # Refresh list, then prove invalid date text is recoverable in the same
            # prompt and August5 still uses future context on ordinary `edit`.
            child.sendline("tasks")
            _expect(child, TASK_EDITED, "edited Task appears in list")
            _console(child, "refreshed Task list returns to console")
            child.sendline("edit 1")
            _expect(child, "Modify what", "Task due edit menu shown")
            child.sendline("1")
            _expect(child, "New due date", "Task new due-date prompt shown")
            child.sendline("definitely-not-a-date")
            _expect(child, "Could not understand", "invalid date is explained instead of aborting")
            _expect(child, "New due date", "date prompt repeats after invalid input")
            child.sendline("August5")
            _console(child, "recovered Task due edit returns to console")
            _assert_date_only(_task_by_summary(calendar, TASK_EDITED), "DUE", expected_aug5)

            child.sendline("tasks")
            _expect(child, TASK_EDITED, "Task remains after date edit")
            _console(child, "Task list returns before priority edit")
            child.sendline("edit 1")
            _expect(child, "Modify what", "Task priority edit menu shown")
            child.sendline("3")
            _expect(child, "New priority", "Task priority prompt shown")
            child.sendline("5")
            _console(child, "Task priority edit returns to console")
            priority = int(_task_by_summary(calendar, TASK_EDITED).get("PRIORITY", 0) or 0)
            if priority != 5:
                raise AssertionError(f"Expected real CalDAV PRIORITY 5, got {priority}")
            print("PASS: real CalDAV confirms Task PRIORITY = 5")

            # Shared Menu help + Back must not accidentally mutate anything.
            child.sendline("tasks")
            _expect(child, TASK_EDITED, "Task available for menu control test")
            _console(child, "Task list returns before menu control test")
            child.sendline("edit 1")
            _expect(child, "Modify what", "Task edit menu reopened")
            child.sendline("?")
            _expect(child, "number or exact label: choose", "shared Menu help works")
            _expect(child, "Modify what", "menu redisplays after help")
            child.sendline("0")
            _console(child, "Back leaves edit without mutation")
            _task_by_summary(calendar, TASK_EDITED)

            # Delete cancellation then authoritative deletion + Undo restore.
            child.sendline("tasks")
            _expect(child, TASK_EDITED, "Task available for delete test")
            _console(child, "Task list returns before delete test")
            child.sendline("remove task 1")
            _expect(child, "Continue", "Task delete confirmation shown")
            child.sendline("n")
            _console(child, "cancelled Task delete returns to console")
            _task_by_summary(calendar, TASK_EDITED)
            print("PASS: cancelled delete left real VTODO unchanged")

            child.sendline("remove task 1")
            _expect(child, "Continue", "Task delete confirmation shown again")
            child.sendline("y")
            _console(child, "confirmed Task delete returns to console")
            _assert_absent_task(calendar, TASK_EDITED)
            child.sendline("undo")
            _console(child, "Undo after Task delete returns to console")
            restored_task = _task_by_summary(calendar, TASK_EDITED)
            _assert_date_only(restored_task, "DUE", expected_aug5)
            print("PASS: persistent Undo restored the real VTODO")

            # Event creation and edits use the same future-aware TemporalParser path.
            child.sendline(f"add event {EVENT_TITLE}")
            _expect(child, "Event time", "Event timing menu shown")
            child.sendline("1")
            _expect(child, "Starts", "all-day Event start prompt shown")
            child.sendline("August5")
            _expect(child, "Optional Event fields", "Event optional-field menu shown")
            child.sendline("2")
            _expect(child, "Location", "Event location prompt shown")
            child.sendline(EVENT_LOCATION)
            _expect(child, "Optional Event fields", "Event optional-field menu returns")
            child.sendline("5")
            _console(child, "Event creation returns to console")
            event = _event_by_summary(calendar, EVENT_TITLE)
            _assert_date_only(event, "DTSTART", expected_aug5)
            if str(event.get("LOCATION", "")) != EVENT_LOCATION:
                raise AssertionError("Event LOCATION was not persisted")
            print("PASS: real CalDAV confirms Event LOCATION")

            child.sendline("events")
            _expect(child, EVENT_TITLE, "created Event appears in numbered list")
            _console(child, "Event list returns to console")
            child.sendline("edit-event 1")
            _expect(child, "Modify Event", "Event edit menu shown")
            child.sendline("2")
            _expect(child, "Start type", "Event start-type menu shown")
            child.sendline("1")
            _expect(child, "Start", "Event start date prompt shown")
            child.sendline("August5")
            _console(child, "Event start edit returns to console")
            _assert_date_only(_event_by_summary(calendar, EVENT_TITLE), "DTSTART", expected_aug5)

            child.sendline("events")
            _expect(child, EVENT_TITLE, "Event available for delete test")
            _console(child, "Event list returns before delete test")
            child.sendline("remove event 1")
            _expect(child, "Continue", "Event delete confirmation shown")
            child.sendline("n")
            _console(child, "cancelled Event delete returns to console")
            _event_by_summary(calendar, EVENT_TITLE)
            print("PASS: cancelled delete left real VEVENT unchanged")

            child.sendline("remove event 1")
            _expect(child, "Continue", "Event delete confirmation shown again")
            child.sendline("y")
            _console(child, "confirmed Event delete returns to console")
            _assert_absent_event(calendar, EVENT_TITLE)
            child.sendline("undo")
            _console(child, "Undo after Event delete returns to console")
            restored_event = _event_by_summary(calendar, EVENT_TITLE)
            _assert_date_only(restored_event, "DTSTART", expected_aug5)
            print("PASS: persistent Undo restored the real VEVENT")

            child.sendline("exit")
            child.expect(pexpect.EOF)
            transcript.flush()
            text = transcript_path.read_text(encoding="utf-8", errors="replace")
            for marker in (
                "Traceback (most recent call last)",
                "IPC method is not allowed",
            ):
                if marker in text:
                    raise AssertionError(f"Unexpected user-visible failure marker: {marker}")

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
            print("REAL CRUD/UNDO HUMAN-PATH ACCEPTANCE: PASS")
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
