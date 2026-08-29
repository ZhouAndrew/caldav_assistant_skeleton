"""Log Task start/resume work-session transitions to WordPress.

This is a bundled extension, not TaskService business logic.  It listens to the
public Full Extension Hook API and writes through the Scratch-like Easy API, so
WordPress/Outbox behavior remains behind WordPressService.  Hook failures are
isolated by the Extension System and can never roll back a successful Task action.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from caldav_assistant.api.v1.hooks import HookEvent, on
from caldav_assistant.easy import tasks, write_log


def _stamp(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.astimezone()
        else:
            value = value.astimezone()
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return "—"
    return str(value)


def _activity(event: HookEvent) -> Any:
    return event.get("activity")


def _task_for(uid: str) -> Any:
    if not uid:
        return None
    try:
        for task in tasks():
            if str(getattr(task, "id", "") or "") == uid:
                return task
    except Exception:
        # The authoritative lifecycle action already succeeded.  A secondary
        # lookup only improves the human log title and must not become required.
        return None
    return None


def _render(event: HookEvent, *, verb: str) -> tuple[str, str]:
    activity = _activity(event)
    uid = str(getattr(activity, "object_id", "") or "")
    task = _task_for(uid)
    summary = str(getattr(task, "summary", "") or "").strip() or uid or "Task"
    metadata = getattr(activity, "metadata", {}) or {}

    actual_time = getattr(activity, "timestamp", None)
    planned_start = metadata.get("planned_start", getattr(task, "start", None))
    due = metadata.get("due", getattr(task, "due", None))
    priority = metadata.get("priority", getattr(task, "priority", None))

    title = f"{verb} — {summary}"
    text = "\n".join(
        [
            "CalDAV Assistant work session",
            f"Action: {verb.lower()}",
            f"Actual time: {_stamp(actual_time)}",
            f"Task: {summary}",
            f"Task UID: {uid or '—'}",
            "",
            "Plan",
            f"- Planned start: {_stamp(planned_start)}",
            f"- Due: {_stamp(due)}",
            f"- Priority: {priority if priority is not None else '—'}",
        ]
    )
    return title, text


def _write(event: HookEvent, *, verb: str) -> Any:
    title, text = _render(event, verb=verb)
    return write_log(text, title=title)


@on("task.started")
def log_task_started(event: HookEvent) -> Any:
    return _write(event, verb="Started")


@on("task.resumed")
def log_task_resumed(event: HookEvent) -> Any:
    return _write(event, verb="Resumed")
