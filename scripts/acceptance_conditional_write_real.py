#!/usr/bin/env python3
"""Real request-budget acceptance for live Task/Event conditional writes.

The test runs the production CalDAV adapter stack against disposable Radicale and
counts DAVClient.request calls.  In python-caldav 3.2.1 one authoritative UID lookup
is two REPORTs (calendar-query followed by calendar-multiget for the body).  A normal
edit must therefore be exactly two REPORTs followed by one If-Match PUT.  The old
service path performed that UID lookup twice, costing four REPORTs before the PUT.
It also proves a stale fast snapshot falls back to the old fresh-read merge behavior.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from caldav.davclient import DAVClient

from caldav_assistant.internal.caldav import (
    CollectionRoutingCalDAVAdapter,
    ExperimentalCacheCalDAVAdapter,
    LibraryCalDAVAdapter,
    SyncEngine,
)
from caldav_assistant.internal.events.service import EventService
from caldav_assistant.internal.tasks.service import TaskService


class Provider:
    def __init__(self, url: str):
        self.url = url

    def get_base_url(self) -> str:
        return self.url


class MemoryCache:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


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


def _todo(now: datetime) -> str:
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//CalDAV Assistant Conditional Write Acceptance//EN",
            "BEGIN:VTODO",
            "UID:conditional-task",
            f"DTSTAMP:{_stamp(now)}",
            f"DUE:{_stamp(now + timedelta(hours=2))}",
            "SUMMARY:Initial Task",
            "DESCRIPTION:initial detail",
            "STATUS:NEEDS-ACTION",
            "END:VTODO",
            "END:VCALENDAR",
            "",
        ]
    )


def _event(now: datetime) -> str:
    start = now + timedelta(hours=1)
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//CalDAV Assistant Conditional Write Acceptance//EN",
            "BEGIN:VEVENT",
            "UID:conditional-event",
            f"DTSTAMP:{_stamp(now)}",
            f"DTSTART:{_stamp(start)}",
            f"DTEND:{_stamp(start + timedelta(minutes=30))}",
            "SUMMARY:Initial Event",
            "DESCRIPTION:event detail",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )


def _instrument(client):
    original = client.request
    calls = []

    def counted(url=None, method="GET", body="", headers=None):
        normalized = {
            str(key).lower(): str(value)
            for key, value in dict(headers or {}).items()
        }
        calls.append((str(method or "GET").upper(), str(url or ""), normalized))
        return original(url, method, body, headers)

    client.request = counted
    return calls


def _assert_normal_edit_budget(calls, label: str) -> None:
    methods = [method for method, _url, _headers in calls]
    reports = methods.count("REPORT")
    puts = methods.count("PUT")
    gets = methods.count("GET")
    if reports != 2 or puts != 1 or gets != 0:
        raise AssertionError(
            f"{label} expected 2 REPORT + 1 PUT + 0 GET, observed {methods}"
        )
    put_headers = next(headers for method, _url, headers in calls if method == "PUT")
    if not put_headers.get("if-match"):
        raise AssertionError(f"{label} PUT did not carry If-Match: {put_headers}")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="caldav-assistant-conditional-write-") as raw_tmp:
        tmp = Path(raw_tmp)
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
        inner = None
        try:
            _wait_http(base_url)
            writer = DAVClient(url=base_url, username="accept", password="accept")
            principal = writer.principal()
            task_calendar = principal.make_calendar(name="Tasks")
            event_calendar = principal.make_calendar(name="Events")
            now = datetime.now(timezone.utc)
            task_calendar.save_todo(_todo(now))
            event_calendar.save_event(_event(now))
            print("PASS: real Radicale seeded for conditional-write acceptance")

            inner = LibraryCalDAVAdapter(
                Provider(base_url),
                {"username": "accept", "password": "accept"},
            )
            routed = CollectionRoutingCalDAVAdapter(
                inner,
                task_collection_url=lambda: str(task_calendar.url),
                event_collection_url=lambda: str(event_calendar.url),
            )
            sync = SyncEngine(routed, MemoryCache())
            app = ExperimentalCacheCalDAVAdapter(
                routed,
                sync,
                enabled=lambda: False,
            )
            tasks = TaskService(app)
            events = EventService(app)

            production_client = inner._client_now()
            calls = _instrument(production_client)

            calls.clear()
            task_result = tasks.update("conditional-task", summary="Edited Task")
            if task_result.affected.summary != "Edited Task":
                raise AssertionError("Task update did not persist expected summary")
            _assert_normal_edit_budget(calls, "Task update")
            print("PASS: Task edit used one UID lookup (2 REPORTs) + one If-Match PUT")

            calls.clear()
            event_result = events.update("conditional-event", summary="Edited Event")
            if event_result.affected.summary != "Edited Event":
                raise AssertionError("Event update did not persist expected summary")
            _assert_normal_edit_budget(calls, "Event update")
            print("PASS: Event edit used one UID lookup (2 REPORTs) + one If-Match PUT")

            stale = tasks.get("conditional-task")
            remote = task_calendar.get_todo_by_uid("conditional-task")
            with remote.edit_icalendar_component() as component:
                component["DESCRIPTION"] = "remote detail preserved"
            remote.save()

            calls.clear()
            merged = tasks.update(stale, summary="Merged after stale snapshot")
            methods = [method for method, _url, _headers in calls]
            if methods.count("PUT") < 2 or methods.count("REPORT") < 2:
                raise AssertionError(
                    "stale fast write did not fall back through fresh-read update path: "
                    f"{methods}"
                )
            current = tasks.get("conditional-task")
            if current.summary != "Merged after stale snapshot":
                raise AssertionError("stale fallback did not apply requested field")
            if current.description != "remote detail preserved":
                raise AssertionError(
                    "stale fallback overwrote an unrelated newer server field"
                )
            if merged.affected.summary != current.summary:
                raise AssertionError("stale fallback returned an inconsistent Task")
            print("PASS: stale ETag fell back to fresh-read merge and preserved remote detail")
            print("REAL CONDITIONAL WRITE ACCEPTANCE: PASS")
            return 0
        finally:
            if inner is not None:
                inner.close()
            radicale.terminate()
            try:
                radicale.wait(timeout=5)
            except subprocess.TimeoutExpired:
                radicale.kill()
                radicale.wait(timeout=5)
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
