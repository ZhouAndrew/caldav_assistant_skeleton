#!/usr/bin/env python3
"""Assistant-operated real PTY acceptance for the field regression from 2026-09-13.

This deliberately reproduces the user's path rather than a unit-test abstraction:

1. start real local Radicale and the installed background Assistant;
2. start a real Task with no planned end time;
3. leave the foreground client while the Task remains active;
4. relaunch the installed CLI and require the background snapshot to show that Task;
5. type bare ``1`` at the top-level console prompt;
6. require it to enter Waiting Mode (never ``Unsupported command: 1``);
7. Ctrl-C -> Pause current Task and verify the real CalDAV Work VEVENT is closed.

The script uses a disposable HOME and real installed executable. It does not call Core
services directly for the lifecycle under test.
"""
from __future__ import annotations

from datetime import datetime, timezone
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

from acceptance_conversation_real import (
    _configure_assistant,
    _event_ics,
    _todo_ics,
    _verify_paused_server,
)
from caldav_assistant.internal.caldav.sync import SyncEngine
from caldav_assistant.internal.session import CalDAVSessionService
from caldav_assistant.internal.storage.sqlite import SQLiteCacheRepository, SQLiteStore


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
        except Exception as exc:  # pragma: no cover - diagnostic path
            last = exc
        time.sleep(0.05)
    raise RuntimeError(f"Radicale did not become ready: {last}")


def _cache(home: Path) -> SQLiteCacheRepository:
    store = SQLiteStore(home / ".caldav-assistant" / "assistant.sqlite3")
    store.migrate()
    return SQLiteCacheRepository(store)


def _wait_task_snapshot(home: Path, timeout: float = 10.0) -> None:
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
    raise AssertionError("background Assistant did not publish Task/Event ready snapshot")


def _wait_current_snapshot(home: Path, expected_uid: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    cache = _cache(home)
    key = CalDAVSessionService.CURRENT_WORK_SNAPSHOT_KEY
    while time.monotonic() < deadline:
        value = cache.get(key, None)
        if (
            isinstance(value, dict)
            and value.get("verified_at")
            and value.get("current_task_id") == expected_uid
        ):
            return
        time.sleep(0.05)
    raise AssertionError("current-work ready snapshot was not written after real Start")


def _expect(child: pexpect.spawn, pattern: str, label: str) -> None:
    child.expect(pattern)
    print(f"PASS: {label}")


def _spawn(executable: str, root: Path, env: dict[str, str], transcript) -> pexpect.spawn:
    child = pexpect.spawn(
        executable,
        cwd=str(root),
        env=env,
        encoding="utf-8",
        codec_errors="replace",
        timeout=20,
    )
    child.logfile = transcript
    return child


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    executable = shutil.which("caldav-assistant")
    if not executable:
        raise RuntimeError("installed caldav-assistant executable is not on PATH")

    with tempfile.TemporaryDirectory(prefix="caldav-assistant-relaunch-numeric-") as raw:
        tmp = Path(raw)
        home = tmp / "home"
        storage = tmp / "radicale"
        home.mkdir()
        storage.mkdir()
        port = _free_port()
        base_url = f"http://127.0.0.1:{port}/"
        radicale_log = (tmp / "radicale.log").open("w", encoding="utf-8")
        transcript_path = tmp / "assistant-operated-pty.txt"
        transcript = transcript_path.open("w", encoding="utf-8")
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
        env["HOME"] = str(home)
        env["PYTHONUNBUFFERED"] = "1"
        first = None
        second = None
        try:
            _wait_http(base_url)
            client = DAVClient(url=base_url, username="acceptance", password="acceptance")
            principal = client.principal()
            calendar = principal.make_calendar(name="AssistantOperated")
            now = datetime.now(timezone.utc)
            calendar.save_todo(_todo_ics(now))
            calendar.save_event(_event_ics(now))
            calendar_url = str(calendar.url)
            _configure_assistant(home, base_url, calendar_url)

            started = subprocess.run(
                [executable, "background", "start"],
                cwd=root,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=10,
            )
            if started.returncode != 0:
                raise AssertionError(f"background start failed:\n{started.stdout}")
            _wait_task_snapshot(home)
            print("PASS: real background Assistant prepared Task/Event snapshot")

            # First foreground session: start real work, then leave without pausing.
            first = _spawn(executable, root, env, transcript)
            _expect(first, "Console ready", "first installed CLI reached console")
            first.sendline("")
            _expect(first, "What do you want to do", "first guided home opened")
            first.sendline("1")
            _expect(
                first,
                "Choose by number; type /keyword to search",
                "primary action entered Task picker",
            )
            _expect(first, "Choose a Task to work on", "Task chooser shown")
            first.sendline("1")
            _expect(first, "How long do you want to work", "Task selected")
            first.sendline("7")
            _expect(first, "Planned end: not set", "open-ended work period selected")
            _expect(first, "Start now", "real Start confirmation shown")
            first.sendline("")
            _expect(first, "Opening CalDAV Work interval", "real CalDAV Start began")
            _expect(first, "Waiting Mode", "first session entered Waiting Mode")
            _wait_current_snapshot(home, TASK_UID)
            print("PASS: successful real Start immediately updated current-work ready snapshot")
            first.sendline("q")
            _expect(
                first,
                "Leaving the foreground client. Current Task and background Assistant keep running.",
                "foreground exited while real Task remained active",
            )
            first.expect(pexpect.EOF)
            first.close()
            first = None

            # Second foreground session is the exact regression path from the field.
            t0 = time.monotonic()
            second = _spawn(executable, root, env, transcript)
            _expect(second, "Reading current work, Tasks and Events", "relaunch startup began")
            _expect(second, "Now", "relaunch rendered Now")
            _expect(second, r"▶ English writing acceptance", "ready snapshot rendered current Task")
            _expect(second, "Console ready", "relaunch reached top-level console")
            startup_elapsed = time.monotonic() - t0
            print(f"PASS: relaunch reached console in {startup_elapsed:.2f}s")

            numeric_started = time.monotonic()
            second.sendline("1")
            _expect(second, "Waiting Mode", "bare top-level 1 selected Return to Waiting Mode")
            numeric_elapsed = time.monotonic() - numeric_started
            print(f"PASS: bare numeric home selection completed in {numeric_elapsed:.2f}s")

            second.sendcontrol("c")
            _expect(second, "Current Task — English writing acceptance", "Ctrl-C opened Task decision menu")
            _expect(second, "Pause current Task", "Pause option visible")
            second.sendline("2")
            _expect(second, "Working: pause", "Pause selected by number")
            _expect(second, "CalDAV Work interval closed", "real Work VEVENT closed")
            _expect(second, "Console ready", "Pause returned to console")
            _verify_paused_server(calendar)
            second.sendline("exit")
            second.expect(pexpect.EOF)
            second.close()
            second = None

            transcript.flush()
            text = transcript_path.read_text(encoding="utf-8", errors="replace")
            forbidden = (
                "Unsupported command: 1",
                "Background snapshot cannot authorize Start",
                "checking live current work before Start",
                "Traceback (most recent call last)",
            )
            for marker in forbidden:
                if marker in text:
                    raise AssertionError(f"field regression marker reappeared: {marker}")
            print("PASS: no duplicate UI Start precheck or numeric-command regression appeared")
            print("ASSISTANT-OPERATED RELAUNCH + NUMERIC CURRENT-WORK ACCEPTANCE: PASS")
            return 0
        finally:
            for child in (first, second):
                if child is not None and child.isalive():
                    child.close(force=True)
            if not transcript.closed:
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
