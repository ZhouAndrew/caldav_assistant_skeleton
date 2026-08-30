"""Shared foreground runner for factual, request-scoped operation progress.

The business operation still runs through the normal CommandService/Object API and
Local IPC.  This helper only keeps the terminal responsive while that synchronous
operation is in flight: it tags the request with an internal operation id and reads
runtime progress events produced by the executing Core services.

No step is predicted here.  If Core never emits a milestone, this helper never
claims that milestone happened.
"""
from __future__ import annotations

from queue import Empty, Queue
from threading import Thread
from time import sleep
from typing import Any, Callable
from uuid import uuid4


def _runtime(app: Any) -> Any:
    return getattr(app, "runtime", None)


def _runtime_call(app: Any, method: str, **payload: Any) -> Any:
    runtime = _runtime(app)
    call = getattr(runtime, "call", None)
    if not callable(call):
        raise RuntimeError("This client has no background Runtime connection")
    return call(method, **payload)


def _cursor(app: Any) -> int:
    value = _runtime_call(app, "runtime.events.cursor")
    if isinstance(value, dict):
        return int(value.get("cursor", 0) or 0)
    return 0


def _events(app: Any, after: int) -> list[dict[str, Any]]:
    value = _runtime_call(app, "runtime.events.list", after=int(after), limit=50)
    return [item for item in (value or ()) if isinstance(item, dict)]


def _tag_runtime_call(runtime: Any, operation_id: str):
    original = getattr(runtime, "call", None)
    if not callable(original):
        return None

    def tagged(method: str, **payload: Any) -> Any:
        body = dict(payload)
        body.setdefault("__operation_id", operation_id)
        return original(method, **body)

    runtime.call = tagged
    return original


def run_with_live_progress(
    app: Any,
    operation: Callable[[], Any],
    *,
    on_progress: Callable[[dict[str, Any]], Any],
    on_delivery: Callable[[dict[str, Any]], Any] | None = None,
    poll_interval: float = 0.05,
) -> Any:
    """Run one synchronous foreground operation while streaming real milestones.

    If the application has no runtime event feed (for example a deliberately small
    unit-test context), execution falls back to the original synchronous behavior.
    Progress-feed failure never changes the authoritative operation result.
    """
    runtime = _runtime(app)
    if runtime is None or not callable(getattr(runtime, "call", None)):
        return operation()

    try:
        cursor = _cursor(app)
    except Exception:
        return operation()

    operation_id = uuid4().hex
    result: Queue[tuple[bool, Any]] = Queue(maxsize=1)

    def worker() -> None:
        original = _tag_runtime_call(runtime, operation_id)
        try:
            result.put((True, operation()))
        except BaseException as exc:
            result.put((False, exc))
        finally:
            if callable(original):
                runtime.call = original

    Thread(
        target=worker,
        name="caldav-assistant-live-command",
        daemon=True,
    ).start()

    outcome: tuple[bool, Any] | None = None
    while outcome is None:
        try:
            outcome = result.get_nowait()
        except Empty:
            pass

        try:
            for event in _events(app, cursor):
                cursor = max(cursor, int(event.get("seq", cursor) or cursor))
                if event.get("kind") == "operation_progress":
                    if event.get("operation_id") == operation_id:
                        on_progress(event)
                    continue
                if callable(on_delivery):
                    on_delivery(event)
        except Exception:
            # Observability is secondary.  It must never cancel or rewrite the
            # authoritative Core operation already in flight.
            pass

        if outcome is None:
            sleep(max(0.01, float(poll_interval)))

    # Drain events published just before the final IPC response reached the client.
    try:
        for event in _events(app, cursor):
            cursor = max(cursor, int(event.get("seq", cursor) or cursor))
            if event.get("kind") == "operation_progress":
                if event.get("operation_id") == operation_id:
                    on_progress(event)
                continue
            if callable(on_delivery):
                on_delivery(event)
    except Exception:
        pass

    ok, value = outcome
    if not ok:
        raise value
    return value


__all__ = ["run_with_live_progress"]
