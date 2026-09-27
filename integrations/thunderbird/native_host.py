#!/usr/bin/env python3
from __future__ import annotations

import base64
from collections import deque
from datetime import datetime
import json
from pathlib import Path
import struct
import subprocess
import sys
import time
from typing import Any
from uuid import uuid4

from caldav_assistant.internal.bootstrap import build_service_application
from caldav_assistant.internal.progress import bind_progress_sink, emit_progress, operation_scope


APP = None
HISTORY_CALENDAR: dict[str, Any] | None = None
UPLOADS: dict[str, dict[str, Any]] = {}
LOG_LINES: deque[str] = deque(maxlen=500)
LOG_PATH = (
    Path.home()
    / ".local"
    / "state"
    / "caldav-assistant"
    / "thunderbird"
    / "native-host.log"
)


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 1)


def log_event(event: str, **fields: Any) -> None:
    record = {
        "at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "event": event,
        **fields,
    }
    line = json.dumps(record, ensure_ascii=False, default=str, sort_keys=True)
    LOG_LINES.append(line)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
        if LOG_PATH.stat().st_size > 2_000_000:
            lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
            LOG_PATH.write_text(
                "\n".join(lines[-500:]) + "\n",
                encoding="utf-8",
            )
    except OSError:
        pass


def log_lines(limit: int = 300) -> list[str]:
    clean_limit = min(500, max(1, int(limit or 300)))
    try:
        if LOG_PATH.is_file():
            return LOG_PATH.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()[-clean_limit:]
    except OSError:
        pass
    return list(LOG_LINES)[-clean_limit:]


def clear_logs() -> None:
    LOG_LINES.clear()
    try:
        LOG_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def open_log_folder() -> dict[str, Any]:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        LOG_PATH.touch(exist_ok=True)
    except OSError:
        pass

    opened = False
    try:
        subprocess.Popen(
            ["xdg-open", str(LOG_PATH.parent)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        opened = True
    except (OSError, ValueError):
        opened = False

    return {
        "ok": True,
        "opened": opened,
        "path": str(LOG_PATH),
        "directory": str(LOG_PATH.parent),
    }


def app():
    global APP
    if APP is None:
        APP = build_service_application()
    return APP


def core_call(method: str, **payload: Any) -> Any:
    return app().background.dispatcher.handle(method, payload)


def read_message() -> dict[str, Any] | None:
    raw = sys.stdin.buffer.read(4)
    if not raw:
        return None
    if len(raw) != 4:
        raise EOFError("short native-message header")
    size = struct.unpack("<I", raw)[0]
    payload = sys.stdin.buffer.read(size)
    if len(payload) != size:
        raise EOFError("short native-message body")
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("message must be an object")
    return value


def write_message(value: dict[str, Any]) -> None:
    data = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(data)))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def ensure_history_calendar() -> dict[str, Any]:
    global HISTORY_CALENDAR
    if HISTORY_CALENDAR is None:
        HISTORY_CALENDAR = core_call(
            "caldav.ensure_worklog_collection",
            name="CalDAV Assistant History",
        )
    return HISTORY_CALENDAR


def ensure_history_calendar_if_needed() -> dict[str, Any]:
    """Keep first-run repair without adding a CalDAV round-trip to every action."""
    try:
        worklog = getattr(app().ctx.session, "worklog", None)
        configured = getattr(worklog, "configured", None)
        if callable(configured) and bool(configured()):
            return {"configured": True, "created": False, "source": "local-setting"}
    except Exception:
        pass

    emit_progress(
        "history.ensure",
        "Work history is not configured; provisioning CalDAV Assistant History...",
        state="started",
    )
    result = ensure_history_calendar()
    emit_progress(
        "history.ensure",
        "CalDAV Assistant History is ready.",
        state="done",
        created=bool((result or {}).get("created")) if isinstance(result, dict) else None,
    )
    return result


def task_json(task: Any) -> dict[str, Any]:
    return {
        "id": str(getattr(task, "id", "") or ""),
        "summary": str(getattr(task, "summary", "") or ""),
        "status": str(getattr(task, "status", "") or ""),
        "completed": bool(getattr(task, "completed", False)),
        "due": getattr(task, "due", None),
        "categories": list(getattr(task, "categories", ()) or ()),
    }


def parse_at(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("action time is required")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def latest_activity_work_event_id(task_id: str) -> str | None:
    """Return the last Work VEVENT id already carried by local Activity metadata."""
    try:
        items = app().ctx.activity.for_task(task_id)
    except Exception:
        return None
    for item in reversed(items or []):
        metadata = getattr(item, "metadata", None)
        segment = metadata.get("work_segment") if isinstance(metadata, dict) else None
        if isinstance(segment, dict):
            event_id = str(segment.get("event_id") or "").strip()
            if event_id:
                return event_id
    return None


def latest_work_event_id(task_id: str) -> str | None:
    # Notes may be added while a Work interval is still open, so prefer the current
    # authoritative VEVENT there. Closed lifecycle actions pass the exact event id
    # from Activity metadata into their asynchronous WordPress follow-up instead.
    try:
        opened = core_call("worklog.open_for", task=task_id)
        event_id = str(getattr(opened, "id", "") or "").strip()
        if event_id:
            return event_id
    except Exception:
        pass
    return latest_activity_work_event_id(task_id)


def link_event(event_id: str | None, *, at: datetime, attachment_urls=()) -> dict[str, Any] | None:
    if not event_id:
        return None
    try:
        reference = core_call("wordpress.daily_log_reference", at=at)
        url = str((reference or {}).get("url") or "").strip()
        if not url and not attachment_urls:
            return None
        core_call(
            "worklog.add_references",
            event_id=event_id,
            wordpress_url=url or None,
            attachment_urls=list(attachment_urls or ()),
        )
        return reference
    except Exception as exc:
        return {"pending": True, "error": f"{type(exc).__name__}: {exc}"}


def _cached_session_state() -> dict[str, Any]:
    """Return only generation-local cached Session facts; never touch CalDAV."""
    session = app().ctx.session
    reader = getattr(session, "cached_startup_snapshot", None)
    if callable(reader):
        try:
            snapshot = reader(())
        except TypeError:
            snapshot = reader([])
        if isinstance(snapshot, dict):
            return {
                "current_task_id": snapshot.get("current_task_id"),
                # Exact paused history belongs to the Thunderbird-local work-event
                # projection in the current XPI.  Returning [] here keeps the
                # compatibility endpoint strictly cache/local only.
                "paused_task_ids": [],
                "current_work_verified": bool(
                    snapshot.get("current_work_verified", True)
                ),
                "producer_generation": snapshot.get("producer_generation"),
            }
    return {
        "current_task_id": None,
        "paused_task_ids": [],
        "current_work_verified": False,
    }


def activity_today() -> dict[str, Any]:
    started = time.perf_counter()
    today = []
    for item in app().ctx.activity.today():
        at = getattr(item, "timestamp", None)
        local = at.astimezone() if isinstance(at, datetime) else at
        stamp = local.strftime("%H:%M") if isinstance(local, datetime) else ""
        action = str(getattr(item, "action", "") or "")
        object_id = str(getattr(item, "object_id", "") or "")
        today.append(f"{stamp} {action} {object_id}".strip())
    return {
        "ok": True,
        "today": today,
        "history_calendar": {"name": "CalDAV Assistant History"},
        "timings": {
            "activity_ms": _elapsed_ms(started),
            "source": "sqlite-activity",
        },
    }


def state_snapshot() -> dict[str, Any]:
    started = time.perf_counter()
    session_started = time.perf_counter()
    state = _cached_session_state()
    session_ms = _elapsed_ms(session_started)
    return {
        "ok": True,
        "state": state,
        "today": [],
        "history_calendar": {"name": "CalDAV Assistant History"},
        "timings": {
            "session_ms": session_ms,
            "total_ms": _elapsed_ms(started),
            "source": "cache-only-session",
        },
    }


def snapshot() -> dict[str, Any]:
    """Compatibility snapshot for older Thunderbird XPI builds."""
    started = time.perf_counter()
    data = state_snapshot()

    tasks_started = time.perf_counter()
    tasks = app().ctx.tasks.list(actionable=True)
    tasks_ms = _elapsed_ms(tasks_started)

    data["tasks"] = [task_json(task) for task in tasks]
    data["timings"] = {
        **data.get("timings", {}),
        "tasks_caldav_ms": tasks_ms,
        "total_ms": _elapsed_ms(started),
        "source": "caldav-fallback",
    }
    return data


def _wordpress_pending_count() -> int | None:
    try:
        return len(app().ctx.wordpress.pending())
    except Exception:
        return None


def action(message: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    timings: dict[str, Any] = {}

    action_name = str(message.get("action") or "").strip()
    task_id = str(message.get("task_id") or "").strip()
    at = parse_at(message.get("at"))
    if not task_id:
        raise ValueError("task_id is required")

    history_started = time.perf_counter()
    ensure_history_calendar_if_needed()
    timings["history_guard_ms"] = _elapsed_ms(history_started)

    emit_progress(
        "action.preflight",
        "Checking authoritative Task and Work state in CalDAV...",
        state="started",
        task_id=task_id,
        action=action_name,
    )

    tasks = app().ctx.tasks
    task_action_started = time.perf_counter()
    if action_name == "start":
        result = tasks._start(task_id, at=at)
        verb = "Started"
    elif action_name == "resume":
        result = tasks._resume(task_id, at=at)
        verb = "Started a new work segment"
    elif action_name == "pause":
        result = tasks._pause(task_id, at=at)
        verb = "Paused"
    elif action_name == "cancel":
        result = tasks._cancel(task_id, at=at)
        verb = "Cancelled"
    elif action_name == "complete":
        result = tasks._complete(task_id, at=at)
        verb = "Completed"
    else:
        raise ValueError("unsupported action")
    timings["task_action_ms"] = _elapsed_ms(task_action_started)

    emit_progress(
        "action.commit",
        "CalDAV Assistant Core accepted the Task action.",
        state="done",
        task_id=task_id,
        action=action_name,
    )

    wordpress = None
    follow_up = None
    if action_name in {"pause", "cancel", "complete"}:
        pending = _wordpress_pending_count()
        wordpress = {
            "message": "Work log saved to the durable WordPress Outbox; upload continues separately.",
            "queued": True,
            "pending": pending,
        }
        follow_up = {
            "command": "wordpress_sync",
            "task_id": task_id,
            "event_id": latest_activity_work_event_id(task_id),
            "at": at.isoformat(),
            "calendar_link": bool(message.get("calendar_link", True)),
        }

    timings["total_ms"] = _elapsed_ms(started)
    return {
        "ok": True,
        "message": f"{verb} at {at.astimezone().strftime('%H:%M')}",
        "task": task_json(getattr(result, "affected", None)),
        "wordpress": wordpress,
        "follow_up": follow_up,
        "timings": timings,
    }


def wordpress_sync(message: dict[str, Any]) -> dict[str, Any]:
    """Finish non-blocking integration work without competing for Outbox delivery.

    The long-running Assistant Service is the single normal owner of WordPress Outbox
    delivery.  This side-by-side Native Host only reports the durable queue state and,
    when requested, establishes the Calendar↔WordPress reference.
    """
    started = time.perf_counter()
    timings: dict[str, Any] = {}
    task_id = str(message.get("task_id") or "").strip()
    at = parse_at(message.get("at"))
    if not task_id:
        raise ValueError("task_id is required")

    pending = _wordpress_pending_count()
    emit_progress(
        "wordpress.background",
        "WordPress log is safely queued; background Assistant Service owns delivery.",
        state="done",
        task_id=task_id,
        pending=pending,
    )

    reference = None
    calendar_link_state = "disabled"
    if bool(message.get("calendar_link", True)):
        emit_progress(
            "wordpress.calendar_link",
            "Linking the CalDAV Work event to the WordPress daily log...",
            state="started",
            task_id=task_id,
        )
        link_started = time.perf_counter()
        event_id = str(message.get("event_id") or "").strip() or latest_work_event_id(task_id)
        if not event_id:
            calendar_link_state = "no-work-event"
            emit_progress(
                "wordpress.calendar_link",
                "No Work VEVENT is available for a Calendar↔WordPress backlink.",
                state="done",
                task_id=task_id,
            )
        else:
            reference = link_event(event_id, at=at)
            if reference and reference.get("pending"):
                calendar_link_state = "pending"
                emit_progress(
                    "wordpress.calendar_link",
                    "Calendar↔WordPress link is pending and needs a later retry.",
                    state="failed",
                    task_id=task_id,
                    event_id=event_id,
                    error=reference.get("error"),
                )
            elif reference and reference.get("url"):
                calendar_link_state = "linked"
                emit_progress(
                    "wordpress.calendar_link",
                    "Calendar↔WordPress link finished.",
                    state="done",
                    task_id=task_id,
                    event_id=event_id,
                    wordpress_url=reference.get("url"),
                )
            else:
                calendar_link_state = "no-wordpress-url"
                emit_progress(
                    "wordpress.calendar_link",
                    "WordPress did not provide a daily-log URL to link.",
                    state="done",
                    task_id=task_id,
                    event_id=event_id,
                )
        timings["calendar_link_ms"] = _elapsed_ms(link_started)

    timings["total_ms"] = _elapsed_ms(started)
    return {
        "ok": True,
        "message": "WordPress integration follow-up finished.",
        "wordpress": {
            "delivery_owner": "background-service",
            "pending": pending,
            "calendar_link_state": calendar_link_state,
            "reference": reference,
        },
        "timings": timings,
    }


def note(message: dict[str, Any]) -> dict[str, Any]:
    task_id = str(message.get("task_id") or "").strip()
    text = str(message.get("text") or "").strip()
    at = parse_at(message.get("at"))
    if not text:
        raise ValueError("note text is required")

    emit_progress(
        "wordpress.queue",
        "Saving the note to the durable WordPress Outbox...",
        state="started",
        task_id=task_id,
    )
    result = app().ctx.wordpress.queue_log(text, _logged_at=at.isoformat())
    pending = _wordpress_pending_count()
    emit_progress(
        "wordpress.queue",
        "Note saved to the WordPress Outbox.",
        state="done",
        task_id=task_id,
        pending=pending,
    )
    return {
        "ok": True,
        "message": getattr(
            result,
            "message",
            "Saved to WordPress Outbox; background upload pending.",
        ),
        "wordpress": {"queued": True, "pending": pending},
        "follow_up": {
            "command": "wordpress_sync",
            "task_id": task_id,
            "at": at.isoformat(),
            "calendar_link": bool(message.get("calendar_link", True)),
        },
    }


def _attachment_store() -> Path:
    store = Path.home() / ".caldav-assistant" / "thunderbird-attachments"
    store.mkdir(parents=True, exist_ok=True)
    return store


def _finish_staged_attachment(state: dict[str, Any]) -> dict[str, Any]:
    path = Path(state["path"])
    at = state["at"]
    task_id = state["task_id"]
    mime_type = state["mime_type"]

    result = core_call(
        "wordpress.attach_file",
        path=str(path),
        _logged_at=at.isoformat(),
        mime_type=mime_type,
    )
    affected = getattr(result, "affected", None)
    payload = affected if isinstance(affected, dict) else {}
    file_url = str(payload.get("url") or "")
    post_url = str(payload.get("post_url") or "")

    event_id = latest_work_event_id(task_id)
    if state["calendar_link"] and event_id:
        attachment_urls = [file_url] if state["attachment_link"] and file_url else []
        try:
            core_call(
                "worklog.add_references",
                event_id=event_id,
                wordpress_url=post_url or None,
                attachment_urls=attachment_urls,
            )
        except Exception:
            pass

    if file_url:
        try:
            path.unlink()
        except OSError:
            pass

    return {
        "ok": True,
        "message": getattr(result, "message", "Attachment recorded."),
        "url": file_url or None,
        "post_url": post_url or None,
        "queued": not bool(file_url),
    }


def attachment_begin(message: dict[str, Any]) -> dict[str, Any]:
    task_id = str(message.get("task_id") or "").strip()
    if not task_id:
        raise ValueError("task_id is required")
    filename = Path(str(message.get("filename") or "attachment")).name
    mime_type = str(message.get("mime_type") or "application/octet-stream")
    at = parse_at(message.get("at"))
    total_size = int(message.get("total_size") or 0)
    if total_size < 0:
        raise ValueError("total_size must not be negative")

    upload_id = uuid4().hex
    path = _attachment_store() / f"{upload_id}-{filename}"
    path.write_bytes(b"")
    UPLOADS[upload_id] = {
        "path": str(path),
        "task_id": task_id,
        "filename": filename,
        "mime_type": mime_type,
        "at": at,
        "total_size": total_size,
        "received": 0,
        "calendar_link": bool(message.get("calendar_link", True)),
        "attachment_link": bool(message.get("attachment_link", False)),
    }
    return {"ok": True, "upload_id": upload_id}


def attachment_chunk(message: dict[str, Any]) -> dict[str, Any]:
    upload_id = str(message.get("upload_id") or "").strip()
    state = UPLOADS.get(upload_id)
    if state is None:
        raise ValueError("unknown upload_id")
    encoded = str(message.get("data_base64") or "")
    if not encoded:
        raise ValueError("attachment chunk is empty")
    data = base64.b64decode(encoded, validate=True)

    total_size = int(state["total_size"])
    next_size = int(state["received"]) + len(data)
    if total_size and next_size > total_size:
        raise ValueError("attachment exceeds declared total_size")

    with Path(state["path"]).open("ab") as stream:
        stream.write(data)
    state["received"] = next_size
    return {
        "ok": True,
        "upload_id": upload_id,
        "received": next_size,
        "total_size": total_size,
    }


def attachment_finish(message: dict[str, Any]) -> dict[str, Any]:
    upload_id = str(message.get("upload_id") or "").strip()
    state = UPLOADS.get(upload_id)
    if state is None:
        raise ValueError("unknown upload_id")
    if int(state["received"]) != int(state["total_size"]):
        raise ValueError(
            f"attachment incomplete: received {state['received']} of {state['total_size']} bytes"
        )
    result = _finish_staged_attachment(state)
    UPLOADS.pop(upload_id, None)
    return result


def attachment_abort(message: dict[str, Any]) -> dict[str, Any]:
    upload_id = str(message.get("upload_id") or "").strip()
    state = UPLOADS.pop(upload_id, None)
    if state is not None:
        try:
            Path(state["path"]).unlink()
        except OSError:
            pass
    return {"ok": True, "upload_id": upload_id, "aborted": state is not None}


def attachment(message: dict[str, Any]) -> dict[str, Any]:
    """Compatibility one-shot attachment path used by older experimental XPI builds."""
    begin = attachment_begin(
        {
            **message,
            "total_size": len(base64.b64decode(str(message.get("data_base64") or ""), validate=True)),
        }
    )
    upload_id = begin["upload_id"]
    try:
        attachment_chunk(
            {
                "upload_id": upload_id,
                "data_base64": message.get("data_base64"),
            }
        )
        return attachment_finish({"upload_id": upload_id})
    except Exception:
        attachment_abort({"upload_id": upload_id})
        raise


def dispatch(message: dict[str, Any]) -> dict[str, Any]:
    command = str(message.get("command") or "")
    if command == "state":
        return state_snapshot()
    if command == "activity_today":
        return activity_today()
    if command == "snapshot":
        return snapshot()
    if command == "action":
        return action(message)
    if command == "wordpress_sync":
        return wordpress_sync(message)
    if command == "note":
        return note(message)
    if command == "attachment_begin":
        return attachment_begin(message)
    if command == "attachment_chunk":
        return attachment_chunk(message)
    if command == "attachment_finish":
        return attachment_finish(message)
    if command == "attachment_abort":
        return attachment_abort(message)
    if command == "attachment":
        return attachment(message)
    if command == "logs":
        return {
            "ok": True,
            "lines": log_lines(int(message.get("limit") or 300)),
            "path": str(LOG_PATH),
        }
    if command == "logs_clear":
        clear_logs()
        return {"ok": True, "cleared": True, "path": str(LOG_PATH)}
    if command == "logs_open":
        return open_log_folder()
    if command == "ping":
        return {"ok": True, "name": "CalDAV Assistant Thunderbird host"}
    raise ValueError(f"unsupported command: {command}")


def main() -> int:
    log_event("native_host_started")

    def progress_sink(payload: dict[str, Any]) -> None:
        write_message({"ok": True, "kind": "progress", **payload})

    bind_progress_sink(progress_sink)

    while True:
        message: dict[str, Any] | None = None
        started: float | None = None
        try:
            message = read_message()
            if message is None:
                for state in list(UPLOADS.values()):
                    try:
                        Path(state["path"]).unlink()
                    except OSError:
                        pass
                UPLOADS.clear()
                log_event("native_host_stopped")
                return 0

            # Start request timing only after a complete Native Messaging request has
            # arrived.  Idle time between requests is not request latency.
            started = time.perf_counter()
            command = str(message.get("command") or "")
            operation_id = str(message.get("operation_id") or "").strip() or None
            with operation_scope(operation_id):
                result = dispatch(message)
            total_ms = _elapsed_ms(started)
            if isinstance(result, dict):
                timings = result.setdefault("timings", {})
                if isinstance(timings, dict):
                    timings.setdefault("host_total_ms", total_ms)

            if command not in {"logs", "logs_clear", "logs_open"}:
                log_event(
                    "request",
                    command=command,
                    ok=True,
                    total_ms=total_ms,
                    timings=result.get("timings") if isinstance(result, dict) else None,
                )
            write_message(result)
        except Exception as exc:
            command = str((message or {}).get("command") or "")
            total_ms = _elapsed_ms(started) if started is not None else 0.0
            log_event(
                "request",
                command=command,
                ok=False,
                total_ms=total_ms,
                error=f"{type(exc).__name__}: {exc}",
            )
            write_message({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    raise SystemExit(main())
