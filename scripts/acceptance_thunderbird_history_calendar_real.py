#!/usr/bin/env python3
"""Real Radicale acceptance for Thunderbird History calendar provisioning."""
from __future__ import annotations

from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from caldav.davclient import DAVClient

from caldav_assistant.internal.caldav.library_adapter import LibraryCalDAVAdapter
from caldav_assistant.internal.caldav.setup import CalDAVSetupService
from caldav_assistant.internal.settings.keys import CALDAV_WORKLOG_COLLECTION_URL


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
    client = DAVClient(url=base_url)
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
            adapter = LibraryCalDAVAdapter(Provider(base_url), None)
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
