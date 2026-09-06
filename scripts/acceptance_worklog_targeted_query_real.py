#!/usr/bin/env python3
"""Real Radicale acceptance for targeted WorkLog reads.

A long-lived Work collection may contain years of closed intervals.  Standalone
``current_task_id`` / ``segments_for(task)`` and the normal Task lifecycle must use
bounded server property filters instead of downloading all Work VEVENTs.  This script
seeds real Radicale and then disables the stable full-history fallbacks so those paths
can pass only when the production targeted REPORTs really work.
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
from caldav_assistant.internal.tasks import CalDAVWorkTaskService
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


def _forbid_full_snapshot(*args, **kwargs):
    raise AssertionError("Task lifecycle loaded the complete Work history")


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
            task_calendar = principal.make_calendar(name="Tasks")
            work_calendar = principal.make_calendar(name="Assistant Work")
            now = datetime.now(timezone.utc).replace(microsecond=0)

            task_calendar.add_todo(
                uid="lifecycle-task",
                summary="Lifecycle Task",
                status="NEEDS-ACTION",
                due=now + timedelta(hours=2),
            )

            # Closed history for several unrelated Tasks simulates a growing Work
            # collection.  Two intervals belong to the target Task used below for a
            # standalone history query.
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

            initial_open = work_calendar.add_event(
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
                task_collection_url=lambda: str(task_calendar.url),
                event_collection_url=lambda: None,
            )
            worklog = WorkLogService(routed, lambda: str(work_calendar.url))

            # A successful targeted query must not need the previous full/scoped path.
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

            # Full snapshot deliberately remains available for paused-task semantics.
            # Restore only that fallback and verify it still sees all 13 Work events.
            del routed.list_events_in_collection
            snapshot = worklog.snapshot()
            if len(snapshot) != 13:
                raise AssertionError(f"full Work snapshot expected 13 items, got {len(snapshot)}")
            print("PASS: full snapshot semantics remain intact for paused-task decisions")

            # Remove the synthetic open interval so a real lifecycle can begin.  Then
            # make full-history access fatal.  The lifecycle is allowed only OPEN and
            # per-Task targeted queries from this point onward.
            initial_open.delete()
            routed.list_events_in_collection = _forbid_fallback
            routed.list_events = _forbid_fallback
            worklog.snapshot = _forbid_full_snapshot

            tasks = CalDAVWorkTaskService(
                routed,
                None,
                None,
                None,
                worklog=worklog,
            )
            tasks.start("lifecycle-task")
            tasks.pause("lifecycle-task")
            tasks.resume("lifecycle-task")
            completed = tasks.complete("lifecycle-task")
            if not completed.affected.completed or completed.affected.status != "COMPLETED":
                raise AssertionError("real targeted lifecycle did not complete the VTODO")

            # Use the independent writer client for post-condition verification; the
            # production WorkLog fallbacks remain disabled throughout the lifecycle.
            life_segments = [
                item
                for item in work_calendar.get_events()
                if WorkLogService._task_id_from_event(
                    inner._to_event(item, work_calendar)
                )
                == "lifecycle-task"
            ]
            if len(life_segments) != 2:
                raise AssertionError(
                    f"start/pause/resume/complete expected 2 Work intervals, got {len(life_segments)}"
                )
            mapped = [inner._to_event(item, work_calendar) for item in life_segments]
            if any(item.end is None or WorkLogService.OPEN_CATEGORY in item.categories for item in mapped):
                raise AssertionError("completed lifecycle left an open Work interval")
            print("PASS: start/pause/resume/complete ran with full Work snapshot forbidden")

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
