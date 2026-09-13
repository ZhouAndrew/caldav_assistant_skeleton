#!/usr/bin/env python3
"""Run the full conversation acceptance in the normal background-ready state.

The product contract now separates two cases deliberately:

* a normal installed session reads the last verified snapshot already maintained by
  the background Assistant and must not wait for CalDAV during CLI startup;
* a truly first-ever run with no verified snapshot must become usable immediately
  with an explicit unavailable/unknown state while background sync fills the cache.

``acceptance_conversation_real`` verifies the long lifecycle conversation.  Its old
fresh-HOME setup accidentally modeled the second case while asserting the first case's
startup data.  This wrapper starts the real installed background service, waits for its
first real Radicale sync to publish a verified snapshot, and then delegates the exact
same user conversation to the original acceptance harness.
"""
from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import time

import acceptance_conversation_real as conversation

from caldav_assistant.internal.caldav.sync import SyncEngine
from caldav_assistant.internal.storage.sqlite import SQLiteCacheRepository, SQLiteStore


_original_configure = conversation._configure_assistant


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
            "Could not start the installed background Assistant before conversation "
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
            and isinstance(snapshot.get("events"), list)
            and snapshot.get("tasks")
            and snapshot.get("events")
        ):
            print("PASS: background Assistant prepared the verified startup snapshot")
            return
        time.sleep(0.05)

    raise RuntimeError(
        "Background Assistant did not publish a verified Task/Event startup snapshot"
    )


conversation._configure_assistant = _configure_with_ready_background


if __name__ == "__main__":
    raise SystemExit(conversation.main())
