#!/usr/bin/env python3
"""Real Radicale acceptance for Thunderbird History calendar provisioning."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from caldav.davclient import DAVClient

from caldav_assistant.api import Task
from caldav_assistant.internal.caldav import CollectionRoutingCalDAVAdapter
from caldav_assistant.internal.caldav.library_adapter import LibraryCalDAVAdapter
from caldav_assistant.internal.caldav.setup import CalDAVSetupService
from caldav_assistant.internal.settings.keys import CALDAV_WORKLOG_COLLECTION_URL
from caldav_assistant.internal.worklog import WorkLogService


class Provider:
    def __init__(self, url: str):
        self.url = url

    def get_base_url(self) -> str:
        return self.url


class Settings:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        return value

    def delete(self, key):
        self.values.pop(key, None)


class Discovery:
    pass


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
        except Exception as exc:
            last_error = exc
        time.sleep(0.1)
    raise RuntimeError(f"Radicale did not become ready: {last_error}")


def _matching_calendars(base_url: str):
    client = DAVClient(url=base_url, username="work", password="work")
    principal = client.principal()
    matches = []
    for calendar in principal.get_calendars():
        try:
            name = calendar.get_display_name()
        except Exception:
            name = getattr(calendar, "name", "")
        if str(name or "").strip() == "CalDAV Assistant History":
            matches.append(calendar)
    return client, matches


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="caldav-assistant-thunderbird-history-") as raw_tmp:
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

        adapter = None
        verification_client = None
        try:
            _wait_http(base_url)
            settings = Settings()
            adapter = LibraryCalDAVAdapter(
                Provider(base_url),
                {"username": "work", "password": "work"},
            )
            setup = CalDAVSetupService(settings, Discovery(), adapter)

            first = setup.ensure_worklog_collection()
            if first.get("created") is not True:
                raise AssertionError(f"first setup did not report creation: {first!r}")
            configured = settings.get(CALDAV_WORKLOG_COLLECTION_URL)
            if not configured or configured != first.get("url"):
                raise AssertionError("worklog collection URL was not persisted")
            print("PASS: first setup created and configured CalDAV Assistant History")

            verification_client, matches = _matching_calendars(base_url)
            if len(matches) != 1:
                raise AssertionError(f"expected one History calendar, got {len(matches)}")
            supported = {str(item).upper() for item in matches[0].get_supported_components()}
            if "VEVENT" not in supported:
                raise AssertionError(f"History calendar does not support VEVENT: {supported}")
            print("PASS: real server calendar exists and supports VEVENT")

            second = setup.ensure_worklog_collection()
            if second.get("created") is not False:
                raise AssertionError(f"configured reuse should not create: {second!r}")

            # Simulate local settings loss. The server-side calendar must still be
            # found by display name and reused instead of duplicated.
            settings.delete(CALDAV_WORKLOG_COLLECTION_URL)
            third = setup.ensure_worklog_collection()
            if third.get("created") is not False:
                raise AssertionError(f"server-side reuse should report created=False: {third!r}")

            verification_client.close()
            verification_client, matches = _matching_calendars(base_url)
            if len(matches) != 1:
                raise AssertionError(
                    f"idempotent setup duplicated History calendar: {len(matches)} copies"
                )
            print("PASS: settings loss reused the existing server calendar without duplication")

            # Prove integration links are written to the History VEVENT itself,
            # even when a separate ordinary Event calendar is configured.
            principal = verification_client.principal()
            normal_events = principal.make_calendar(name="Normal Events")
            routed = CollectionRoutingCalDAVAdapter(
                adapter,
                task_collection_url=lambda: None,
                event_collection_url=lambda: str(normal_events.url),
            )
            worklog = WorkLogService(
                routed,
                lambda: settings.get(CALDAV_WORKLOG_COLLECTION_URL),
            )
            task = Task(id="link-task", summary="Link Test")
            started_at = datetime(2026, 9, 27, 9, 20, tzinfo=timezone.utc)
            ended_at = datetime(2026, 9, 27, 10, 5, tzinfo=timezone.utc)
            opened = worklog.start_segment(task, at=started_at, snapshot=())
            closed = worklog.close_segment(task, at=ended_at, snapshot=(opened,))

            wordpress_url = "https://example.test/log/2026-09-27/"
            attachment_url = "https://example.test/uploads/evidence.pdf"
            worklog.add_references(
                closed.id,
                wordpress_url=wordpress_url,
                attachment_urls=[attachment_url],
            )

            history_resource = matches[0].get_event_by_uid(closed.id)
            component = history_resource.get_icalendar_component()
            if str(component.get("URL") or "") != wordpress_url:
                raise AssertionError(
                    f"History VEVENT URL mismatch: {component.get('URL')!r}"
                )
            raw_attach = component.get("ATTACH")
            attach_values = (
                {str(value) for value in raw_attach}
                if isinstance(raw_attach, (list, tuple))
                else {str(raw_attach)} if raw_attach is not None else set()
            )
            if attachment_url not in attach_values:
                raise AssertionError(
                    f"History VEVENT ATTACH missing {attachment_url!r}: {attach_values!r}"
                )
            description = str(component.get("DESCRIPTION") or "")
            if f"WordPress: {wordpress_url}" not in description:
                raise AssertionError("History VEVENT DESCRIPTION lost WordPress reference")
            if f"Attachment: {attachment_url}" not in description:
                raise AssertionError("History VEVENT DESCRIPTION lost attachment reference")
            if list(normal_events.get_events()):
                raise AssertionError(
                    "WordPress references leaked into the ordinary Event calendar"
                )
            print("PASS: History VEVENT stores URL + ATTACH and ordinary Event calendar stays untouched")

            print("REAL THUNDERBIRD HISTORY CALENDAR ACCEPTANCE: PASS")
            return 0
        finally:
            if verification_client is not None:
                verification_client.close()
            if adapter is not None:
                adapter.close()
            radicale.terminate()
            try:
                radicale.wait(timeout=5)
            except subprocess.TimeoutExpired:
                radicale.kill()
                radicale.wait(timeout=5)
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
