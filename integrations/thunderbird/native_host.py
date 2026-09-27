#!/usr/bin/env python3
from __future__ import annotations

import base64
from datetime import datetime
import json
from pathlib import Path
import struct
import sys
from typing import Any
from uuid import uuid4

from caldav_assistant.internal.bootstrap import build_cli_application


APP = None


def app():
    global APP
    if APP is None:
        APP = build_cli_application()
    return APP


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


def latest_work_event_id(task_id: str) -> str | None:
    try:
        opened = app().runtime.call("worklog.open_for", task=task_id)
        event_id = str(getattr(opened, "id", "") or "").strip()
        if event_id:
            return event_id
    except Exception:
        pass

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


def link_event(event_id: str | None, *, at: datetime, attachment_urls=()) -> dict[str, Any] | None:
    if not event_id:
        return None
    try:
        reference = app().runtime.call("wordpress.daily_log_reference", at=at)
        url = str((reference or {}).get("url") or "").strip()
        if not url and not attachment_urls:
            return None
        app().runtime.call(
            "worklog.add_references",
            event_id=event_id,
            wordpress_url=url or None,
            attachment_urls=list(attachment_urls or ()),
        )
        return reference
    except Exception as exc:
        return {"pending": True, "error": f"{type(exc).__name__}: {exc}"}


def snapshot() -> dict[str, Any]:
    tasks = app().ctx.tasks.list()
    current_id = app().ctx.session.current_task_id()
    paused_ids = list(app().ctx.session.paused_task_ids())
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
        "tasks": [task_json(task) for task in tasks],
        "state": {
            "current_task_id": current_id,
            "paused_task_ids": paused_ids,
        },
        "today": today,
    }


def action(message: dict[str, Any]) -> dict[str, Any]:
    action_name = str(message.get("action") or "").strip()
    task_id = str(message.get("task_id") or "").strip()
    at = parse_at(message.get("at"))
    if not task_id:
        raise ValueError("task_id is required")

    tasks = app().ctx.tasks
    if action_name == "start":
        if task_id in app().ctx.session.paused_task_ids():
            result = tasks.resume(task_id, at=at)
            verb = "Started a new work segment"
        else:
            result = tasks.start(task_id, at=at)
            verb = "Started"
    elif action_name == "pause":
        result = tasks.pause(task_id, at=at)
        verb = "Paused"
    elif action_name == "cancel":
        result = tasks.cancel(task_id, at=at)
        verb = "Cancelled"
    elif action_name == "complete":
        result = tasks.complete(task_id, at=at)
        verb = "Completed"
    else:
        raise ValueError("unsupported action")

    wp = None
    if action_name in {"pause", "cancel", "complete"}:
        try:
            app().runtime.call("wordpress.flush")
            wp = {"message": "WordPress log updated"}
        except Exception as exc:
            wp = {"message": "WordPress update pending", "error": str(exc)}

        if bool(message.get("calendar_link", True)):
            event_id = latest_work_event_id(task_id)
            ref = link_event(event_id, at=at)
            if ref and ref.get("pending"):
                wp = wp or {}
                wp["calendar_link_pending"] = True

    return {
        "ok": True,
        "message": f"{verb} at {at.astimezone().strftime('%H:%M')}",
        "task": task_json(getattr(result, "affected", None)),
        "wordpress": wp,
    }


def note(message: dict[str, Any]) -> dict[str, Any]:
    task_id = str(message.get("task_id") or "").strip()
    text = str(message.get("text") or "").strip()
    at = parse_at(message.get("at"))
    if not text:
        raise ValueError("note text is required")
    result = app().ctx.wordpress.log(text, _logged_at=at.isoformat())
    reference = None
    if bool(message.get("calendar_link", True)):
        reference = link_event(latest_work_event_id(task_id), at=at)
    return {
        "ok": True,
        "message": getattr(result, "message", "Added to WordPress."),
        "wordpress": reference,
    }


def attachment(message: dict[str, Any]) -> dict[str, Any]:
    task_id = str(message.get("task_id") or "").strip()
    filename = Path(str(message.get("filename") or "attachment")).name
    mime_type = str(message.get("mime_type") or "application/octet-stream")
    at = parse_at(message.get("at"))
    encoded = str(message.get("data_base64") or "")
    if not encoded:
        raise ValueError("attachment data is empty")

    store = Path.home() / ".caldav-assistant" / "thunderbird-attachments"
    store.mkdir(parents=True, exist_ok=True)
    path = store / f"{uuid4().hex}-{filename}"
    path.write_bytes(base64.b64decode(encoded, validate=True))

    result = app().runtime.call(
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
    if bool(message.get("calendar_link", True)) and event_id:
        attachment_urls = [file_url] if bool(message.get("attachment_link", False)) and file_url else []
        try:
            app().runtime.call(
                "worklog.add_references",
                event_id=event_id,
                wordpress_url=post_url or None,
                attachment_urls=attachment_urls,
            )
        except Exception:
            pass

    return {
        "ok": True,
        "message": getattr(result, "message", "Attachment recorded."),
        "url": file_url or None,
        "post_url": post_url or None,
        "queued": not bool(file_url),
    }


def dispatch(message: dict[str, Any]) -> dict[str, Any]:
    command = str(message.get("command") or "")
    if command == "snapshot":
        return snapshot()
    if command == "action":
        return action(message)
    if command == "note":
        return note(message)
    if command == "attachment":
        return attachment(message)
    if command == "ping":
        return {"ok": True, "name": "CalDAV Assistant Thunderbird host"}
    raise ValueError(f"unsupported command: {command}")


def main() -> int:
    while True:
        try:
            message = read_message()
            if message is None:
                return 0
            write_message(dispatch(message))
        except Exception as exc:
            write_message({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    raise SystemExit(main())
