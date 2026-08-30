"""Observable background Assistant Service for foreground monitor clients.

The ordinary AssistantService remains the scheduler/orchestrator. This subclass adds
one internal, read-only delivery feed over Local IPC. A feed event is published only
after ReminderService.process_due() has successfully returned that notification as
sent, so the foreground never invents a reminder event of its own.

This is an internal client/runtime contract, not part of the frozen public Python API.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any
import signal

from .ipc import IPCAlreadyRunningError
from .service import AssistantService


class ObservableAssistantService(AssistantService):
    """AssistantService plus a bounded notification-delivery event feed."""

    def __init__(self, *args: Any, event_limit: int = 200, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.event_limit = int(event_limit)
        if self.event_limit <= 0:
            raise ValueError("event_limit must be positive")
        self._event_seq = 0
        self._delivery_events: deque[dict[str, Any]] = deque(maxlen=self.event_limit)

    @staticmethod
    def _request_value(request: Any, name: str, default: Any = None) -> Any:
        value = getattr(request, name, default)
        if callable(value):
            try:
                value = value()
            except Exception:
                return default
        return value

    def _publish_delivery(self, request: Any) -> None:
        when = self._request_value(request, "when", None)
        if isinstance(when, datetime):
            when_text = when.isoformat()
        else:
            when_text = str(when) if when is not None else None

        metadata = self._request_value(request, "metadata", {})
        if not isinstance(metadata, dict):
            metadata = {"value": str(metadata)}

        # Explicit Assistant reminders normally have source="reminder" and their
        # object id is the reminder id.  Work-period deadlines deliberately carry a
        # semantic source/task id in metadata so the foreground can report the human
        # event without changing the frozen ReminderEngine request contract.
        source = str(metadata.get("source") or self._request_value(request, "source", "reminder") or "reminder")
        object_id = metadata.get("task_id") or self._request_value(request, "object_id", None)

        adapter = getattr(getattr(self.reminders, "notifications", None), "adapter", None)
        adapter_name = type(adapter).__name__ if adapter is not None else None

        with self._lock:
            self._event_seq += 1
            self._delivery_events.append(
                {
                    "seq": self._event_seq,
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                    "scheduled_for": when_text,
                    "source": source,
                    "object_id": object_id,
                    "title": str(self._request_value(request, "title", "") or ""),
                    "body": str(self._request_value(request, "body", "") or ""),
                    "delivery_key": str(self._request_value(request, "key", "") or ""),
                    "metadata": dict(metadata),
                    "delivery": "system_notification",
                    "adapter": adapter_name,
                    "result": "delivered",
                }
            )

    def _process_due_observable(self) -> list[Any]:
        process = getattr(self.reminders, "process_due", None)
        if not callable(process):
            return []
        try:
            sent = list(process() or ())
        except Exception as exc:
            self._record_error("reminders.process_due", exc)
            return []

        with self._lock:
            self._last_success["reminders.process_due"] = datetime.now(timezone.utc).isoformat()
            self._last_errors.pop("reminders.process_due", None)
        for request in sent:
            self._publish_delivery(request)
        return sent

    def _run_reminder_cycle(self) -> None:
        self._process_due_observable()
        delay = self._reminder_delay()
        if delay <= 0:
            delay = min(self.max_idle, 5.0)
        with self._lock:
            self._next_reminder_wake = self.scheduler.monotonic() + delay

    def run_maintenance_once(self) -> None:
        incremental = getattr(self.sync, "incremental_sync", None) or getattr(
            self.sync, "refresh", None
        )
        self._run_one("sync.incremental", incremental)
        self._process_due_observable()
        self._run_one("wordpress.flush", getattr(self.wordpress, "flush", None))

    def delivery_cursor(self) -> int:
        with self._lock:
            return self._event_seq

    def delivery_events(self, after: int = 0, limit: int = 50) -> list[dict[str, Any]]:
        after = max(0, int(after))
        limit = max(1, min(int(limit), self.event_limit))
        with self._lock:
            items = [item.copy() for item in self._delivery_events if int(item["seq"]) > after]
        return items[:limit]

    def _handle_request(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        payload = payload or {}
        if method == "runtime.events.cursor":
            return {"cursor": self.delivery_cursor()}
        if method == "runtime.events.list":
            return self.delivery_events(
                after=payload.get("after", 0),
                limit=payload.get("limit", 50),
            )
        return super()._handle_request(method, payload)

    def status(self) -> dict[str, Any]:
        value = super().status()
        value["delivery_event_cursor"] = self.delivery_cursor()
        return value


def build_observable_service() -> ObservableAssistantService:
    from ..bootstrap import build_service_application

    application = build_service_application()
    base = application.background
    return ObservableAssistantService(
        base.sync,
        base.reminders,
        base.wordpress,
        base.ipc_server,
        base.dispatcher,
        base.scheduler,
        sync_interval=base.sync_interval,
        wordpress_interval=base.wordpress_interval,
        max_idle=base.max_idle,
    )


def main() -> int:
    service = build_observable_service()

    def request_stop(signum: int, frame: Any) -> None:
        service.stop()

    for name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, request_stop)
            except (ValueError, OSError):
                pass

    try:
        service.run_forever()
    except IPCAlreadyRunningError:
        # Preserve the singleton launch contract of the original service entrypoint:
        # a concurrent losing launcher exits cleanly after the real daemon owns IPC.
        return 0
    except KeyboardInterrupt:
        service.stop()
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ObservableAssistantService", "build_observable_service", "main"]
