from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

import pexpect
from caldav.davclient import DAVClient

from caldav_assistant.internal.settings.keys import (
    AGENDA_UPCOMING_HOURS,
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


TASK_UID = "manual-pr62-task"
TASK_TITLE = "Manual PR62 acceptance task"
TRANSCRIPT: list[str] = []


def record(text: str) -> None:
    TRANSCRIPT.append(text)
    sys.stdout.write(text)
    sys.stdout.flush()


def mark(message: str) -> None:
    record(f"\n[RELAY] {message}\n")


def stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_http(url: str, timeout: float = 15.0) -> None:
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


def seed_and_configure(home: Path, base_url: str):
    client = DAVClient(url=base_url, username="acceptance", password="acceptance")
    principal = client.principal()
    calendar = principal.make_calendar(name="Manual PR62 Acceptance")
    now = datetime.now(timezone.utc)
    calendar.save_todo(
        "\r\n".join(
            [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "PRODID:-//Assistant Operated PR62 Acceptance//EN",
                "BEGIN:VTODO",
                f"UID:{TASK_UID}",
                f"DTSTAMP:{stamp(now)}",
                f"DTSTART:{stamp(now + timedelta(minutes=2))}",
                f"DUE:{stamp(now + timedelta(hours=2))}",
                f"SUMMARY:{TASK_TITLE}",
                "STATUS:NEEDS-ACTION",
                "PRIORITY:1",
                "END:VTODO",
                "END:VCALENDAR",
                "",
            ]
        )
    )
    calendar.save_event(
        "\r\n".join(
            [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "PRODID:-//Assistant Operated PR62 Acceptance//EN",
                "BEGIN:VEVENT",
                "UID:manual-pr62-event",
                f"DTSTAMP:{stamp(now)}",
                f"DTSTART:{stamp(now + timedelta(hours=3))}",
                f"DTEND:{stamp(now + timedelta(hours=4))}",
                "SUMMARY:Manual PR62 acceptance event",
                "END:VEVENT",
                "END:VCALENDAR",
                "",
            ]
        )
    )

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
    collection_url = str(calendar.url)
    settings.set(CALDAV_TASK_COLLECTION_URL, collection_url)
    settings.set(CALDAV_EVENT_COLLECTION_URL, collection_url)
    settings.set(CALDAV_WORKLOG_COLLECTION_URL, collection_url)
    settings.set(AGENDA_UPCOMING_HOURS, 24)
    settings.set(NOTIFICATIONS_ENABLED, False)
    settings.set(WORDPRESS_ENABLED, False)
    settings.set(
        EXTENSIONS_ENABLED,
        {"software_intro": False, "wordpress_work_session_log": False},
    )
    return calendar


def read_control() -> dict[str, object]:
    control_url = os.environ["CONTROL_URL"]
    control_ref = os.environ["CONTROL_REF"]
    token = os.environ["GITHUB_TOKEN"]
    separator = "&" if "?" in control_url else "?"
    url = f"{control_url}{separator}ref={urllib.parse.quote(control_ref, safe='')}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Cache-Control": "no-cache",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.load(response)
    raw = base64.b64decode(payload["content"]).decode("utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("control file must contain an object")
    return value


def publish_status(seq: int, phase: str, command: str) -> None:
    status_url = os.environ["STATUS_URL"]
    control_ref = os.environ["CONTROL_REF"]
    token = os.environ["GITHUB_TOKEN"]
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    separator = "&" if "?" in status_url else "?"
    read_url = f"{status_url}{separator}ref={urllib.parse.quote(control_ref, safe='')}"
    sha = None
    try:
        with urllib.request.urlopen(
            urllib.request.Request(read_url, headers=headers), timeout=5
        ) as response:
            current = json.load(response)
        sha = current.get("sha")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise

    status = {
        "seq": seq,
        "phase": phase,
        "command": command,
        "transcript": "".join(TRANSCRIPT)[-60000:],
    }
    body: dict[str, object] = {
        "message": f"Record PR62 manual acceptance status {seq}: {phase}",
        "content": base64.b64encode(
            (json.dumps(status, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        ).decode("ascii"),
        "branch": control_ref,
    }
    if sha:
        body["sha"] = sha
    request = urllib.request.Request(
        status_url,
        data=json.dumps(body).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        json.load(response)


def pump(child: pexpect.spawn | None) -> tuple[pexpect.spawn | None, bool]:
    if child is None:
        return None, False
    saw_eof = False
    while True:
        try:
            text = child.read_nonblocking(size=4096, timeout=0.05)
        except pexpect.TIMEOUT:
            break
        except pexpect.EOF:
            saw_eof = True
            break
        else:
            record(text)
    if saw_eof:
        child.close()
        mark(f"SESSION_EXITED status={child.exitstatus} signal={child.signalstatus}")
        return None, True
    return child, False


def settle(
    child: pexpect.spawn | None,
    *,
    max_seconds: float = 15.0,
    idle_seconds: float = 1.0,
) -> pexpect.spawn | None:
    if child is None:
        return None
    deadline = time.monotonic() + max_seconds
    last_output = time.monotonic()
    while time.monotonic() < deadline:
        try:
            text = child.read_nonblocking(size=4096, timeout=0.25)
        except pexpect.TIMEOUT:
            if time.monotonic() - last_output >= idle_seconds:
                return child
        except pexpect.EOF:
            child.close()
            mark(f"SESSION_EXITED status={child.exitstatus} signal={child.signalstatus}")
            return None
        else:
            record(text)
            last_output = time.monotonic()
    mark("OUTPUT_STILL_ACTIVE_AFTER_SETTLE_WINDOW")
    return child


def spawn_cli(executable: str, root: Path, env: dict[str, str]) -> pexpect.spawn:
    child = pexpect.spawn(
        executable,
        cwd=str(root),
        env=env,
        encoding="utf-8",
        codec_errors="replace",
        timeout=None,
    )
    mark(f"CLI_SESSION_STARTED pid={child.pid}")
    return child


def verify_caldav(calendar) -> None:
    task = None
    for resource in calendar.todos(include_completed=True):
        component = resource.get_icalendar_component()
        if str(component.get("UID", "")) == TASK_UID:
            task = component
            break
    if task is None:
        raise AssertionError("seeded VTODO not found")

    work_events = []
    for resource in calendar.events():
        component = resource.get_icalendar_component()
        categories = str(component.get("CATEGORIES", "") or "")
        description = str(component.get("DESCRIPTION", "") or "")
        if "caldav-assistant-work" in categories and TASK_UID in description:
            work_events.append(component)
    if not work_events:
        raise AssertionError("Work VEVENT not found")

    latest = work_events[-1]
    task_status = str(task.get("STATUS", ""))
    work_dtend_present = latest.get("DTEND") is not None
    work_categories = str(latest.get("CATEGORIES", "") or "")
    open_marker_present = "caldav-assistant-work-open" in work_categories
    mark(f"VTODO_STATUS={task_status}")
    mark(f"WORK_EVENT_COUNT={len(work_events)}")
    mark(f"WORK_DTEND_PRESENT={work_dtend_present}")
    mark(f"WORK_OPEN_MARKER_PRESENT={open_marker_present}")
    if task_status != "IN-PROCESS":
        raise AssertionError("paused VTODO is not IN-PROCESS")
    if not work_dtend_present:
        raise AssertionError("paused Work VEVENT has no DTEND")
    if open_marker_present:
        raise AssertionError("paused Work VEVENT still has open marker")
    mark("AUTHORITATIVE_CALDAV_READBACK=PASS")


def main() -> int:
    root = Path.cwd()
    executable = shutil.which("caldav-assistant")
    if not executable:
        raise RuntimeError("installed caldav-assistant executable is not on PATH")

    with tempfile.TemporaryDirectory(prefix="pr62-assistant-operated-") as raw_tmp:
        tmp = Path(raw_tmp)
        home = tmp / "home"
        storage = tmp / "radicale"
        home.mkdir()
        storage.mkdir()
        port = free_port()
        base_url = f"http://127.0.0.1:{port}/"
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
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PYTHONUNBUFFERED"] = "1"
        child: pexpect.spawn | None = None
        try:
            wait_http(base_url)
            calendar = seed_and_configure(home, base_url)
            started = subprocess.run(
                [executable, "background", "start"],
                cwd=root,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=15,
                check=False,
            )
            record(started.stdout)
            if started.returncode != 0:
                raise AssertionError("background start failed")
            status = subprocess.run(
                [executable, "background", "status"],
                cwd=root,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=10,
                check=False,
            )
            record(status.stdout)
            if status.returncode != 0:
                raise AssertionError("background status failed")
            mark(f"SETUP_READY base_commit=77212fcaef06f845cbb19d4877a6f6f393216950")
            mark(f"REAL_RADICALE_READY url={base_url}")
            mark("WAITING_FOR_COMMAND seq>0")
            publish_status(0, "SETUP_READY", "NONE")

            last_seq = 0
            deadline = time.monotonic() + 22 * 60
            verified = False
            while time.monotonic() < deadline:
                child, _ = pump(child)
                try:
                    control = read_control()
                except Exception as exc:
                    mark(f"CONTROL_READ_RETRY {type(exc).__name__}: {exc}")
                    time.sleep(1)
                    continue
                seq = int(control.get("seq", -1))
                if seq <= last_seq:
                    time.sleep(0.5)
                    continue
                command = str(control.get("command", ""))
                last_seq = seq
                mark(f"COMMAND_RECEIVED seq={seq} command={command!r}")

                if command in {"LAUNCH", "RELAUNCH"}:
                    if child is not None:
                        raise AssertionError("cannot launch while a CLI session is active")
                    child = spawn_cli(executable, root, env)
                elif command == "ENTER":
                    if child is None:
                        raise AssertionError("ENTER without an active CLI")
                    child.sendline("")
                elif command == "CTRL_C":
                    if child is None:
                        raise AssertionError("CTRL_C without an active CLI")
                    child.sendcontrol("c")
                elif command.startswith("TEXT:"):
                    if child is None:
                        raise AssertionError("TEXT without an active CLI")
                    child.sendline(command.removeprefix("TEXT:"))
                elif command == "VERIFY":
                    if child is not None:
                        raise AssertionError("VERIFY requires the CLI session to be closed")
                    verify_caldav(calendar)
                    verified = True
                elif command == "CLEANUP":
                    if not verified:
                        raise AssertionError("CLEANUP refused before CalDAV verification")
                    mark("CLEANUP_ACCEPTED")
                    publish_status(seq, "CLEANUP_ACCEPTED", command)
                    return 0
                else:
                    raise AssertionError(f"unsupported relay command: {command}")
                mark(f"COMMAND_APPLIED seq={seq}")
                child = settle(child)
                phase = "VERIFIED" if verified else (
                    "SESSION_ACTIVE" if child is not None else "SESSION_IDLE"
                )
                publish_status(seq, phase, command)
            raise TimeoutError("relay timed out waiting for assistant-operated commands")
        finally:
            if child is not None and child.isalive():
                child.close(force=True)
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


if __name__ == "__main__":
    raise SystemExit(main())
