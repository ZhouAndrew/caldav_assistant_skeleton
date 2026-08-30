"""Internal operation-progress channel.

This module carries one request-scoped operation id through service-side code and
publishes factual progress milestones to an optional runtime sink. It is deliberately
internal: public Easy/Object/Full APIs remain unchanged.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Iterator


_current_operation_id: ContextVar[str | None] = ContextVar(
    "caldav_assistant_operation_id",
    default=None,
)
_progress_sink: Callable[[dict[str, Any]], Any] | None = None


def bind_progress_sink(sink: Callable[[dict[str, Any]], Any] | None) -> None:
    global _progress_sink
    if sink is not None and not callable(sink):
        raise TypeError("progress sink must be callable or None")
    _progress_sink = sink


@contextmanager
def operation_scope(operation_id: str | None) -> Iterator[None]:
    clean = str(operation_id or "").strip() or None
    token = _current_operation_id.set(clean)
    try:
        yield
    finally:
        _current_operation_id.reset(token)


def emit_progress(
    stage: str,
    message: str,
    *,
    state: str = "info",
    **details: Any,
) -> None:
    operation_id = _current_operation_id.get()
    sink = _progress_sink
    if operation_id is None or sink is None:
        return
    payload = {
        "operation_id": operation_id,
        "stage": str(stage),
        "message": str(message),
        "state": str(state),
        "details": dict(details),
    }
    try:
        sink(payload)
    except Exception:
        # Progress reporting must never change the authoritative operation outcome.
        return


__all__ = ["bind_progress_sink", "emit_progress", "operation_scope"]
