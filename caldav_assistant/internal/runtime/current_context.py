"""Process-local binding used by the synchronous Easy API.

MODULE CONTRACT
- Imports: stable public errors only.
- Provides: bind/get/clear helpers for the current AssistantContext.
- Called by: composition roots and ``caldav_assistant.easy``.
- Must not: build services, open IPC, perform business operations, or expose this
  helper as a public extension requirement.

Easy extensions never call these functions themselves.  The bootstrap composition
root binds the already-composed public context before extensions are executed.
"""
from __future__ import annotations

from typing import Any

from ...api.v1.errors import UnavailableError


_current_context: Any | None = None


def bind_current_context(ctx: Any) -> Any | None:
    """Bind one already-composed AssistantContext for this process.

    Returns the previous value as a small internal convenience.  No service or
    adapter is constructed here.
    """
    if ctx is None:
        raise ValueError("AssistantContext must not be None")

    global _current_context
    previous = _current_context
    _current_context = ctx
    return previous


def get_current_context() -> Any:
    """Return the process' current AssistantContext or a stable public error."""
    if _current_context is None:
        raise UnavailableError(
            "AssistantContext is not bound in this process. "
            "Build the CalDAV Assistant application before using the Easy API."
        )
    return _current_context


def clear_current_context() -> Any | None:
    """Clear the internal binding; primarily useful for isolated tests."""
    global _current_context
    previous = _current_context
    _current_context = None
    return previous


__all__ = [
    "bind_current_context",
    "get_current_context",
    "clear_current_context",
]
