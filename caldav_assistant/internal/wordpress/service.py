"""Reliable WordPress application service backed by a local Outbox.

CalDAV actions never depend on WordPress availability.  Every mutation is written to
the durable Outbox before transport is attempted; ``queue_log`` deliberately skips
the immediate transport attempt for non-blocking Core side effects.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from ...api import ActionResult
from ...api.v1.errors import ValidationError


class WordPressService:
    """Canonical WordPress business layer above an adapter + durable Outbox."""

    _SCHEMA_VERSION = 1
    _OPERATIONS = frozenset({"create_log", "create_post", "update_post"})

    def __init__(self, adapter: Any, outbox: Any, activity: Any = None) -> None:
        self.adapter = adapter
        self.outbox = outbox
        self.activity = activity

    @staticmethod
    def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
        if not isinstance(value, str):
            raise ValidationError(f"{name} must be text")
        value = value.strip()
        if not allow_empty and not value:
            raise ValidationError(f"{name} must not be empty")
        return value

    @staticmethod
    def _post_id(value: Any) -> str | int:
        if isinstance(value, bool) or value is None:
            raise ValidationError("WordPress post id must not be empty")
        if isinstance(value, int):
            if value <= 0:
                raise ValidationError("WordPress post id must be positive")
            return value
        if isinstance(value, str) and value.strip():
            return value.strip()
        raise ValidationError("WordPress post id must be text or a positive integer")

    @classmethod
    def _payload(cls, operation: str, args: dict[str, Any]) -> dict[str, Any]:
        if operation not in cls._OPERATIONS:
            raise ValidationError(f"Unsupported WordPress operation: {operation}")
        return {
            "schema": cls._SCHEMA_VERSION,
            "request_id": uuid4().hex,
            "operation": operation,
            "args": deepcopy(args),
        }

    @staticmethod
    def _log_transport_metadata(
        metadata: dict[str, Any],
        *,
        request_id: str,
    ) -> dict[str, Any]:
        result = deepcopy(metadata)
        # Capture the human action time before the Outbox write.  If WordPress is
        # offline until tomorrow, retry must still append to the day on which the
        # user actually wrote the log.
        result.setdefault("_logged_at", datetime.now().astimezone().isoformat())
        result["_request_id"] = request_id
        return result

    def _record(self, action: str, object_id: Any = None, **metadata: Any) -> None:
        if self.activity is not None:
            value = None if object_id is None else str(object_id)
            self.activity.record(action, value, **metadata)

    def _deliver_payload(self, payload: dict[str, Any]) -> Any:
        operation = payload.get("operation")
        args = payload.get("args")
        if operation not in self._OPERATIONS or not isinstance(args, dict):
            raise ValueError("Malformed WordPress Outbox payload")

        if operation == "create_log":
            metadata = args.get("metadata") or {}
            if not isinstance(metadata, dict):
                raise ValueError("Malformed create_log metadata")
            return self.adapter.create_log(args["text"], **metadata)

        if operation == "create_post":
            fields = args.get("fields") or {}
            if not isinstance(fields, dict):
                raise ValueError("Malformed create_post fields")
            return self.adapter.create_post(
                args["title"],
                args.get("content", ""),
                **fields,
            )

        changes = args.get("changes") or {}
        if not isinstance(changes, dict):
            raise ValueError("Malformed update_post changes")
        return self.adapter.update_post(args["post_id"], **changes)

    @staticmethod
    def _remote_object_id(operation: str, result: Any, payload: dict[str, Any]) -> Any:
        if operation == "update_post":
            return payload["args"].get("post_id")
        if isinstance(result, dict):
            for key in ("id", "ID", "post_id"):
                if result.get(key) is not None:
                    return result[key]
        for name in ("id", "ID", "post_id"):
            if hasattr(result, name):
                value = getattr(result, name)
                if value is not None:
                    return value
        if isinstance(result, (str, int)) and not isinstance(result, bool):
            return result
        return None

    def _record_delivery(self, operation: str, result: Any, payload: dict[str, Any]) -> None:
        object_id = self._remote_object_id(operation, result, payload)
        action = {
            "create_log": "wordpress_log_created",
            "create_post": "wordpress_post_created",
            "update_post": "wordpress_post_updated",
        }[operation]
        self._record(action, object_id, request_id=payload.get("request_id"))

    def _mark_failed(self, item_id: int, exc: Exception) -> None:
        try:
            self.outbox.mark_failed(item_id, exc)
        except Exception:
            pass

    def _queue_and_try(self, payload: dict[str, Any]) -> ActionResult:
        item = self.outbox.enqueue(payload)
        item_id = int(item["id"])

        try:
            result = self._deliver_payload(payload)
        except Exception as exc:
            self._mark_failed(item_id, exc)
            return ActionResult(
                True,
                message="Saved locally; WordPress upload pending.",
                affected=item,
            )

        try:
            self.outbox.mark_sent(item_id)
        except Exception as exc:
            self._mark_failed(item_id, exc)
            self._record_delivery(payload["operation"], result, payload)
            return ActionResult(
                True,
                message=(
                    "Uploaded to WordPress, but local Outbox acknowledgement failed; "
                    "the item remains pending and may be retried."
                ),
                affected=result,
            )

        self._record_delivery(payload["operation"], result, payload)
        return ActionResult(True, message="Uploaded to WordPress.", affected=result)

    def _queue_only(self, payload: dict[str, Any]) -> ActionResult:
        item = self.outbox.enqueue(payload)
        return ActionResult(
            True,
            message="Saved to WordPress Outbox; background upload pending.",
            affected=item,
        )

    def _log_payload(self, text: str, metadata: dict[str, Any]) -> dict[str, Any]:
        payload = self._payload("create_log", {"text": text, "metadata": {}})
        payload["args"]["metadata"] = self._log_transport_metadata(
            metadata,
            request_id=payload["request_id"],
        )
        return payload

    # Frozen public Object API -------------------------------------------------
    def log(self, text: str, **metadata: Any) -> ActionResult:
        clean = self._text(text, "WordPress log")
        return self._queue_and_try(self._log_payload(clean, metadata))

    def queue_log(self, text: str, **metadata: Any) -> ActionResult:
        clean = self._text(text, "WordPress log")
        return self._queue_only(self._log_payload(clean, metadata))

    def create_post(self, title: str, content: str = "", **fields: Any) -> ActionResult:
        clean_title = self._text(title, "WordPress post title")
        clean_content = self._text(content, "WordPress post content", allow_empty=True)
        payload = self._payload(
            "create_post",
            {"title": clean_title, "content": clean_content, "fields": deepcopy(fields)},
        )
        return self._queue_and_try(payload)

    def update_post(self, post_id: Any, **changes: Any) -> ActionResult:
        clean_id = self._post_id(post_id)
        if not changes:
            raise ValidationError("No WordPress post changes supplied")
        payload = self._payload(
            "update_post",
            {"post_id": clean_id, "changes": deepcopy(changes)},
        )
        return self._queue_and_try(payload)

    def pending(self, limit: int | None = None) -> list[dict[str, Any]]:
        return list(self.outbox.pending(limit=limit))

    def flush(self, limit: int | None = None) -> dict[str, int]:
        items = list(self.outbox.pending(limit=limit))
        sent = 0
        failed = 0
        for item in items:
            item_id = int(item["id"])
            payload = item.get("payload")
            try:
                if not isinstance(payload, dict):
                    raise ValueError("Malformed WordPress Outbox item")
                result = self._deliver_payload(payload)
                self.outbox.mark_sent(item_id)
            except Exception as exc:
                failed += 1
                self._mark_failed(item_id, exc)
                continue
            sent += 1
            self._record_delivery(payload["operation"], result, payload)

        return {
            "attempted": len(items),
            "sent": sent,
            "failed": failed,
            "pending": len(self.outbox.pending()),
        }

    def test_connection(self) -> bool:
        try:
            return bool(self.adapter.test_connection())
        except Exception:
            return False
