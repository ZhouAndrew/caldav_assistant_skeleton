#!/usr/bin/env python3
"""Real installed-CLI acceptance for the read-only feature demo/doctor.

This is intentionally not a mocked unit test. It creates a disposable Radicale server,
seeds real VTODO/VEVENT data, disables all bundled Extensions, launches the installed
``caldav-assistant demo`` command, and verifies that the normal CLI -> RuntimeClient ->
local IPC -> Core -> CalDAV path is exercised and diagnosed without mutating the data.
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
            "PRODID:-//CalDAV Assistant Feature Demo Acceptance//EN",
            "BEGIN:VTODO",
            "UID:feature-demo-task",
            f"DTSTAMP:{_stamp(now)}",
            f"DUE:{_stamp(now + timedelta(hours=2))}",
            "SUMMARY:Feature demo acceptance Task",
            "STATUS:NEEDS-ACTION",
            "PRIORITY:1",
            "END:VTODO",
            "END:VCALENDAR",
            "",
        ]
    )


def _event_ics(now: datetime) -> str:
    start = now + timedelta(hours=3)
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//CalDAV Assistant Feature Demo Acceptance//EN",
            "BEGIN:VEVENT",
            "UID:feature-demo-event",
            f"DTSTAMP:{_stamp(now)}",
            f"DTSTART:{_stamp(start)}",
            f"DTEND:{_stamp(start + timedelta(minutes=30))}",
            "SUMMARY:Feature demo acceptance Event",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )


def _configure(home: Path, *, base_url: str, task_url: str, event_url: str, work_url: str) -> None:
    state_dir = home / ".caldav-assistant"
    state_dir.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(state_dir / "assistant.sqlite3")
    store.migrate()
    settings = SettingsService(SQLiteKeyValueRepository(store, "settings"))
    settings.set(CALDAV_BASE_URL, base_url)
    settings.set(CALDAV_CREDENTIALS, {"username": "demo", "password": "demo"})
    settings.set(CALDAV_TASK_COLLECTION_URL, task_url)
    settings.set(CALDAV_EVENT_COLLECTION_URL, event_url)
    settings.set(CALDAV_WORKLOG_COLLECTION_URL, work_url)
    settings.set(NOTIFICATIONS_ENABLED, False)
    settings.set(WORDPRESS_ENABLED, False)
    # The diagnostic must remain available even when every Extension is disabled.
    settings.set(
        EXTENSIONS_ENABLED,
        {"software_intro": False, "wordpress_work_session_log": False, "developer_tools": False},
    )


def _expect(child: pexpect.spawn, pattern: str, label: str) -> None:
    child.expect(pattern)
    print(f"PASS: {label}")


def _assert_source_unchanged(task_calendar, event_calendar) -> None:
    todos = task_calendar.todos()
    events = event_calendar.events()
    if len(todos) != 1 or len(events) != 1:
        raise AssertionError("Feature demo changed the number of source Task/Event objects")
    task_text = todos[0].data
    event_text = events[0].data
    if "STATUS:NEEDS-ACTION" not in task_text:
        raise AssertionError("Feature demo changed Task STATUS")
    if "SUMMARY:Feature demo acceptance Task" not in task_text:
        raise AssertionError("Feature demo changed Task content")
    if "SUMMARY:Feature demo acceptance Event" not in event_text:
        raise AssertionError("Feature demo changed Event content")
    print("PASS: real CalDAV VTODO/VEVENT remained unchanged after diagnosis")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    executable = shutil.which("caldav-assistant")
    if not executable:
        raise RuntimeError("Installed caldav-assistant executable is not on PATH")

    with tempfile.TemporaryDirectory(prefix="caldav-assistant-feature-demo-") as raw_tmp:
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
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PYTHONUNBUFFERED"] = "1"
        try:
            _wait_http(base_url)
            client = DAVClient(url=base_url, username="demo", password="demo")
            principal = client.principal()
            task_calendar = principal.make_calendar(name="Tasks")
            event_calendar = principal.make_calendar(name="Events")
            work_calendar = principal.make_calendar(name="Assistant Work")
            now = datetime.now(timezone.utc)
            task_calendar.save_todo(_todo_ics(now))
            event_calendar.save_event(_event_ics(now))
            _configure(
                home,
                base_url=base_url,
                task_url=str(task_calendar.url),
                event_url=str(event_calendar.url),
                work_url=str(work_calendar.url),
            )
            print("PASS: disposable real Radicale seeded and all Extensions disabled")

            child = pexpect.spawn(
                executable,
                ["demo"],
                cwd=str(root),
                env=env,
                encoding="utf-8",
                codec_errors="replace",
                timeout=30,
            )
            _expect(child, "live feature demo / diagnosis", "installed demo command started")
            _expect(child, r"Command registry.*PASS", "real CommandRegistry path passed")
            _expect(child, r"Background / local IPC.*PASS", "real Background/IPC path passed")
            _expect(child, r"CalDAV status.*PASS", "real CalDAV setup/status path passed")
            _expect(child, r"Task read.*PASS", "real VTODO read passed")
            _expect(child, r"Event read.*PASS", "real VEVENT read passed")
            _expect(child, r"Agenda today.*PASS", "real Agenda path passed")
            _expect(child, r"Next recommendation.*PASS", "real Next path passed")
            _expect(child, r"Current work / Session.*PASS", "real Session path passed")
            _expect(child, r"Activity Journal read.*PASS", "real Activity path passed")
            _expect(child, r"WordPress Outbox read.*PASS", "real Outbox read passed")
            _expect(child, r"CalDAV authenticated connection.*PASS", "real authenticated collection test passed")
            _expect(child, "Live diagnosis result: PASS", "healthy disposable environment diagnosed PASS")
            _expect(
                child,
                "Safety: read-only; no Task/Event/WordPress data was changed.",
                "demo stated its read-only safety contract",
            )
            child.expect(pexpect.EOF)
            child.close()
            if child.exitstatus not in (None, 0):
                raise AssertionError(f"installed feature demo exited with {child.exitstatus}")
            child = None

            _assert_source_unchanged(task_calendar, event_calendar)
            print("REAL INSTALLED FEATURE DEMO ACCEPTANCE: PASS")
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
            radicale_log.close()


if __name__ == "__main__":
    raise SystemExit(main())
