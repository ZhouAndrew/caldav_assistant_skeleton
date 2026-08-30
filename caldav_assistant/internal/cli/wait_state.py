"""Two-state desktop Assistant view derived from the authoritative Session service.

The interactive client has only two long-lived human states:

* waiting for a command; or
* waiting for the human to finish the current Task.

Reminders, Events, due times, and allocated-work-time expirations are transient events.
They may interrupt the screen, but they do not create a third persistent state and
must not silently mutate a Task.  The current Task comes from SessionService, which
in turn is backed by the existing Task/work-session semantics.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


WaitKind = Literal["command", "task"]


@dataclass(frozen=True, slots=True)
class WaitState:
    kind: WaitKind
    task_id: str | None = None
    summary: str | None = None

    @property
    def key(self) -> tuple[str, str | None]:
        return self.kind, self.task_id


def _summary(task: Any) -> str:
    text = str(getattr(task, "summary", "") or "").strip()
    if text:
        return text
    uid = str(getattr(task, "id", "") or "").strip()
    return uid or "Task"


def current_wait_state(ctx: Any) -> WaitState:
    """Derive the desktop wait state without owning any additional state."""
    session = getattr(ctx, "session", None)
    getter = getattr(session, "current_task", None)
    if not callable(getter):
        return WaitState("command")

    try:
        task = getter()
    except Exception:
        # REPL presentation must never become a second failure path for a Core
        # operation.  The underlying command will still surface its own error.
        return WaitState("command")

    if task is None:
        return WaitState("command")

    uid = str(getattr(task, "id", "") or "").strip() or None
    return WaitState("task", task_id=uid, summary=_summary(task))


def prompt_for(state: WaitState) -> str:
    if state.kind == "task":
        return f"[doing: {state.summary or 'Task'}] > "
    return "> "


def message_for(state: WaitState) -> str:
    if state.kind == "task":
        return (
            f"Working: {state.summary or 'Task'}. "
            "The Assistant is waiting for you to finish it. "
            "Use 'done' when finished or 'pause' to stop for now."
        )
    return "Ready. The Assistant is waiting for a command."


__all__ = ["WaitState", "current_wait_state", "prompt_for", "message_for"]
