#!/usr/bin/env python3
"""Real PTY acceptance for Waiting Mode, countdown and Ctrl-C.

This is deliberately a human-path acceptance rather than a unit test. It starts a
real local Radicale server, creates a real VTODO, configures an isolated production
Assistant home, launches the installed ``caldav-assistant`` executable in a PTY, and
uses terminal Ctrl-C/keyboard input exactly as a person would.

Acceptance contract:
- start enters Waiting Mode with a real background-owned work period;
- Ctrl-C is caught by the Waiting Mode main thread and opens the decision menu;
- continuing returns to the live countdown;
- the countdown reaches TIME UP without auto-completing the Task;
- ``?`` remains interactive;
- ``p`` performs a real CalDAV pause and returns to the console;
- no traceback/KeyboardInterrupt escapes to the user.
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


TASK_UID = "accept-waiting-mode-interrupt"
TASK_SUMMARY = "Waiting interrupt acceptance"


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


def _todo_ics(now: datetime) -> str:
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//CalDAV Assistant Waiting Acceptance//EN",
            "BEGIN:VTODO",
            f"UID:{TASK_UID}",
            f"DTSTAMP:{_stamp(now)}",
            f"DTSTART:{_stamp(now + timedelta(minutes=1))}",
            f"DUE:{_stamp(now + timedelta(hours=1))}",
            f"SUMMARY:{TASK_SUMMARY}",
            "STATUS:NEEDS-ACTION",
            "PRIORITY:1",
            "END:VTODO",
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


def _todo(calendar):
    matches = []
    for resource in calendar.todos(include_completed=True):
        component = resource.get_icalendar_component()
        if str(component.get("UID", "")) == TASK_UID:
            matches.append(component)
    if len(matches) != 1:
        raise AssertionError(f"Expected one acceptance VTODO, got {len(matches)}")
    return matches[0]


def _verify_paused(calendar) -> None:
    todo = _todo(calendar)
    if str(todo.get("STATUS", "")) != "IN-PROCESS":
        raise AssertionError(f"Paused VTODO must stay IN-PROCESS, got {todo.get('STATUS')}")

    work = []
    for resource in calendar.events():
        component = resource.get_icalendar_component()
        categories = str(component.get("CATEGORIES", "") or "")
        description = str(component.get("DESCRIPTION", "") or "")
        if (
            "caldav-assistant-work" in categories
            and f"Task-UID: {TASK_UID}" in description
        ):
            work.append(component)
    if not work:
        raise AssertionError("No real CalDAV Work VEVENT was written")
    latest = work[-1]
    if latest.get("DTEND") is None:
        raise AssertionError("Paused Work VEVENT has no DTEND")
    if "caldav-assistant-work-open" in str(latest.get("CATEGORIES", "") or ""):
        raise AssertionError("Paused Work VEVENT still carries the open marker")
    print("PASS: real CalDAV confirms pause closed the Work interval")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    executable = shutil.which("caldav-assistant")
    if not executable:
        raise RuntimeError("Installed caldav-assistant executable is not on PATH")

    with tempfile.TemporaryDirectory(prefix="caldav-assistant-wait-accept-") as raw_tmp:
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
            calendar = principal.make_calendar(name="WaitingAcceptance")
            calendar.save_todo(_todo_ics(datetime.now(timezone.utc)))
            calendar_url = str(calendar.url)
            _configure(home, base_url, calendar_url)
            print(f"PASS: real Radicale ready at {base_url}")
            print("PASS: real VTODO seeded")

            raw_transcript = os.environ.get("CALDAV_ASSISTANT_WAIT_ACCEPTANCE_TRANSCRIPT")
            transcript_path = Path(raw_transcript) if raw_transcript else tmp / "waiting.txt"
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

            _expect(child, "CalDAV Assistant", "installed executable launched")
            _expect(child, "Upcoming · next 24h", "startup agenda rendered")
            _expect(child, TASK_SUMMARY, "acceptance Task visible")
            _expect(child, "Console ready", "console entered")

            # Enter -> Start recommended Task -> custom 8-second period -> confirm.
            child.sendline("")
            _expect(child, "What do you want to do", "guided menu opened")
            child.sendline("1")
            _expect(child, "How long do you want to work", "duration menu opened")
            child.sendline("6")
            _expect(child, "Duration", "custom duration prompt shown")
            child.sendline("8s")
            _expect(child, "Ready to start", "start plan shown")
            _expect(child, "Start now", "start confirmation shown")
            child.sendline("")
            _expect(child, "Work period is active", "background work period allocated")
            _expect(child, "Waiting Mode", "Waiting Mode entered")
            _expect(child, r"remaining [0-9]+s", "main-thread countdown visible")

            # Real terminal SIGINT: this must be consumed by Waiting Mode, not leak a
            # Python traceback. Choose Continue and prove the countdown resumes.
            child.sendcontrol("c")
            _expect(child, f"Current Task — {TASK_SUMMARY}", "Ctrl-C opens decision menu")
            _expect(child, "Continue waiting", "interrupt menu offers continue")
            child.sendline("1")
            _expect(child, r"remaining [0-9]+s|TIME UP", "countdown resumes after Ctrl-C")

            # The main thread remains interactive while waiting.
            child.sendline("?")
            _expect(child, "Waiting Mode controls", "question-mark help works in Waiting Mode")

            # The requested eight seconds must expire relative to the actual work
            # start, while the Task remains IN-PROCESS until the user decides.
            _expect(child, "Planned work time has ended", "countdown reaches TIME UP")
            todo_before_pause = _todo(calendar)
            if str(todo_before_pause.get("STATUS", "")) != "IN-PROCESS":
                raise AssertionError("Work-period expiry must not complete/pause the VTODO")
            print("PASS: TIME UP leaves the real VTODO IN-PROCESS")

            child.sendline("p")
            _expect(child, "Working: pause", "pause accepted from Waiting Mode")
            _expect(child, "CalDAV Work interval closed", "pause closed real Work VEVENT")
            _expect(child, "Operation finished", "pause reached authoritative result")
            _expect(child, "Console ready", "pause returned to console")
            _verify_paused(calendar)

            child.sendline("exit")
            child.expect(pexpect.EOF)
            transcript.flush()

            text = transcript_path.read_text(encoding="utf-8", errors="replace")
            forbidden = (
                "Traceback (most recent call last)",
                "KeyboardInterrupt",
                "Runtime request timed out: agenda.next",
            )
            for marker in forbidden:
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
            print(f"PASS: PTY transcript saved to {transcript_path}")
            print("REAL WAITING MODE CTRL-C ACCEPTANCE: PASS")
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
