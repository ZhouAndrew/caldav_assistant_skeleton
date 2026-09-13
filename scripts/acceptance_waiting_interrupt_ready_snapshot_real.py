#!/usr/bin/env python3
"""Run Waiting Mode Ctrl-C acceptance after real background snapshot preparation.

The original acceptance remains the source of truth for the interactive Waiting Mode
path. This wrapper changes only its fresh-HOME precondition: once Radicale and Settings
exist, start the installed background Assistant and wait for its first verified Task
snapshot. Foreground startup can then exercise the production cache-first contract
without reintroducing synchronous CalDAV I/O.
"""
from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import time

import acceptance_waiting_interrupt_real as waiting

from caldav_assistant.internal.caldav.sync import SyncEngine
from caldav_assistant.internal.storage.sqlite import SQLiteCacheRepository, SQLiteStore


_original_configure = waiting._configure


def _configure_with_ready_background(
    home: Path,
    base_url: str,
    calendar_url: str,
) -> None:
    _original_configure(home, base_url, calendar_url)

    executable = shutil.which("caldav-assistant")
    if not executable:
        raise RuntimeError("Installed caldav-assistant executable is not on PATH")

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PYTHONUNBUFFERED"] = "1"
    started = subprocess.run(
        [executable, "background", "start"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=10,
        check=False,
    )
    if started.returncode != 0:
        raise RuntimeError(
            "Could not start the installed background Assistant before Waiting Mode "
            f"acceptance:\n{started.stdout}"
        )

    store = SQLiteStore(home / ".caldav-assistant" / "assistant.sqlite3")
    store.migrate()
    cache = SQLiteCacheRepository(store)
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        snapshot = cache.get(SyncEngine.SNAPSHOT_KEY, None)
        if (
            isinstance(snapshot, dict)
            and isinstance(snapshot.get("synced_at"), str)
            and snapshot.get("synced_at")
            and isinstance(snapshot.get("tasks"), list)
            and snapshot.get("tasks")
            and isinstance(snapshot.get("events"), list)
        ):
            print("PASS: background Assistant prepared Waiting Mode startup snapshot")
            return
        time.sleep(0.05)

    raise RuntimeError(
        "Background Assistant did not publish a verified Waiting Mode startup snapshot"
    )


waiting._configure = _configure_with_ready_background


if __name__ == "__main__":
    raise SystemExit(waiting.main())
