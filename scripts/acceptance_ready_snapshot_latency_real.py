#!/usr/bin/env python3
"""Real latency acceptance for the background-ready startup architecture.

This intentionally drives the installed executable against real local Radicale.  It
proves the contract that matters after the startup redesign:

* the background Assistant first publishes a verified Task/Event snapshot;
* restarting the daemon does not discard that snapshot;
* foreground CLI startup reads the local snapshot instead of waiting for CalDAV;
* the numbered Start path stays responsive whether one Task is auto-selected or a
  chooser is shown; and
* human think-time inside a modal menu is not reported as operation latency.
"""
from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import time

import pexpect
from caldav.davclient import DAVClient

from acceptance_latency_real import (
    HUMAN_THINK_SECONDS,
    WORK_HISTORY_EVENTS,
    _closed_work_ics,
    _configure,
    _event_ics,
    _free_port,
    _todo_ics,
    _wait_http,
)
from caldav_assistant.internal.caldav.sync import SyncEngine
from caldav_assistant.internal.storage.sqlite import SQLiteCacheRepository, SQLiteStore


STARTUP_BUDGET_SECONDS = 2.0
MENU_BUDGET_SECONDS = 1.0


def _verified_snapshot(home: Path):
    store = SQLiteStore(home / ".caldav-assistant" / "assistant.sqlite3")
    store.migrate()
    return SQLiteCacheRepository(store).get(SyncEngine.SNAPSHOT_KEY, None)


def _wait_for_verified_snapshot(home: Path, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = _verified_snapshot(home)
        if (
            isinstance(snapshot, dict)
            and isinstance(snapshot.get("synced_at"), str)
            and snapshot.get("synced_at")
            and isinstance(snapshot.get("tasks"), list)
            and isinstance(snapshot.get("events"), list)
            and snapshot.get("tasks")
            and snapshot.get("events")
        ):
            return snapshot
        time.sleep(0.05)
    raise AssertionError("Background Assistant did not publish a verified startup snapshot")


def _return_to_console(child: pexpect.spawn) -> None:
    """Back out from duration/Task/home menus without assuming auto-selection."""
    for _ in range(4):
        child.sendline("0")
        index = child.expect(
            [
                r"What do you want to do\?",
                "Choose a Task to work on",
                r"> ",
            ]
        )
        if index == 2:
            return
    raise AssertionError("Could not return from guided Start path to the console")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    executable = shutil.which("caldav-assistant")
    if not executable:
        raise RuntimeError("Installed caldav-assistant executable is not on PATH")

    with tempfile.TemporaryDirectory(prefix="caldav-assistant-ready-latency-") as raw_tmp:
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
            client = DAVClient(url=base_url, username="latency", password="latency")
            principal = client.principal()
            task_calendar = principal.make_calendar(name="Tasks")
            event_calendar = principal.make_calendar(name="Events")
            work_calendar = principal.make_calendar(name="Assistant Work")
            for index in range(5):
                principal.make_calendar(name=f"Decoy {index + 1}")

            now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
            task_calendar.save_todo(_todo_ics(now, status="IN-PROCESS"))
            event_calendar.save_event(_event_ics(now))
            for index in range(WORK_HISTORY_EVENTS):
                work_calendar.save_event(_closed_work_ics(index, now))
            _configure(
                home,
                base_url=base_url,
                task_url=str(task_calendar.url),
                event_url=str(event_calendar.url),
                work_url=str(work_calendar.url),
            )
            print(
                "PASS: real Radicale seeded with 3 role collections + 5 decoys + "
                f"{WORK_HISTORY_EVENTS} closed Work intervals"
            )

            started = subprocess.run(
                [executable, "background", "start"],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
            if started.returncode != 0:
                raise AssertionError(
                    "Background start failed before snapshot preparation: "
                    f"{started.stdout}{started.stderr}"
                )
            _wait_for_verified_snapshot(home)
            print("PASS: background Assistant published a verified Task/Event snapshot")

            restarted = subprocess.run(
                [executable, "background", "restart"],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
            if restarted.returncode != 0:
                raise AssertionError(
                    "Background restart failed before latency path: "
                    f"{restarted.stdout}{restarted.stderr}"
                )
            print("PASS: background restarted immediately before foreground CLI")

            transcript_raw = os.environ.get("CALDAV_ASSISTANT_LATENCY_TRANSCRIPT")
            transcript_path = Path(transcript_raw) if transcript_raw else tmp / "latency.txt"
            if not transcript_path.is_absolute():
                transcript_path = root / transcript_path
            transcript_path.parent.mkdir(parents=True, exist_ok=True)
            transcript = transcript_path.open("w", encoding="utf-8")

            began = time.monotonic()
            child = pexpect.spawn(
                executable,
                cwd=str(root),
                env=env,
                encoding="utf-8",
                codec_errors="replace",
                timeout=15,
            )
            child.logfile = transcript
            child.expect("Console ready")
            startup_elapsed = time.monotonic() - began
            if startup_elapsed > STARTUP_BUDGET_SECONDS:
                raise AssertionError(
                    f"Background-snapshot startup took {startup_elapsed:.2f}s; "
                    f"budget is {STARTUP_BUDGET_SECONDS:.1f}s"
                )
            print(
                f"PASS: background-snapshot startup {startup_elapsed:.2f}s "
                f"<= {STARTUP_BUDGET_SECONDS:.1f}s"
            )

            began = time.monotonic()
            child.sendline("")
            child.expect(r"What do you want to do\?")
            menu_elapsed = time.monotonic() - began
            if menu_elapsed > MENU_BUDGET_SECONDS:
                raise AssertionError(
                    f"Opening guided menu took {menu_elapsed:.2f}s; "
                    f"budget is {MENU_BUDGET_SECONDS:.1f}s"
                )
            print(f"PASS: guided menu opened in {menu_elapsed:.2f}s")

            child.sendline("1")
            index = child.expect(["Choose a Task to work on", "How long do you want to work"])
            if index == 0:
                print("PASS: guided Start displayed Task chooser")
                child.sendline("1")
                child.expect("How long do you want to work")
            else:
                print("PASS: single actionable Task was auto-selected")
            print("PASS: guided Start reached duration menu without startup live refresh")
            _return_to_console(child)

            child.sendline("history")
            child.expect("Working: history")
            child.expect("History")
            time.sleep(HUMAN_THINK_SECONDS)
            child.sendline("0")
            child.expect("Menu/selection finished")
            child.expect(r"> ")
            child.sendline("exit")
            child.expect(pexpect.EOF)
            child.close()
            child = None

            transcript.flush()
            transcript.close()
            transcript = None
            text = transcript_path.read_text(encoding="utf-8", errors="replace")
            startup_text, _, after_console = text.partition("Console ready")
            if "verified local snapshot" not in startup_text:
                raise AssertionError("Startup transcript did not use the background verified snapshot path")
            if "→ CalDAV [Tasks" in startup_text:
                raise AssertionError("Foreground startup still advertised a live CalDAV traversal")
            if "Startup live read exceeded" in startup_text:
                raise AssertionError("Foreground startup still waited for the old live-read deadline")
            if "Still working… 2s elapsed" in startup_text:
                raise AssertionError("Background-snapshot startup showed a multi-second wait heartbeat")
            if "Latency acceptance Task" not in startup_text:
                raise AssertionError("Verified snapshot Task was not shown during startup")
            if "Latency acceptance Event" not in startup_text:
                raise AssertionError("Verified snapshot Event was not shown during startup")

            marker = "Working: history"
            end_marker = "Menu/selection finished"
            if marker not in after_console or end_marker not in after_console:
                raise AssertionError("History interaction markers missing from transcript")
            history_section = after_console.split(marker, 1)[1].split(end_marker, 1)[0]
            if "Still working" in history_section:
                raise AssertionError(
                    "Human think-time in History was falsely reported as Still working"
                )
            print(
                f"PASS: {HUMAN_THINK_SECONDS:.1f}s human pause in History produced no fake progress heartbeat"
            )
            print(f"PASS: ready-snapshot latency transcript written to {transcript_path}")
            return 0
        finally:
            if child is not None:
                try:
                    child.close(force=True)
                except Exception:
                    pass
            if transcript is not None:
                try:
                    transcript.close()
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
