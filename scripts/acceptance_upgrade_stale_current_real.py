#!/usr/bin/env python3
"""Real upgrade/restart acceptance for stale current-work cache safety.

This reproduces the field failure from 2026-09-19 with real processes and CalDAV:

1. create an isolated HOME and real Radicale;
2. let daemon A verify "no current Task" and persist that ready snapshot;
3. create a real open Assistant Work VEVENT outside the daemon;
4. make CalDAV temporarily hang and change package source so the installed CLI must
   replace daemon A with daemon B;
5. require the CLI to treat daemon A's cached None as UNKNOWN, never as permission to
   offer Start;
6. restore Radicale and require daemon B's independent ready lane to discover the
   real current Task without a manual cache cleanup;
7. relaunch the installed CLI, enter Waiting Mode, pause through the real UI, and
   verify the Work VEVENT is closed on the server;
8. clean every child process, daemon, source probe and temporary directory.

The lifecycle under test always travels through the installed executable and real
Local IPC/Core/CalDAV path. Direct SQLite access is inspection only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread
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

from acceptance_conversation_real import (
    _configure_assistant,
    _event_ics,
    _ical_stamp,
    _todo_ics,
    _verify_paused_server,
)
from caldav_assistant.internal.caldav.sync import SyncEngine
from caldav_assistant.internal.session import CalDAVSessionService
from caldav_assistant.internal.settings.keys import CALDAV_WORKLOG_COLLECTION_URL
from caldav_assistant.internal.settings.service import SettingsService
from caldav_assistant.internal.storage.sqlite import (
    SQLiteCacheRepository,
    SQLiteKeyValueRepository,
    SQLiteStore,
)


TASK_UID = "accept-task-english-writing"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_http(url: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status < 500:
                    return
        except Exception as exc:
            last = exc
        time.sleep(0.05)
    raise RuntimeError(f"Radicale did not become ready: {last}")


def _spawn_radicale(root: Path, storage: Path, port: int, log):
    return subprocess.Popen(
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


def _stop_process(process) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


class BlackholeHTTP:
    """Accept TCP connections but never answer, forcing the 3s startup cache path."""

    def __init__(self, port: int):
        self.port = port
        self.stop_event = Event()
        self.listener = None
        self.clients = []
        self.thread = None

    def start(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", self.port))
        listener.listen()
        listener.settimeout(0.2)
        self.listener = listener

        def run() -> None:
            while not self.stop_event.is_set():
                try:
                    client, _ = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                client.settimeout(0.2)
                self.clients.append(client)
            for client in self.clients:
                try:
                    client.close()
                except OSError:
                    pass

        self.thread = Thread(target=run, name="acceptance-http-blackhole", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.listener is not None:
            try:
                self.listener.close()
            except OSError:
                pass
        for client in self.clients:
            try:
                client.close()
            except OSError:
                pass
        if self.thread is not None:
            self.thread.join(timeout=2)


def _cache(home: Path) -> SQLiteCacheRepository:
    store = SQLiteStore(home / ".caldav-assistant" / "assistant.sqlite3")
    store.migrate()
    return SQLiteCacheRepository(store)


def _wait_task_snapshot(home: Path, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    cache = _cache(home)
    while time.monotonic() < deadline:
        value = cache.get(SyncEngine.SNAPSHOT_KEY, None)
        if (
            isinstance(value, dict)
            and value.get("synced_at")
            and isinstance(value.get("tasks"), list)
            and value.get("tasks")
            and isinstance(value.get("events"), list)
            and value.get("events")
        ):
            return
        time.sleep(0.05)
    raise AssertionError("background Assistant did not publish Task/Event snapshot")


def _wait_current_snapshot(
    home: Path,
    expected_uid: str | None,
    *,
    different_from: str | None = None,
    timeout: float = 25.0,
) -> dict:
    deadline = time.monotonic() + timeout
    cache = _cache(home)
    key = CalDAVSessionService.CURRENT_WORK_SNAPSHOT_KEY
    last = None
    while time.monotonic() < deadline:
        value = cache.get(key, None)
        last = value
        if isinstance(value, dict):
            generation = str(value.get("producer_generation") or "")
            if (
                value.get("verified_at")
                and value.get("current_task_id") == expected_uid
                and generation
                and (different_from is None or generation != different_from)
            ):
                return value
        time.sleep(0.05)
    raise AssertionError(
        f"current-work snapshot did not become {expected_uid!r}; last={last!r}"
    )


def _configure_worklog(home: Path, calendar_url: str) -> None:
    store = SQLiteStore(home / ".caldav-assistant" / "assistant.sqlite3")
    store.migrate()
    settings = SettingsService(SQLiteKeyValueRepository(store, "settings"))
    settings.set(CALDAV_WORKLOG_COLLECTION_URL, calendar_url)


def _open_work_ics(now: datetime) -> str:
    start = now - timedelta(minutes=5)
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//CalDAV Assistant Upgrade Acceptance//EN",
            "BEGIN:VEVENT",
            "UID:accept-upgrade-open-work",
            f"DTSTAMP:{_ical_stamp(now)}",
            f"DTSTART:{_ical_stamp(start)}",
            "SUMMARY:Work — English writing acceptance",
            "DESCRIPTION:CalDAV Assistant Work Segment\\nTask-UID: accept-task-english-writing",
            "CATEGORIES:caldav-assistant-work,caldav-assistant-work-open",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )


def _spawn_cli(executable: str, root: Path, env: dict[str, str], transcript):
    child = pexpect.spawn(
        executable,
        cwd=str(root),
        env=env,
        encoding="utf-8",
        codec_errors="replace",
        timeout=25,
    )
    child.logfile = transcript
    return child


def _expect(child, pattern: str, label: str) -> None:
    child.expect(pattern)
    print(f"PASS: {label}")


def _background(executable: str, root: Path, env: dict[str, str], action: str):
    return subprocess.run(
        [executable, "background", action],
        cwd=root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10,
    )


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    executable = shutil.which("caldav-assistant")
    if not executable:
        raise RuntimeError("installed caldav-assistant executable is not on PATH")

    probe = root / "caldav_assistant" / "_acceptance_runtime_generation_probe.py"
    if probe.exists():
        raise RuntimeError(f"refusing to overwrite existing acceptance probe: {probe}")

    temp_path = None
    transcript_target = os.environ.get(
        "CALDAV_ASSISTANT_UPGRADE_ACCEPTANCE_TRANSCRIPT",
        "",
    ).strip()

    with tempfile.TemporaryDirectory(prefix="caldav-assistant-upgrade-current-") as raw:
        temp_path = Path(raw)
        home = temp_path / "home"
        storage = temp_path / "radicale"
        home.mkdir()
        storage.mkdir()
        port = _free_port()
        base_url = f"http://127.0.0.1:{port}/"
        radicale_log = (temp_path / "radicale.log").open("w", encoding="utf-8")
        transcript_path = (
            Path(transcript_target)
            if transcript_target
            else temp_path / "upgrade-current-transcript.txt"
        )
        transcript = transcript_path.open("w", encoding="utf-8")
        radicale = None
        blackhole = None
        first = None
        second = None
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PYTHONUNBUFFERED"] = "1"

        try:
            radicale = _spawn_radicale(root, storage, port, radicale_log)
            _wait_http(base_url)

            client = DAVClient(
                url=base_url,
                username="acceptance",
                password="acceptance",
            )
            principal = client.principal()
            calendar = principal.make_calendar(name="UpgradeCurrent")
            now = datetime.now(timezone.utc)
            calendar.save_todo(
                _todo_ics(now).replace(
                    "STATUS:NEEDS-ACTION",
                    "STATUS:IN-PROCESS",
                )
            )
            calendar.save_event(_event_ics(now))
            calendar_url = str(calendar.url)
            _configure_assistant(home, base_url, calendar_url)
            _configure_worklog(home, calendar_url)

            started = _background(executable, root, env, "start")
            if started.returncode != 0:
                raise AssertionError(f"background start failed:\n{started.stdout}")
            _wait_task_snapshot(home)
            old_ready = _wait_current_snapshot(home, None)
            old_generation = str(old_ready["producer_generation"])
            print("PASS: daemon A published verified-none current-work snapshot")

            # External/server truth changes after daemon A's verified-none snapshot.
            calendar.save_event(_open_work_ics(datetime.now(timezone.utc)))
            print("PASS: real CalDAV now contains an open Work VEVENT")

            # Force installed startup to use the cache route while replacing stale
            # daemon code, exactly where the field regression used old current=None.
            _stop_process(radicale)
            radicale = None
            blackhole = BlackholeHTTP(port)
            blackhole.start()
            probe.write_text(
                "# runtime identity probe for acceptance; removed in finally\n",
                encoding="utf-8",
            )

            first = _spawn_cli(executable, root, env, transcript)
            _expect(
                first,
                "Background service code changed; restarted the stale daemon automatically",
                "source change forced automatic stale-daemon replacement",
            )
            _expect(first, "Now", "replacement CLI rendered Now")
            _expect(
                first,
                "not yet verified by this background Assistant generation",
                "old verified-none snapshot became UNKNOWN after daemon replacement",
            )
            _expect(first, "Console ready", "CLI remained usable from stale Task/Event cache")
            first.sendline("")
            _expect(first, "What do you want to do", "guided home opened while current work unknown")
            _expect(first, "Refresh current work", "unknown state exposes safe refresh action")
            first.sendline("0")
            first.sendline("exit")
            first.expect(pexpect.EOF)
            first.close()
            first = None

            transcript.flush()
            early_text = transcript_path.read_text(encoding="utf-8", errors="replace")
            forbidden_early = (
                "Background snapshot has no current Task",
                "Start recommended Task",
                "Choose a Task and start",
                "Ready to start",
            )
            for marker in forbidden_early:
                if marker in early_text:
                    raise AssertionError(
                        f"unsafe Start/no-current marker appeared while current work was UNKNOWN: {marker}"
                    )
            print("PASS: UNKNOWN never became fake empty/current-none Start authorization")

            blackhole.stop()
            blackhole = None
            radicale = _spawn_radicale(root, storage, port, radicale_log)
            _wait_http(base_url)

            new_ready = _wait_current_snapshot(
                home,
                TASK_UID,
                different_from=old_generation,
                timeout=25.0,
            )
            print(
                "PASS: daemon B independently refreshed current work after CalDAV recovered "
                f"(generation {new_ready['producer_generation']})"
            )

            second = _spawn_cli(executable, root, env, transcript)
            _expect(second, "Now", "relaunch rendered Now after background recovery")
            _expect(
                second,
                r"▶ English writing acceptance",
                "relaunch rendered the real current Task",
            )
            _expect(second, "Console ready", "relaunch reached console")
            second.sendline("")
            _expect(second, "What do you want to do", "guided home reopened")
            _expect(
                second,
                "Return to Waiting Mode — English writing acceptance",
                "home primary action recovered to Waiting Mode",
            )
            second.sendline("1")
            _expect(second, "Waiting Mode", "real current Task entered Waiting Mode")
            second.sendcontrol("c")
            _expect(
                second,
                "Current Task — English writing acceptance",
                "Ctrl-C opened current Task decision menu",
            )
            _expect(second, "Pause current Task", "Pause action is available")
            second.sendline("2")
            _expect(second, "CalDAV Work interval closed", "real Work VEVENT was closed")
            _expect(second, "Console ready", "Pause returned to console")
            second.sendline("exit")
            second.expect(pexpect.EOF)
            second.close()
            second = None

            verify_client = DAVClient(
                url=base_url,
                username="acceptance",
                password="acceptance",
            )
            verify_calendar = verify_client.principal().calendars()[0]
            _verify_paused_server(verify_calendar)
            paused_ready = _wait_current_snapshot(
                home,
                None,
                different_from=old_generation,
                timeout=5.0,
            )
            assert paused_ready["current_task_id"] is None
            print("PASS: authoritative Pause immediately published verified-none in daemon B")

            transcript.flush()
            full_text = transcript_path.read_text(encoding="utf-8", errors="replace")
            for marker in (
                "Unsupported command: 1",
                "Traceback (most recent call last)",
                "ValidationError: Another Task is currently being worked on",
            ):
                if marker in full_text:
                    raise AssertionError(f"field regression marker reappeared: {marker}")

            print("UPGRADE + STALE CURRENT-WORK REAL ACCEPTANCE: PASS")
        finally:
            for child in (first, second):
                if child is not None and child.isalive():
                    child.close(force=True)
            if blackhole is not None:
                blackhole.stop()
            if not transcript.closed:
                transcript.flush()
                transcript.close()
            try:
                _background(executable, root, env, "stop")
            except Exception:
                pass
            _stop_process(radicale)
            if probe.exists():
                probe.unlink()
            radicale_log.close()

            status = _background(executable, root, env, "status")
            if status.returncode != 0 or "Background service: Stopped" not in status.stdout:
                raise AssertionError(
                    "acceptance cleanup left the background Assistant running:\n"
                    + status.stdout
                )
            if probe.exists():
                raise AssertionError("acceptance source probe was not removed")
            print("PASS: acceptance teardown stopped daemon/Radicale and removed source probe")

    assert temp_path is not None and not temp_path.exists()
    print("PASS: temporary HOME, SQLite, sockets and Radicale storage were removed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
