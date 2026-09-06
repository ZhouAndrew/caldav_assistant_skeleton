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
from types import SimpleNamespace
from typing import Any

from caldav_assistant.api import Event
from caldav_assistant.api.v1.hooks import HookEvent, on
from caldav_assistant.easy import tasks
from caldav_assistant.internal.runtime.current_context import get_current_context
from caldav_assistant.internal.wordpress.worklog import WorkLogFormatter


_OPEN_ACTIONS = frozenset({"task_started", "task_resumed"})
_CLOSE_ACTIONS = frozenset({"task_paused", "task_completed", "task_deleted"})


def _activity(event: HookEvent) -> Any:
    return event.get("activity")


def _task_for(activity: Any) -> Any:
    """Use the Task fact already carried by production lifecycle hooks when present."""
    uid = str(getattr(activity, "object_id", "") or "").strip()
    if not uid:
        return None
    metadata = getattr(activity, "metadata", None)
    if isinstance(metadata, dict):
        summary = str(metadata.get("task_summary") or "").strip()
        if summary:
            # WorkLogFormatter needs only id + summary.  Do not re-read the Task
            # collection after the authoritative pause command already knew both.
            return SimpleNamespace(id=uid, summary=summary)

    # Compatibility path for replacement/older lifecycle publishers that do not
    # carry the optional task_summary fact.
    try:
        for task in tasks():
            if str(getattr(task, "id", "") or "") == uid:
                return task
    except Exception:
        return None
    return None


def _hook_segment(activity: Any) -> tuple[datetime, datetime] | None:
    """Consume the exact Work interval closed by the current lifecycle command."""
    metadata = getattr(activity, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    raw = metadata.get("work_segment")
    if not isinstance(raw, dict):
        return None
    try:
        start = datetime.fromisoformat(str(raw.get("start") or ""))
        end = datetime.fromisoformat(str(raw.get("end") or ""))
    except ValueError:
        return None
    if end < start:
        return None
    return start, end


def _caldav_segment(task: Any, activity_end: datetime) -> tuple[datetime, datetime] | None:
    """Compatibility fallback: re-read Work history only when hook facts are absent."""
    try:
        ctx = get_current_context()
        session = getattr(ctx, "session", None)
        worklog = getattr(session, "worklog", None)
        reader = getattr(worklog, "segments_for", None)
        if not callable(reader):
            return None
        closed = [
            item
            for item in (reader(task) or ())
            if isinstance(item, Event)
            and isinstance(item.start, datetime)
            and isinstance(item.end, datetime)
            and item.start <= item.end <= activity_end
        ]
    except Exception:
        return None
    if not closed:
        return None
    item = max(closed, key=lambda value: value.end)
    return item.start, item.end


def _activity_segment(task: Any, end: datetime) -> tuple[datetime, datetime] | None:
    """Recover a closed interval from Activity Journal when no Work VEVENT exists."""
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
    return None if start is None else (start, end)


def _closed_segment(
    task: Any,
    end: datetime,
    activity: Any,
) -> tuple[datetime, datetime] | None:
    # Production CalDAV lifecycle hands us the just-persisted segment.  The two
    # fallbacks preserve behaviour for replacement services and WorkLog-disabled use.
    return _hook_segment(activity) or _caldav_segment(task, end) or _activity_segment(task, end)


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
    activity_end = getattr(activity, "timestamp", None)
    uid = str(getattr(activity, "object_id", "") or "").strip()
    if not isinstance(activity_end, datetime) or not uid:
        return None

    task = _task_for(activity)
    if task is None:
        return None
    interval = _closed_segment(task, activity_end, activity)
    if interval is None:
        return None
    start, end = interval

    ctx = get_current_context()
    text = WorkLogFormatter(ctx.settings).render_segment(
        task,
        start,
        end,
        status="paused",
    )
    return None if not text else _queue(text)
