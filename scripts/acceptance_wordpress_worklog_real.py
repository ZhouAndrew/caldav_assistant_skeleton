#!/usr/bin/env python3
"""Real installed-CLI acceptance for compact WordPress work-session logging.

This is intentionally separate from pytest.  It starts a real local Radicale server,
creates a real VTODO, configures the production SQLite settings/outbox, invokes the
installed ``caldav-assistant`` executable through start/pause/resume/pause, and then
checks the actual durable WordPress Outbox payloads produced by those human commands.

A WordPress server is deliberately not required here: work-session hooks must queue
reliably without waiting for the WordPress transport.  WP-CLI rendering itself has a
separate regression test for the exact visible paragraph.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

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
    WORDPRESS_WORKLOG_STYLE,
    WORDPRESS_WORKLOG_TEMPLATE,
)
from caldav_assistant.internal.settings.service import SettingsService
from caldav_assistant.internal.storage.sqlite import (
    SQLiteKeyValueRepository,
    SQLiteOutboxRepository,
    SQLiteStore,
)


TASK_UID = "accept-compact-wordpress-worklog"
TASK_NAME = "Anki acceptance"
CUSTOM_TEMPLATE = "{task} | {duration_minutes}m | {start}>{end}"


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
    start = now + timedelta(minutes=1)
    due = now + timedelta(hours=1)
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//CalDAV Assistant Worklog Acceptance//EN",
            "BEGIN:VTODO",
            f"UID:{TASK_UID}",
            f"DTSTAMP:{_ical_stamp(now)}",
            f"DTSTART:{_ical_stamp(start)}",
            f"DUE:{_ical_stamp(due)}",
            f"SUMMARY:{TASK_NAME}",
            "STATUS:NEEDS-ACTION",
            "PRIORITY:1",
            "END:VTODO",
            "END:VCALENDAR",
            "",
        ]
    )


def _state(home: Path):
    store = SQLiteStore(home / ".caldav-assistant" / "assistant.sqlite3")
    store.migrate()
    return store


def _configure(home: Path, base_url: str, calendar_url: str) -> None:
    state_dir = home / ".caldav-assistant"
    state_dir.mkdir(parents=True, exist_ok=True)
    settings = SettingsService(SQLiteKeyValueRepository(_state(home), "settings"))
    settings.set(CALDAV_BASE_URL, base_url)
    settings.set(
        CALDAV_CREDENTIALS,
        {"username": "acceptance", "password": "acceptance"},
    )
    settings.set(CALDAV_TASK_COLLECTION_URL, calendar_url)
    settings.set(CALDAV_EVENT_COLLECTION_URL, calendar_url)
    settings.set(CALDAV_WORKLOG_COLLECTION_URL, calendar_url)
    settings.set(NOTIFICATIONS_ENABLED, False)
    settings.set(WORDPRESS_ENABLED, True)
    settings.set(WORDPRESS_WORKLOG_STYLE, "compact")
    settings.set(
        EXTENSIONS_ENABLED,
        {"software_intro": False, "wordpress_work_session_log": True},
    )


def _pending_payloads(home: Path) -> list[dict]:
    return list(SQLiteOutboxRepository(_state(home)).pending())


def _log_payloads(home: Path) -> list[dict]:
    values = []
    for item in _pending_payloads(home):
        payload = item.get("payload") if isinstance(item, dict) else None
        if not isinstance(payload, dict) or payload.get("operation") != "create_log":
            continue
        values.append(payload)
    return values


def _run_cli(executable: str, env: dict[str, str], *args: str) -> str:
    result = subprocess.run(
        [executable, *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=35,
        check=False,
    )
    output = (result.stdout or "") + (result.stderr or "")
    print(f"$ caldav-assistant {' '.join(args)}")
    print(output.rstrip())
    if result.returncode != 0:
        raise AssertionError(
            f"CLI command failed with {result.returncode}: {' '.join(args)}\n{output}"
        )
    return output


def _assert_default_compact(payload: dict) -> None:
    args = payload.get("args") or {}
    text = str(args.get("text") or "")
    metadata = args.get("metadata") or {}
    pattern = rf"^\d{{1,2}}:\d{{2}}-\d{{1,2}}:\d{{2}} {re.escape(TASK_NAME)}$"
    if re.fullmatch(pattern, text) is None:
        raise AssertionError(f"Default WordPress worklog is not one compact line: {text!r}")
    forbidden = ("Task UID", "Planned start", "Priority", "Actual time", "Action:")
    if any(item in text for item in forbidden):
        raise AssertionError(f"Machine metadata leaked into human worklog: {text!r}")
    if metadata.get("_show_clock") is not False:
        raise AssertionError("Compact range did not suppress the transport's duplicate clock")
    if metadata.get("title"):
        raise AssertionError("Compact range unexpectedly has a verbose entry title")
    print(f"PASS: real Outbox contains compact human line: {text}")


def _assert_custom(payload: dict) -> None:
    args = payload.get("args") or {}
    text = str(args.get("text") or "")
    pattern = rf"^{re.escape(TASK_NAME)} \| \d+m \| \d{{1,2}}:\d{{2}}>\d{{1,2}}:\d{{2}}$"
    if re.fullmatch(pattern, text) is None:
        raise AssertionError(f"Custom per-user worklog template was not applied: {text!r}")
    print(f"PASS: active user's custom template is applied: {text}")


def main() -> int:
    executable = shutil.which("caldav-assistant")
    if not executable:
        raise RuntimeError("Installed caldav-assistant executable is not on PATH")

    with tempfile.TemporaryDirectory(prefix="caldav-worklog-real-") as raw_tmp:
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
            stdout=radicale_log,
            stderr=subprocess.STDOUT,
        )
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PYTHONUNBUFFERED"] = "1"
        try:
            _wait_http(base_url)
            client = DAVClient(url=base_url, username="acceptance", password="acceptance")
            calendar = client.principal().make_calendar(name="Acceptance")
            calendar.save_todo(_todo_ics(datetime.now(timezone.utc)))
            _configure(home, base_url, str(calendar.url))
            print("PASS: real Radicale + production SQLite settings/outbox configured")

            _run_cli(executable, env, "start", TASK_NAME)
            time.sleep(0.2)
            _run_cli(executable, env, "pause")

            compact_logs = _log_payloads(home)
            if len(compact_logs) != 1:
                raise AssertionError(
                    f"Expected one queued worklog after first pause, got {len(compact_logs)}"
                )
            _assert_default_compact(compact_logs[0])

            style_result = _run_cli(
                executable,
                env,
                "settings",
                "set",
                WORDPRESS_WORKLOG_STYLE,
                "custom",
            )
            if f"{WORDPRESS_WORKLOG_STYLE} = custom" not in style_result:
                raise AssertionError("Installed CLI did not confirm custom worklog style")
            template_result = _run_cli(
                executable,
                env,
                "settings",
                "set",
                WORDPRESS_WORKLOG_TEMPLATE,
                CUSTOM_TEMPLATE,
            )
            if CUSTOM_TEMPLATE not in template_result:
                raise AssertionError("Installed CLI did not confirm custom worklog template")
            print("PASS: per-user worklog customization is reachable through the real Settings CLI")

            _run_cli(executable, env, "resume")
            time.sleep(0.2)
            _run_cli(executable, env, "pause")

            logs = _log_payloads(home)
            if len(logs) != 2:
                raise AssertionError(
                    f"Expected two closed-segment logs after second pause, got {len(logs)}"
                )
            _assert_custom(logs[-1])
            print("PASS: start/resume themselves created no extra WordPress log entries")
            print("PASS: real installed CLI compact/custom WordPress worklog acceptance complete")
        finally:
            try:
                subprocess.run(
                    [executable, "background", "stop"],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=10,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
