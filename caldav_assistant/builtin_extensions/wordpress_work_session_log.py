"""Write closed Task work intervals to the human WordPress daily log.

Machine-detail lifecycle history remains in Activity Journal / CalDAV Work VEVENTs.
This bundled extension deliberately writes nothing on start/resume; when work is
paused it closes the human-facing diary entry as one configurable line, e.g.::

    5:00-5:10 Anki

The formatter is driven by validated per-user Settings.  WordPress delivery is queued
through the Outbox when available, so a successful Task action never waits for the
WordPress transport.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from caldav_assistant.api.v1.hooks import HookEvent, on
from caldav_assistant.easy import tasks
from caldav_assistant.internal.runtime.current_context import get_current_context
from caldav_assistant.internal.wordpress.worklog import WorkLogFormatter


_OPEN_ACTIONS = frozenset({"task_started", "task_resumed"})
_CLOSE_ACTIONS = frozenset({"task_paused", "task_completed", "task_deleted"})


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
        return None
    return None


def _segment_start(task: Any, end: datetime) -> datetime | None:
    """Recover the current interval start from persisted Activity Journal history."""
    try:
        ctx = get_current_context()
        items = list(ctx.activity.for_task(task) or ())
    except Exception:
        return None

    valid = [
        item
        for item in items
        if isinstance(getattr(item, "timestamp", None), datetime)
        and getattr(item, "timestamp") <= end
    ]
    valid.sort(key=lambda item: getattr(item, "timestamp"))

    start: datetime | None = None
    for item in valid:
        action = str(getattr(item, "action", "") or "")
        timestamp = getattr(item, "timestamp")
        if action in _OPEN_ACTIONS:
            start = timestamp
            continue
        if action in _CLOSE_ACTIONS:
            # The hook fires after the current pause was persisted.  A close record
            # at exactly `end` is the interval we are rendering, not an earlier one.
            if timestamp < end:
                start = None
    return start


def _queue(text: str) -> Any:
    ctx = get_current_context()
    wordpress = ctx.wordpress
    writer = getattr(wordpress, "queue_log", None)
    if not callable(writer):
        writer = getattr(wordpress, "log", None)
    if not callable(writer):
        return None
    # The line already contains its start/end range; suppress the transport's
    # ordinary "logged at" prefix so WordPress contains exactly the human entry.
    return writer(text, _show_clock=False)


@on("task.paused")
def log_closed_work_segment(event: HookEvent) -> Any:
    activity = _activity(event)
    end = getattr(activity, "timestamp", None)
    uid = str(getattr(activity, "object_id", "") or "").strip()
    if not isinstance(end, datetime) or not uid:
        return None

    task = _task_for(uid)
    if task is None:
        return None
    start = _segment_start(task, end)
    if start is None:
        return None

    ctx = get_current_context()
    text = WorkLogFormatter(ctx.settings).render_segment(
        task,
        start,
        end,
        status="paused",
    )
    return None if not text else _queue(text)
