#!/usr/bin/env python3
"""Real RFC 6578 incremental-sync acceptance against disposable Radicale.

This complements the installed CLI human-path suite: it proves the production
LibraryCalDAVAdapter + CollectionRoutingCalDAVAdapter + SyncEngine path actually uses
Radicale sync tokens after initialization and does not silently fall back to Task/Event
full scans on a no-change or changed-resource cycle.
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
    LibraryCalDAVAdapter,
    SyncEngine,
)


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


def _todo(uid: str, summary: str, now: datetime) -> str:
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//CalDAV Assistant Sync Token Acceptance//EN",
            "BEGIN:VTODO",
            f"UID:{uid}",
            f"DTSTAMP:{_stamp(now)}",
            f"DUE:{_stamp(now + timedelta(hours=2))}",
            f"SUMMARY:{summary}",
            "STATUS:NEEDS-ACTION",
            "END:VTODO",
            "END:VCALENDAR",
            "",
        ]
    )


def _event(uid: str, summary: str, now: datetime) -> str:
    start = now + timedelta(hours=1)
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//CalDAV Assistant Sync Token Acceptance//EN",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{_stamp(now)}",
            f"DTSTART:{_stamp(start)}",
            f"DTEND:{_stamp(start + timedelta(minutes=30))}",
            f"SUMMARY:{summary}",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )


def _forbid_full_scan(*args, **kwargs):
    raise AssertionError("RFC 6578 cycle attempted a full Task/Event collection scan")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="caldav-assistant-sync-token-") as raw_tmp:
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
            writer = DAVClient(url=base_url, username="sync", password="sync")
            principal = writer.principal()
            task_calendar = principal.make_calendar(name="Tasks")
            event_calendar = principal.make_calendar(name="Events")
            now = datetime.now(timezone.utc)
            task_calendar.save_todo(_todo("sync-task-1", "Initial Task", now))
            event = event_calendar.save_event(_event("sync-event-1", "Initial Event", now))
            print("PASS: real Radicale seeded with separate Task/Event collections")

            inner = LibraryCalDAVAdapter(
                Provider(base_url),
                {"username": "sync", "password": "sync"},
            )
            routed = CollectionRoutingCalDAVAdapter(
                inner,
                task_collection_url=lambda: str(task_calendar.url),
                event_collection_url=lambda: str(event_calendar.url),
            )
            cache = MemoryCache()
            engine = SyncEngine(routed, cache)

            first = engine.incremental_sync()
            if first["effective_mode"] != "full-scan":
                raise AssertionError(f"unexpected initialization mode: {first}")
            token_state = cache.get(SyncEngine.TOKEN_KEY)
            if not isinstance(token_state, dict) or token_state.get("supported") is not True:
                raise AssertionError(f"real Radicale sync-token was not seeded: {token_state}")
            if len(token_state.get("tokens") or {}) != 2:
                raise AssertionError(f"expected two opaque collection tokens: {token_state}")
            print("PASS: initialization seeded real opaque sync tokens before full snapshot")

            # Prove no-change sync cannot quietly call the full Task/Event readers.
            routed.list_tasks = _forbid_full_scan
            routed.list_events = _forbid_full_scan
            second = engine.incremental_sync()
            if second["effective_mode"] != "sync-token":
                raise AssertionError(f"no-change cycle did not use RFC 6578: {second}")
            if any(second["changes"][kind][bucket] for kind in ("tasks", "events") for bucket in ("added", "updated", "removed")):
                raise AssertionError(f"no-change cycle reported changes: {second}")
            print("PASS: no-change cycle used sync-token with zero full collection scans")

            # Mutate through a separate CalDAV client, including a deletion.  The
            # next cycle must merge only those deltas while full readers stay banned.
            task_calendar.save_todo(_todo("sync-task-2", "Added Task", now + timedelta(minutes=1)))
            event.delete()
            third = engine.incremental_sync()
            if third["effective_mode"] != "sync-token":
                raise AssertionError(f"changed cycle did not use RFC 6578: {third}")
            if third["changes"]["tasks"]["added"] != ["sync-task-2"]:
                raise AssertionError(f"Task delta mismatch: {third}")
            if third["changes"]["events"]["removed"] != ["sync-event-1"]:
                raise AssertionError(f"Event deletion delta mismatch: {third}")
            if sorted(task.id for task in engine.cached_tasks()) != ["sync-task-1", "sync-task-2"]:
                raise AssertionError("incremental Task snapshot merge is incorrect")
            if engine.cached_events():
                raise AssertionError("incremental Event deletion was not removed from cache")
            print("PASS: real add/delete deltas merged without Task/Event full scans")
            print("REAL RFC6578 SYNC TOKEN ACCEPTANCE: PASS")
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
