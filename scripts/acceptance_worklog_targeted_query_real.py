#!/usr/bin/env python3
"""Real Radicale acceptance for targeted WorkLog reads.

A long-lived Work collection may contain years of closed intervals.  Standalone
``current_task_id`` and ``segments_for(task)`` must therefore use server property
filters instead of downloading all Work VEVENTs.  This script seeds real Radicale,
then disables the stable full/scoped fallback so the acceptance can pass only if the
production targeted REPORT path is actually supported.
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

from caldav_assistant.internal.caldav import CollectionRoutingCalDAVAdapter, LibraryCalDAVAdapter
from caldav_assistant.internal.worklog.service import WorkLogService


class Provider:
    def __init__(self, url: str):
        self.url = url

    def get_base_url(self) -> str:
        return self.url


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


def _forbid_fallback(*args, **kwargs):
    raise AssertionError("targeted WorkLog query fell back to full/scoped history read")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="caldav-assistant-worklog-query-") as raw_tmp:
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
            writer = DAVClient(url=base_url, username="work", password="work")
            principal = writer.principal()
            work_calendar = principal.make_calendar(name="Assistant Work")
            now = datetime.now(timezone.utc).replace(microsecond=0)

            # Closed history for several unrelated Tasks simulates a growing Work
            # collection.  Two intervals belong to the target Task.
            for index in range(12):
                task_id = "wanted" if index in (3, 9) else f"old-{index}"
                start = now - timedelta(days=60 - index, minutes=index)
                work_calendar.add_event(
                    summary=f"Work — {task_id}",
                    dtstart=start,
                    dtend=start + timedelta(minutes=10),
                    description=WorkLogService._description(task_id),
                    categories=[WorkLogService.CATEGORY],
                )

            work_calendar.add_event(
                summary="Work — current",
                dtstart=now - timedelta(minutes=5),
                description=WorkLogService._description("current"),
                categories=[WorkLogService.CATEGORY, WorkLogService.OPEN_CATEGORY],
            )
            print("PASS: real Radicale seeded with closed Work history + one open interval")

            inner = LibraryCalDAVAdapter(
                Provider(base_url),
                {"username": "work", "password": "work"},
            )
            routed = CollectionRoutingCalDAVAdapter(
                inner,
                # These human roles are irrelevant to WorkLog; the helper binds the
                # explicit Work collection URL directly.
                task_collection_url=lambda: None,
                event_collection_url=lambda: None,
            )
            worklog = WorkLogService(routed, lambda: str(work_calendar.url))

            # A successful targeted query must not need the previous fallback path.
            routed.list_events_in_collection = _forbid_fallback
            routed.list_events = _forbid_fallback

            current = worklog.current_task_id()
            if current != "current":
                raise AssertionError(f"targeted open query returned {current!r}")
            print("PASS: current_task_id used server OPEN-category query")

            segments = worklog.segments_for("wanted")
            if len(segments) != 2:
                raise AssertionError(
                    f"targeted per-Task history expected 2 segments, got {len(segments)}"
                )
            if any(WorkLogService._task_id_from_event(item) != "wanted" for item in segments):
                raise AssertionError("per-Task query returned another Task's Work segment")
            print("PASS: segments_for used server category + description query")

            # Full snapshot deliberately remains available for paused-task semantics;
            # restore only that fallback and verify it still sees all 13 Work events.
            del routed.list_events_in_collection
            snapshot = worklog.snapshot()
            if len(snapshot) != 13:
                raise AssertionError(f"full Work snapshot expected 13 items, got {len(snapshot)}")
            print("PASS: full snapshot semantics remain intact for paused-task decisions")
            print("REAL WORKLOG TARGETED QUERY ACCEPTANCE: PASS")
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
