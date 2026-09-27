"""Native Messaging bridge used by the Thunderbird CalDAV Assistant add-on."""
from __future__ import annotations

import base64
from contextlib import redirect_stdout
from dataclasses import fields, is_dataclass
from datetime import date, datetime
import json
from pathlib import Path
import re
import struct
import sys
from typing import Any
from uuid import uuid4

from ..bootstrap import build_cli_application


HOST_NAME = "org.caldav_assistant.thunderbird"
EXTENSION_ID = "caldav-assistant@zhouandrew.local"
_MAX_NATIVE_MESSAGE = 64 * 1024 * 1024
_ATTACHMENT_ROOT = Path.home() / ".caldav-assistant" / "thunderbird-attachments"


def _jsonable(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        result = {}
        for field in fields(value):
            if field.name.startswith("_"):
                continue
            result[field.name] = _jsonable(getattr(value, field.name))
        return result
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _read_message(stream: Any) -> dict[str, Any] | None:
    header = stream.read(4)
    if not header:
        return None
    if len(header) != 4:
        raise EOFError("Incomplete Native Messaging header")
    length = struct.unpack("<I", header)[0]
    if length > _MAX_NATIVE_MESSAGE:
        raise ValueError("Native Messaging request is too large")
    payload = stream.read(length)
    if len(payload) != length:
        raise EOFError("Incomplete Native Messaging message")
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Native Messaging request must be a JSON object")
    return value


def _write_message(stream: Any, value: dict[str, Any]) -> None:
    payload = json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    stream.write(struct.pack("<I", len(payload)))
    stream.write(payload)
    stream.flush()


def _safe_filename(value: Any) -> str:
    name = Path(str(value or "attachment.bin")).name.strip() or "attachment.bin"
    name = re.sub(r"[^A-Za-z0-9._()\- ]+", "_", name)
    return name[:180] or "attachment.bin"


class ThunderbirdBridge:
    def __init__(self, application: Any = None) -> None:
        if application is None:
            with redirect_stdout(sys.stderr):
                application = build_cli_application()
        self.application = application
        self.ctx = application.ctx
        self.runtime = application.runtime

    def _snapshot(self) -> dict[str, Any]:
        tasks = [
            task
            for task in self.ctx.tasks.list()
            if not bool(getattr(task, "completed", False))
            and str(getattr(task, "status", "") or "") != "CANCELLED"
        ]
        current_id = self.ctx.session.current_task_id()
        paused_ids = list(self.ctx.session.paused_task_ids())
        return {
            "tasks": tasks,
            "current_task_id": current_id,
            "paused_task_ids": paused_ids,
            "wordpress_pending": len(self.ctx.wordpress.pending()),
        }

    @staticmethod
    def _task_id(message: dict[str, Any]) -> str:
        value = str(message.get("task_id") or "").strip()
        if not value:
            raise ValueError("task_id is required")
        return value

    def _action(self, message: dict[str, Any]) -> Any:
        action = str(message.get("action") or "").strip().casefold()
        task_id = self._task_id(message)
        at = message.get("at")
        if action == "start":
            paused = set(self.ctx.session.paused_task_ids())
            if task_id in paused:
                return self.ctx.tasks.resume(task_id, at=at)
            return self.ctx.tasks.start(task_id, at=at)
        if action == "pause":
            return self.ctx.tasks.pause(task_id, at=at)
        if action == "cancel":
            return self.ctx.tasks.cancel(task_id, at=at)
        if action == "complete":
            return self.ctx.tasks.complete(task_id, at=at)
        raise ValueError("action must be start, pause, cancel, or complete")

    def _related_work_event_id(self, task_id: str) -> str | None:
        try:
            current = self.runtime.call("worklog.open_for", task=task_id)
        except Exception:
            current = None
        event_id = str(getattr(current, "id", "") or "").strip()
        if event_id:
            return event_id

        try:
            segments = list(
                self.runtime.call("worklog.segments_for", task=task_id) or ()
            )
        except Exception:
            return None
        if not segments:
            return None
        event = segments[-1]
        value = str(getattr(event, "id", "") or "").strip()
        return value or None

    def _log(self, message: dict[str, Any]) -> Any:
        text = str(message.get("text") or "").strip()
        if not text:
            raise ValueError("log text must not be empty")
        metadata: dict[str, Any] = {}
        at = message.get("at")
        if at:
            metadata["_logged_at"] = at
        return self.ctx.wordpress.log(text, **metadata)

    def _attachment(self, message: dict[str, Any]) -> Any:
        encoded = str(message.get("data_base64") or "")
        if not encoded:
            raise ValueError("attachment data is required")
        try:
            data = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise ValueError("attachment data is not valid base64") from exc

        _ATTACHMENT_ROOT.mkdir(parents=True, exist_ok=True)
        name = _safe_filename(message.get("name"))
        path = _ATTACHMENT_ROOT / f"{uuid4().hex}-{name}"
        path.write_bytes(data)

        task_id = str(message.get("task_id") or "").strip()
        work_event_id = (
            str(message.get("work_event_id") or "").strip()
            or (self._related_work_event_id(task_id) if task_id else None)
        )
        metadata: dict[str, Any] = {
            "filename": name,
            "mime_type": str(message.get("mime_type") or ""),
            "_calendar_link": bool(message.get("calendar_link", True)),
            "_calendar_attachment_link": bool(
                message.get("calendar_attachment_link", False)
            ),
            "_work_event_id": work_event_id,
        }
        at = message.get("at")
        if at:
            metadata["_logged_at"] = at
        return self.ctx.wordpress.attach_file(path, **metadata)

    def handle(self, message: dict[str, Any]) -> dict[str, Any]:
        kind = str(message.get("type") or "").strip().casefold()
        with redirect_stdout(sys.stderr):
            if kind == "ping":
                result: Any = {
                    "host": HOST_NAME,
                    "extension_id": EXTENSION_ID,
                }
            elif kind == "snapshot":
                result = self._snapshot()
            elif kind == "action":
                result = self._action(message)
            elif kind == "log":
                result = self._log(message)
            elif kind == "attachment":
                result = self._attachment(message)
            elif kind == "sync_wordpress":
                result = self.runtime.call("wordpress.flush")
            else:
                raise ValueError(
                    "type must be ping, snapshot, action, log, attachment, or sync_wordpress"
                )
        return {"ok": True, "result": _jsonable(result)}


def main() -> int:
    bridge: ThunderbirdBridge | None = None
    input_stream = sys.stdin.buffer
    output_stream = sys.stdout.buffer

    while True:
        try:
            message = _read_message(input_stream)
            if message is None:
                return 0
            if bridge is None:
                bridge = ThunderbirdBridge()
            response = bridge.handle(message)
        except Exception as exc:
            response = {
                "ok": False,
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            }
        _write_message(output_stream, response)


if __name__ == "__main__":
    raise SystemExit(main())
